import frappe
from frappe import _


def _has_doctype(doctype: str) -> bool:
    return bool(frappe.db.exists("DocType", doctype))


def _has_field(doctype: str, fieldname: str) -> bool:
    try:
        return frappe.get_meta(doctype).has_field(fieldname)
    except Exception:
        return False


@frappe.whitelist()
def resolve_item_from_barcode(barcode: str):
    """Return {item_code} or {matches:[...]} for a barcode string."""
    barcode = (barcode or "").strip()
    if not barcode:
        return {"ok": False, "message": _("Empty barcode")}

    # 1) Item Barcode child table (v14/v15 usually)
    matches = []
    if _has_doctype("Item Barcode"):
        # Item Barcode is a child table; "parent" points to Item.name (item_code)
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

    # Normalize unique
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
def get_item_snapshot(item_code: str):
    """Return a dashboard-like snapshot for the item."""
    item_code = (item_code or "").strip()
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Item not found: {0}").format(item_code))

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
        item_fields.append("standard_rate")  # sometimes used as standard buying rate
    if _has_field("Item", "last_purchase_rate"):
        item_fields.append("last_purchase_rate")

    item = frappe.db.get_value("Item", item_code, item_fields, as_dict=True)

    # Barcodes
    barcodes = []
    if _has_doctype("Item Barcode"):
        barcodes = frappe.get_all(
            "Item Barcode",
            filters={"parent": item_code},
            fields=["barcode"],
            order_by="idx asc",
            limit_page_length=50,
        )
        barcodes = [b["barcode"] for b in barcodes if b.get("barcode")]

    # Stock by warehouse (Bin)
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

    # Latest valuation_rate by warehouse from Stock Ledger Entry
    valuation_by_wh = {}
    if _has_doctype("Stock Ledger Entry"):
        # pick last SLE per warehouse (safe + fast enough)
        rows = frappe.db.sql(
            """
            SELECT sle.warehouse, sle.valuation_rate
            FROM `tabStock Ledger Entry` sle
            INNER JOIN (
                SELECT warehouse,
                       MAX(CONCAT(posting_date, ' ', TIME_FORMAT(posting_time, '%%H:%%i:%%s'), ' ', creation)) AS max_key
                FROM `tabStock Ledger Entry`
                WHERE item_code=%s AND is_cancelled=0 AND warehouse IS NOT NULL
                GROUP BY warehouse
            ) latest
              ON latest.warehouse = sle.warehouse
             AND CONCAT(sle.posting_date, ' ', TIME_FORMAT(sle.posting_time, '%%H:%%i:%%s'), ' ', sle.creation) = latest.max_key
            WHERE sle.item_code=%s AND sle.is_cancelled=0
            """,
            (item_code, item_code),
            as_dict=True,
        )
        valuation_by_wh = {r["warehouse"]: (r.get("valuation_rate") or 0) for r in rows}

    # Price history (Item Price) - by price_list
    ip_doctype = "Item Price"
    price_rows = []
    if _has_doctype(ip_doctype):
        ip_fields = ["name", "price_list", "price_list_rate", "currency", "modified", "creation"]
        if _has_field(ip_doctype, "valid_from"):
            ip_fields.append("valid_from")
        if _has_field(ip_doctype, "valid_upto"):
            ip_fields.append("valid_upto")

        price_rows = frappe.get_all(
            ip_doctype,
            filters={"item_code": item_code},
            fields=ip_fields,
            order_by="COALESCE(valid_from, creation) asc",
            limit_page_length=1000,
        )

    # Recent sales (Sales Invoice Item)
    recent_sales = []
    if _has_doctype("Sales Invoice Item") and _has_doctype("Sales Invoice"):
        recent_sales = frappe.db.sql(
            """
            SELECT sii.parent as sales_invoice, si.posting_date, sii.qty, sii.rate, sii.amount, si.customer
            FROM `tabSales Invoice Item` sii
            INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE sii.item_code=%s AND si.docstatus=1
            ORDER BY si.posting_date DESC, si.modified DESC
            LIMIT 10
            """,
            (item_code,),
            as_dict=True,
        )

    # Recent purchases (Purchase Invoice Item)
    recent_purchases = []
    if _has_doctype("Purchase Invoice Item") and _has_doctype("Purchase Invoice"):
        recent_purchases = frappe.db.sql(
            """
            SELECT pii.parent as purchase_invoice, pi.posting_date, pii.qty, pii.rate, pii.amount, pi.supplier
            FROM `tabPurchase Invoice Item` pii
            INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            WHERE pii.item_code=%s AND pi.docstatus=1
            ORDER BY pi.posting_date DESC, pi.modified DESC
            LIMIT 10
            """,
            (item_code,),
            as_dict=True,
        )

    # Enrich bins with valuation + stock_value
    for b in bins:
        vr = valuation_by_wh.get(b["warehouse"], 0) or 0
        b["valuation_rate"] = vr
        b["stock_value_est"] = (b.get("actual_qty") or 0) * vr

    return {
        "ok": True,
        "item": item,
        "barcodes": barcodes,
        "bins": bins,
        "price_history": price_rows,
        "recent_sales": recent_sales,
        "recent_purchases": recent_purchases,
    }
