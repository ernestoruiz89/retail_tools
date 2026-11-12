"""
Label Generator - Backend API

Provides API endpoints for generating barcode labels with:
- Item lookup with barcode data
- Multiple label formats
- Quantity support
"""

import frappe
from frappe import _


# Label format configurations (width in mm, columns)
LABEL_FORMATS = {
    "2x1": {
        "key": "2x1",
        "name": "2x1 in (50.8x25.4mm)",
        "columns": 1,
        "width": 50.8,
        "height": 25.4,
    },
    "small": {
        "key": "small",
        "name": "Small (38x25mm)",
        "columns": 4,
        "width": 38,
        "height": 25,
    },
    "medium": {
        "key": "medium",
        "name": "Medium (50x30mm)",
        "columns": 3,
        "width": 50,
        "height": 30,
    },
    "large": {
        "key": "large",
        "name": "Large (70x40mm)",
        "columns": 2,
        "width": 70,
        "height": 40,
    },
}


@frappe.whitelist()
def get_label_formats() -> dict:
    """Get available label formats."""
    return {"ok": True, "formats": LABEL_FORMATS}


@frappe.whitelist()
def get_items_with_stock(warehouse: str = None) -> dict:
    """
    Get all items with stock for label generation.

    Args:
        warehouse: Optional warehouse filter

    Returns:
        dict with items array
    """
    # Get items with stock from Bin
    filters = {}
    if warehouse:
        filters["warehouse"] = warehouse

    bins = frappe.get_all(
        "Bin",
        filters=filters,
        fields=["item_code", "actual_qty", "warehouse"],
        order_by="item_code",
    )

    # Filter to positive stock and aggregate by item
    from collections import defaultdict
    stock_by_item = defaultdict(float)
    for b in bins:
        if b.actual_qty > 0:
            stock_by_item[b.item_code] += b.actual_qty

    if not stock_by_item:
        return {"ok": False, "message": _("No items with stock found")}

    # Get item details
    items = []
    for item_code, qty in stock_by_item.items():
        result = get_item_for_label(item_code)
        if result.get("ok"):
            item = result["item"]
            item["qty"] = int(qty)
            items.append(item)

    return {"ok": True, "items": items, "count": len(items)}


@frappe.whitelist()
def get_items_from_receipt_document(doctype: str, docname: str) -> dict:
    """
    Get items from a Purchase Invoice or Purchase Receipt for label generation.

    Args:
        doctype: Document type (Purchase Invoice or Purchase Receipt)
        docname: Document name

    Returns:
        dict with items array (item_code, item_name, barcode, price, qty)
    """
    # Validate doctype
    allowed_doctypes = ["Purchase Invoice", "Purchase Receipt"]
    if doctype not in allowed_doctypes:
        return {"ok": False, "message": _("Invalid document type")}

    # Validate document exists
    if not frappe.db.exists(doctype, docname):
        return {"ok": False, "message": _("Document not found")}

    # Get child table name
    child_doctype = f"{doctype} Item"

    # Get items from child table
    items_data = frappe.get_all(
        child_doctype,
        filters={"parent": docname},
        fields=["item_code", "qty"],
        order_by="idx",
    )

    if not items_data:
        return {"ok": False, "message": _("No items found in document")}

    # Get item details for each item
    items = []
    for row in items_data:
        result = get_item_for_label(row.item_code)
        if result.get("ok"):
            item = result["item"]
            item["qty"] = int(row.qty)
            items.append(item)

    if not items:
        return {"ok": False, "message": _("No valid items found")}

    return {"ok": True, "items": items, "count": len(items)}


@frappe.whitelist()
def get_item_for_label(
    item_code: str, price_list: str = None, price_list_2: str = None
) -> dict:
    """
    Get item data for label generation.

    Args:
        item_code: Item code to look up
        price_list: Optional price list to use (defaults to selling settings)
        price_list_2: Optional second price list to use

    Returns:
        dict with item data including barcode
    """
    if not item_code:
        return {"ok": False, "message": _("Item code is required")}

    # Check if item exists
    if not frappe.db.exists("Item", item_code):
        return {"ok": False, "message": _("Item not found")}

    # Get item data
    item = frappe.get_doc("Item", item_code)

    # Get barcode
    barcode = None
    if item.barcodes:
        barcode = item.barcodes[0].barcode

    # Get price from specified or default price list
    price = 0
    currency = None
    target_price_list = price_list or frappe.db.get_single_value(
        "Selling Settings", "selling_price_list"
    )
    if target_price_list:
        price_doc = frappe.db.get_value(
            "Item Price",
            {"item_code": item_code, "price_list": target_price_list, "selling": 1},
            ["price_list_rate", "currency"],
            as_dict=True,
        )
        if price_doc:
            price = price_doc.price_list_rate or 0
            currency = price_doc.currency

    # Get optional second price
    price_2 = 0
    currency_2 = None
    if price_list_2:
        price_2_doc = frappe.db.get_value(
            "Item Price",
            {"item_code": item_code, "price_list": price_list_2, "selling": 1},
            ["price_list_rate", "currency"],
            as_dict=True,
        )
        if price_2_doc:
            price_2 = price_2_doc.price_list_rate or 0
            currency_2 = price_2_doc.currency

    return {
        "ok": True,
        "item": {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "barcode": barcode,
            "price": price,
            "currency": currency,
            "price_2": price_2,
            "currency_2": currency_2,
        },
    }


