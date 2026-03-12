"""
Item Inspector - Backend API

Provides API endpoints for the Item Inspector page to lookup items
by barcode and retrieve comprehensive item snapshots including:
- Stock levels by warehouse
- Price history by price list
- Recent sales and purchase transactions
"""

from functools import lru_cache

import frappe
from frappe import _


@lru_cache(maxsize=64)
def _has_doctype(doctype: str) -> bool:
    """
    Check if a DocType exists in the system.

    Args:
        doctype: Name of the DocType to check

    Returns:
        True if the DocType exists, False otherwise
    """
    return bool(frappe.db.exists("DocType", doctype))


@lru_cache(maxsize=128)
def _has_field(doctype: str, fieldname: str) -> bool:
    """
    Check if a field exists in a DocType.

    Args:
        doctype: Name of the DocType
        fieldname: Name of the field to check

    Returns:
        True if the field exists in the DocType, False otherwise
    """
    try:
        meta = frappe.get_meta(doctype)
        return meta.has_field(fieldname) if meta else False
    except frappe.DoesNotExistError:
        return False
    except AttributeError:
        return False


def _first_existing_field(doctype: str, *fieldnames: str) -> str | None:
    """Return the first field that exists in the DocType."""
    for fieldname in fieldnames:
        if _has_field(doctype, fieldname):
            return fieldname
    return None


@lru_cache(maxsize=1)
def _get_pos_closing_child_doctype() -> str | None:
    """Get the child table used by POS Closing Entry to store POS invoices."""
    if not _has_doctype("POS Closing Entry"):
        return None

    try:
        meta = frappe.get_meta("POS Closing Entry")
    except frappe.DoesNotExistError:
        return None

    if not meta:
        return None

    table_fields = [df for df in meta.fields if getattr(df, "fieldtype", None) == "Table"]
    preferred_fields = sorted(table_fields, key=lambda df: 0 if df.fieldname == "pos_transactions" else 1)

    for field in preferred_fields:
        child_doctype = field.options if field and field.options else None
        if child_doctype and _has_doctype(child_doctype) and _has_field(child_doctype, "pos_invoice"):
            return child_doctype

    return None


@frappe.whitelist()
def resolve_item_from_barcode(barcode: str) -> dict:
    """
    Resolve an item code from a barcode string.

    Searches in multiple sources:
    1. Item Barcode child table (standard in v14/v15)
    2. Item.barcode field (legacy setups)
    3. Direct item_code match

    Args:
        barcode: The barcode string to search for

    Returns:
        dict with keys:
        - ok (bool): Whether the operation succeeded
        - item_code (str): The resolved item code (if single match)
        - matches (list): List of matching items (if multiple matches)
        - message (str): Error message (if failed)
    """
    barcode = (barcode or "").strip()
    if not barcode:
        return {"ok": False, "message": _("Empty barcode")}

    matches: list[str] = []

    # 1) Item Barcode child table (v14/v15 usually)
    if _has_doctype("Item Barcode"):
        rows = frappe.get_all(
            "Item Barcode",
            filters={"barcode": barcode},
            fields=["parent as item_code"],
            limit_page_length=20,
        )
        matches.extend([r["item_code"] for r in rows])

    # 2) Fallback: Item.barcode field (some setups)
    if not matches and _has_field("Item", "barcode"):
        item_code = frappe.db.get_value("Item", {"barcode": barcode}, "name")
        if item_code:
            matches.append(item_code)

    # 3) If user typed item_code directly
    if not matches and frappe.db.exists("Item", barcode):
        matches.append(barcode)

    # Normalize to unique values preserving order
    matches = list(dict.fromkeys(matches))

    if not matches:
        return {"ok": False, "message": _("No item found for barcode: {0}").format(barcode)}

    if len(matches) == 1:
        return {"ok": True, "item_code": matches[0]}

    # Multiple items share same barcode (rare but possible)
    items = frappe.get_all(
        "Item",
        filters={"name": ["in", matches]},
        fields=["name as item_code", "item_name", "image", "disabled"],
        limit_page_length=50,
    )
    return {"ok": True, "matches": items}