@frappe.whitelist()
def generate_labels_html(
    items: str | list,
    label_format: str = "medium",
    show_price: int = 1,
    price_list: str | None = None,
    price_list_2: str | None = None,
) -> dict:
    """
    Generate HTML for label printing.

    Args:
        items: JSON string of items with quantities [{item_code, qty}, ...]
        label_format: Label format key (2x1, small, medium, large)
        show_price: Whether to show price on labels
        price_list: Optional price list to use for prices
        price_list_2: Optional second price list to use for prices

    Returns:
        dict with HTML content
    """
    import json

    try:
        items_list = json.loads(items) if isinstance(items, str) else items
    except json.JSONDecodeError:
        return {"ok": False, "message": _("Invalid items data")}

    if not items_list:
        return {"ok": False, "message": _("No items provided")}

    # Get format config
    format_config = LABEL_FORMATS.get(label_format, LABEL_FORMATS["medium"])

    # Collect all labels
    labels = []
    for item_data in items_list:
        item_code = item_data.get("item_code")
        qty = int(item_data.get("qty", 1))

        # Get item details with specified price lists
        result = get_item_for_label(item_code, price_list, price_list_2)
        if not result.get("ok"):
            continue

        item = result["item"]

        # Add label for each quantity
        for _ in range(qty):
            labels.append(item)

    if not labels:
        return {"ok": False, "message": _("No valid items found")}

    # Build HTML
    html = _build_labels_html(labels, format_config, int(show_price))

    return {"ok": True, "html": html, "count": len(labels)}


def _format_label_price(price: float, currency: str = None, compact: bool = False) -> str:
    """Format price for labels, optionally stripping .00 decimals for compact 2x1 tags."""
    import re

    if not price:
        return ""

    options = {"fieldtype": "Currency"}
    if currency:
        options["currency"] = currency

    formatted = frappe.format_value(price, options)
    if not compact:
        return formatted

    if float(price).is_integer():
        formatted = re.sub(r"[.,]00$", "", formatted)

    # Ensure single space between currency symbol and amount (e.g. "C$ 150")
    formatted = re.sub(r"^([^\d\s-]+)\s*(\d)", r"\1 \2", formatted.strip())
    return formatted