@frappe.whitelist()
def get_item_snapshot(item_code: str) -> dict:
    """
    Return a comprehensive dashboard-like snapshot for an item.

    Includes:
    - Basic item information (name, group, brand, UoM, etc.)
    - Barcodes associated with the item
    - Stock levels by warehouse with valuation rates
    - Price history by price list
    - Recent sales transactions (last 10)
    - Recent purchase transactions (last 10)

    Args:
        item_code: The item code to get snapshot for

    Returns:
        dict with keys:
        - ok (bool): Whether the operation succeeded
        - item (dict): Item master data
        - barcodes (list): List of barcode strings
        - bins (list): Stock by warehouse with valuation
        - price_history (list): Item prices by list
        - recent_sales (list): Last 10 sales
        - recent_purchases (list): Last 10 purchases
    """
    item_code = (item_code or "").strip()
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Item not found: {0}").format(item_code))

    item = _get_item_data(item_code)
    barcodes = _get_barcodes(item_code)
    bins = _get_stock_by_warehouse(item_code)
    price_rows = _get_price_history(item_code)
    recent_sales = _get_recent_sales(item_code)
    recent_purchases = _get_recent_purchases(item_code)
    recent_pos_sales_pending = _get_recent_pending_pos_sales(item_code)
    sales_last_30_days = _get_sales_last_30_days(item_code)
    selling_price = _get_default_selling_price(item_code)
    days_since_last_sale = _get_days_since_last_sale(item_code)

    return {
        "ok": True,
        "item": item,
        "barcodes": barcodes,
        "bins": bins,
        "price_history": price_rows,
        "recent_sales": recent_sales,
        "recent_purchases": recent_purchases,
        "recent_pos_sales_pending": recent_pos_sales_pending,
        "sales_last_30_days": sales_last_30_days,
        "selling_price": selling_price,
        "days_since_last_sale": days_since_last_sale,
    }


def _get_item_data(item_code: str) -> dict:
    """Get basic item master data."""
    item_fields = [
        "name as item_code",
        "item_name",
        "item_group",
        "brand",
        "stock_uom",
        "description",
        "image",
        "disabled",
        "is_stock_item",
    ]

    if _has_field("Item", "standard_rate"):
        item_fields.append("standard_rate")
    if _has_field("Item", "last_purchase_rate"):
        item_fields.append("last_purchase_rate")
    if _has_field("Item", "reorder_level"):
        item_fields.append("reorder_level")

    return frappe.db.get_value("Item", item_code, item_fields, as_dict=True) or {}


def _get_barcodes(item_code: str) -> list[str]:
    """Get all barcodes associated with an item."""
    if not _has_doctype("Item Barcode"):
        return []

    barcodes = frappe.get_all(
        "Item Barcode",
        filters={"parent": item_code},
        fields=["barcode"],
        order_by="idx asc",
        limit_page_length=50,
    )
    return [b["barcode"] for b in barcodes if b.get("barcode")]


def _get_stock_by_warehouse(item_code: str) -> list[dict]:
    """
    Get stock levels by warehouse with valuation rates.

    Uses ROW_NUMBER() for efficient latest valuation lookup.
    """
    bin_fields = ["warehouse", "actual_qty", "projected_qty", "reserved_qty", "ordered_qty"]

    if _has_field("Bin", "indented_qty"):
        bin_fields.append("indented_qty")
    if _has_field("Bin", "planned_qty"):
        bin_fields.append("planned_qty")

    bins = frappe.get_all(
        "Bin",
        filters={"item_code": item_code},
        fields=bin_fields,
        order_by="actual_qty desc",
        limit_page_length=500,
    )

    # Get latest valuation_rate by warehouse using ROW_NUMBER (optimized)
    valuation_by_wh = _get_valuation_rates(item_code)

    # Enrich bins with valuation + stock_value
    for b in bins:
        vr = valuation_by_wh.get(b["warehouse"], 0) or 0
        b["valuation_rate"] = vr
        b["stock_value_est"] = (b.get("actual_qty") or 0) * vr

    return bins


def _get_valuation_rates(item_code: str) -> dict[str, float]:
    """
    Get latest valuation rate by warehouse using optimized SQL with ROW_NUMBER().

    This is more efficient than the previous CONCAT-based approach
    as it uses window functions to get the latest entry per warehouse.

    Args:
        item_code: The item code to get valuation rates for

    Returns:
        dict mapping warehouse name to valuation rate
    """
    if not _has_doctype("Stock Ledger Entry"):
        return {}

    # Using ROW_NUMBER() for better performance
    rows = frappe.db.sql(
        """
        SELECT warehouse, valuation_rate
        FROM (
            SELECT
                warehouse,
                valuation_rate,
                ROW_NUMBER() OVER (
                    PARTITION BY warehouse
                    ORDER BY posting_date DESC, posting_time DESC, creation DESC
                ) as rn
            FROM `tabStock Ledger Entry`
            WHERE item_code = %s
              AND is_cancelled = 0
              AND warehouse IS NOT NULL
        ) ranked
        WHERE rn = 1
        """,
        (item_code,),
        as_dict=True,
    )

    return {r["warehouse"]: (r.get("valuation_rate") or 0) for r in rows}


def _get_price_history(item_code: str) -> list[dict]:
    """Get price history from Item Price doctype."""
    ip_doctype = "Item Price"

    if not _has_doctype(ip_doctype):
        return []

    ip_fields = ["name", "price_list", "price_list_rate", "currency", "modified", "creation"]

    if _has_field(ip_doctype, "valid_from"):
        ip_fields.append("valid_from")
    if _has_field(ip_doctype, "valid_upto"):
        ip_fields.append("valid_upto")

    return frappe.get_all(
        ip_doctype,
        filters={"item_code": item_code, "selling": 1},
        fields=ip_fields,
        order_by="COALESCE(valid_from, creation) asc",
        limit_page_length=1000,
    )


def _get_recent_sales(item_code: str, limit: int = 10) -> list[dict]:
    """Get recent sales invoice items for the item.

    Uses stock_qty for proper UoM conversion and base amounts
    for multi-currency support.
    """
    if not (_has_doctype("Sales Invoice Item") and _has_doctype("Sales Invoice")):
        return []

    return frappe.db.sql(
        """
        SELECT
            sii.parent as sales_invoice,
            si.posting_date,
            sii.stock_qty as qty,
            (sii.rate * si.conversion_rate) as rate,
            sii.base_net_amount as amount,
            si.customer,
            si.currency
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE sii.item_code = %s AND si.docstatus = 1
        ORDER BY si.posting_date DESC, si.modified DESC
        LIMIT %s
        """,
        (item_code, limit),
        as_dict=True,
    )


def _get_recent_purchases(item_code: str, limit: int = 10) -> list[dict]:
    """Get recent purchase invoice items for the item.

    Uses stock_uom_rate for proper UoM conversion and base amounts
    for multi-currency support.
    """
    if not (_has_doctype("Purchase Invoice Item") and _has_doctype("Purchase Invoice")):
        return []

    return frappe.db.sql(
        """
        SELECT
            pii.parent as purchase_invoice,
            pi.posting_date,
            pii.stock_qty as qty,
            (pii.stock_uom_rate * pi.conversion_rate) as rate,
            pii.base_net_amount as amount,
            pi.supplier,
            pi.currency
        FROM `tabPurchase Invoice Item` pii
        INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pii.item_code = %s AND pi.docstatus = 1
        ORDER BY pi.posting_date DESC, pi.modified DESC
        LIMIT %s
        """,
        (item_code, limit),
        as_dict=True,
    )


def _get_recent_pending_pos_sales(item_code: str, limit: int = 10) -> list[dict]:
    """Get recent POS Invoice rows that are still pending consolidation/closure."""
    if not (_has_doctype("POS Invoice Item") and _has_doctype("POS Invoice")):
        return []

    qty_field = _first_existing_field("POS Invoice Item", "stock_qty", "qty")
    rate_field = _first_existing_field("POS Invoice Item", "base_rate", "stock_uom_rate", "rate")
    amount_field = _first_existing_field("POS Invoice Item", "base_net_amount", "base_amount", "net_amount", "amount")

    qty_expr = f"pii.{qty_field}" if qty_field else "0"

    if rate_field == "base_rate":
        rate_expr = "pii.base_rate"
    elif rate_field and _has_field("POS Invoice", "conversion_rate"):
        rate_expr = f"(pii.{rate_field} * COALESCE(pi.conversion_rate, 1))"
    elif rate_field:
        rate_expr = f"pii.{rate_field}"
    else:
        rate_expr = "0"

    if amount_field in {"base_net_amount", "base_amount"}:
        amount_expr = f"pii.{amount_field}"
    elif amount_field and _has_field("POS Invoice", "conversion_rate"):
        amount_expr = f"(pii.{amount_field} * COALESCE(pi.conversion_rate, 1))"
    elif amount_field:
        amount_expr = f"pii.{amount_field}"
    else:
        amount_expr = "0"

    customer_expr = "pi.customer" if _has_field("POS Invoice", "customer") else "''"
    currency_expr = "pi.currency" if _has_field("POS Invoice", "currency") else "''"

    where_clauses = [
        "pii.item_code = %s",
        "pi.docstatus = 1",
    ]

    if _has_field("POS Invoice", "consolidated_invoice"):
        where_clauses.append("COALESCE(pi.consolidated_invoice, '') = ''")
    elif _has_field("POS Invoice", "pos_closing_entry"):
        where_clauses.append("COALESCE(pi.pos_closing_entry, '') = ''")
    else:
        child_doctype = _get_pos_closing_child_doctype()
        if child_doctype:
            child_table = child_doctype.replace("`", "")
            where_clauses.append(
                f"""
                NOT EXISTS (
                    SELECT 1
                    FROM `tab{child_table}` pct
                    INNER JOIN `tabPOS Closing Entry` pce ON pce.name = pct.parent
                    WHERE pct.parenttype = 'POS Closing Entry'
                      AND pct.pos_invoice = pi.name
                      AND pce.docstatus = 1
                )
                """
            )

    if _has_field("POS Invoice", "status"):
        where_clauses.append("COALESCE(pi.status, '') != 'Consolidated'")

    order_by = "pi.posting_date DESC"
    if _has_field("POS Invoice", "posting_time"):
        order_by += ", pi.posting_time DESC"
    if _has_field("POS Invoice", "modified"):
        order_by += ", pi.modified DESC"

    return frappe.db.sql(
        f"""
        SELECT
            pii.parent as pos_invoice,
            pi.posting_date,
            {customer_expr} as customer,
            {qty_expr} as qty,
            {rate_expr} as rate,
            {amount_expr} as amount,
            {currency_expr} as currency
        FROM `tabPOS Invoice Item` pii
        INNER JOIN `tabPOS Invoice` pi ON pi.name = pii.parent
        WHERE {' AND '.join(where_clauses)}
        ORDER BY {order_by}
        LIMIT %s
        """,
        (item_code, limit),
        as_dict=True,
    )