def _build_labels_html(labels: list, format_config: dict, show_price: int = 1) -> str:
    """Build labels HTML grid."""
    columns = format_config["columns"]
    label_height = format_config["height"]
    is_2x1 = format_config.get("key") == "2x1"

    # Check if small format (horizontal layout)
    is_small = columns == 4

    # Adjust sizes based on format (fewer columns = larger labels)
    name_size = "11px"
    price_size = "12px"
    code_size = "9px"
    barcode_height = "35px"
    char_limit = 30

    if columns == 2:  # Large labels
        name_size = "14px"
        price_size = "14px"
        code_size = "11px"
        barcode_height = "65px"
        char_limit = 50
    elif columns == 3:  # Medium labels
        name_size = "12px"
        price_size = "12px"
        code_size = "10px"
        barcode_height = "50px"
        char_limit = 35
    elif is_small:  # Small labels
        name_size = "11px"
        price_size = "11px"
        code_size = "9px"
        barcode_height = "40px"
        char_limit = 25

    labels_html = ""
    for label in labels:
        formatted_price = ""
        formatted_price_2 = ""
        if show_price:
            if label.get("price"):
                formatted_price = _format_label_price(
                    label["price"], label.get("currency"), compact=is_2x1
                )
            if label.get("price_2"):
                formatted_price_2 = _format_label_price(
                    label["price_2"], label.get("currency_2"), compact=is_2x1
                )

        barcode_html = ""
        if label.get("barcode"):
            barcode_html = f'<svg class="barcode-svg" data-barcode="{label["barcode"]}"></svg>'
        else:
            barcode_html = f'<div class="label-no-barcode">{_("No barcode")}</div>'

        if is_2x1:
            prices_2x1_html = ""
            if formatted_price:
                prices_2x1_html += f'<div class="label-2x1-price">{formatted_price}</div>'
            if formatted_price_2:
                prices_2x1_html += f'<div class="label-2x1-price">{formatted_price_2}</div>'

            labels_html += f"""
            <div class="label-2x1">
                <div class="label-2x1-barcode">{barcode_html}</div>
                <div class="label-2x1-info">
                    <div class="label-2x1-name">{label["item_name"][:28]}</div>
                    {prices_2x1_html}
                </div>
            </div>
            """
        elif is_small:
            # Small labels: barcode on top, info row below (name/code left, price right)
            # If no price, center the info
            price_lines = [p for p in [formatted_price, formatted_price_2] if p]
            price_html = (
                f'<div class="label-price-side">{"<br>".join(price_lines)}</div>'
                if price_lines
                else ""
            )
            centered_class = "" if price_lines else " label-centered"
            labels_html += f"""
            <div class="label-item label-small{centered_class}">
                <div class="label-barcode">{barcode_html}</div>
                <div class="label-info-row">
                    <div class="label-left">
                        <div class="label-name">{label["item_name"][:char_limit]}</div>
                        <div class="label-code">{label["item_code"]}</div>
                    </div>
                    {price_html}
                </div>
            </div>
            """
        else:
            # Medium/Large labels: same layout, larger sizes
            price_lines = [p for p in [formatted_price, formatted_price_2] if p]
            price_html = (
                f'<div class="label-price-side">{"<br>".join(price_lines)}</div>'
                if price_lines
                else ""
            )
            centered_class = "" if price_lines else " label-centered"
            labels_html += f"""
            <div class="label-item{centered_class}">
                <div class="label-barcode">{barcode_html}</div>
                <div class="label-info-row">
                    <div class="label-left">
                        <div class="label-name">{label["item_name"][:char_limit]}</div>
                        <div class="label-code">{label["item_code"]}</div>
                    </div>
                    {price_html}
                </div>
            </div>
            """

    page_rule = "@page { size: 2in 1in; margin: 0; }" if is_2x1 else ""
    grid_class = "labels-grid-2x1" if is_2x1 else "labels-grid"

    return f"""
    <style>
        {page_rule}
        .labels-container {{
            font-family: Arial, sans-serif;
        }}
        .labels-grid {{
            display: grid;
            grid-template-columns: repeat({columns}, 1fr);
            gap: 5px;
        }}
        .labels-grid-2x1 {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .label-2x1 {{
            width: 50.8mm;
            height: 25.4mm;
            border: 1px dashed #ccc;
            border-radius: 2mm;
            padding: 1.5mm 2mm;
            box-sizing: border-box;
            background: #fff;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: space-between;
            page-break-inside: avoid;
            break-inside: avoid;
            overflow: hidden;
        }}
        .label-2x1-barcode {{
            width: 56%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }}
        .label-2x1-barcode svg {{
            width: 100%;
            height: auto;
            max-height: 22mm;
            display: block;
        }}
        .label-2x1-info {{
            width: 44%;
            height: 100%;
            padding-left: 1.5mm;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            gap: 2px;
        }}
        .label-2x1-name {{
            font-weight: 700;
            font-size: 12px;
            line-height: 1.15;
            color: #000;
            width: 100%;
            overflow: hidden;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            word-break: break-word;
        }}
        .label-2x1-price {{
            font-weight: 700;
            font-size: 13px;
            line-height: 1.15;
            color: #000;
            white-space: nowrap;
        }}
        .label-item {{
            border: 1px dashed #ccc;
            padding: 8px;
            text-align: center;
            min-height: {label_height}mm;
            box-sizing: border-box;
            page-break-inside: avoid;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}
        /* Small label layout: barcode top, info row below */
        .label-small {{
            padding: 4px 8px;
        }}
        /* Common layout for all sizes */
        .label-barcode {{
            margin-bottom: 4px;
            text-align: center;
        }}
        .label-barcode svg {{
            height: {barcode_height};
            max-width: 100%;
        }}
        .label-info-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .label-left {{
            flex: 1;
            min-width: 0;
            text-align: left;
        }}
        .label-name {{
            font-weight: 600;
            font-size: {name_size};
            line-height: 1.2;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .label-code {{
            font-size: {code_size};
            color: #666;
        }}
        .label-price-side {{
            font-weight: 700;
            font-size: {price_size};
            color: #333;
            text-align: right;
            white-space: nowrap;
            padding-left: 8px;
        }}
        /* Centered layout when no price */
        .label-centered .label-info-row {{
            justify-content: center;
        }}
        .label-centered .label-left {{
            text-align: center;
        }}
        .label-no-barcode {{
            color: #999;
            font-size: 10px;
            padding: 10px 0;
        }}
        @media print {{
            .label-item {{
                border: 1px solid #ddd;
            }}
            .labels-grid-2x1 {{
                display: block;
                margin: 0;
                padding: 0;
            }}
            .label-2x1 {{
                width: 2in;
                height: 1in;
                border: none !important;
                border-radius: 0 !important;
                margin: 0 !important;
                page-break-after: always;
                break-after: page;
            }}
            .label-2x1:last-child {{
                page-break-after: auto;
                break-after: auto;
            }}
        }}
    </style>
    <div class="labels-container">
        <div class="{grid_class}">
            {labels_html}
        </div>
    </div>
    """