def _get_sales_last_30_days(item_code: str) -> dict:
    """
    Get total quantity sold in the last 30 days.

    Args:
        item_code: The item code to get sales data for

    Returns:
        dict with qty (total quantity sold), amount (total revenue), and count (number of transactions)
    """
    if not (_has_doctype("Sales Invoice Item") and _has_doctype("Sales Invoice")):
        return {"qty": 0, "amount": 0, "count": 0}

    from frappe.utils import add_days, nowdate

    thirty_days_ago = add_days(nowdate(), -30)

    result = frappe.db.sql(
        """
        SELECT
            COALESCE(SUM(sii.qty), 0) as qty,
            COALESCE(SUM(sii.amount), 0) as amount,
            COUNT(DISTINCT sii.parent) as count
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE sii.item_code = %s
          AND si.docstatus = 1
          AND si.posting_date >= %s
        """,
        (item_code, thirty_days_ago),
        as_dict=True,
    )

    if result:
        return {
            "qty": result[0].get("qty") or 0,
            "amount": result[0].get("amount") or 0,
            "count": result[0].get("count") or 0,
        }
    return {"qty": 0, "amount": 0, "count": 0}


def _get_default_selling_price(item_code: str) -> dict:
    """
    Get the default selling price for an item.

    Uses the selling_price_list from Stock Settings or the first selling price list found.

    Args:
        item_code: The item code to get selling price for

    Returns:
        dict with price, price_list, and currency
    """
    if not _has_doctype("Item Price"):
        return {"price": 0, "price_list": None, "currency": None}

    # Try to get default selling price list from Stock Settings
    default_pl = None
    if _has_doctype("Stock Settings") and _has_field("Stock Settings", "default_selling_price_list"):
        default_pl = frappe.db.get_single_value("Stock Settings", "default_selling_price_list")

    # If no default, try Selling Settings
    if not default_pl and _has_doctype("Selling Settings") and _has_field("Selling Settings", "selling_price_list"):
        default_pl = frappe.db.get_single_value("Selling Settings", "selling_price_list")

    filters = {"item_code": item_code, "selling": 1}
    if default_pl:
        filters["price_list"] = default_pl

    price_row = frappe.get_all(
        "Item Price",
        filters=filters,
        fields=["price_list_rate", "price_list", "currency"],
        order_by="modified desc",
        limit_page_length=1,
    )

    if price_row:
        return {
            "price": price_row[0].get("price_list_rate") or 0,
            "price_list": price_row[0].get("price_list"),
            "currency": price_row[0].get("currency"),
        }

    return {"price": 0, "price_list": None, "currency": None}


def _get_days_since_last_sale(item_code: str) -> int | None:
    """
    Get the number of days since the last sale of this item.

    Args:
        item_code: The item code to check

    Returns:
        Number of days since last sale, or None if never sold
    """
    if not (_has_doctype("Sales Invoice Item") and _has_doctype("Sales Invoice")):
        return None

    from frappe.utils import date_diff, nowdate

    result = frappe.db.sql(
        """
        SELECT MAX(si.posting_date) as last_sale_date
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE sii.item_code = %s
          AND si.docstatus = 1
        """,
        (item_code,),
        as_dict=True,
    )

    if result and result[0].get("last_sale_date"):
        return date_diff(nowdate(), result[0]["last_sale_date"])

    return None
