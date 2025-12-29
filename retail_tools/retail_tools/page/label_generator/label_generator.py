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
    "small": {"name": "Small (38x25mm)", "columns": 4, "width": 38, "height": 25},
    "medium": {"name": "Medium (50x30mm)", "columns": 3, "width": 50, "height": 30},
    "large": {"name": "Large (70x40mm)", "columns": 2, "width": 70, "height": 40},
}


@frappe.whitelist()
def get_label_formats() -> dict:
    """Get available label formats."""
    return {"ok": True, "formats": LABEL_FORMATS}


@frappe.whitelist()
def get_item_for_label(item_code: str) -> dict:
    """
    Get item data for label generation.

    Args:
        item_code: Item code to look up

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

    # Get price from default selling price list
    price = 0
    default_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
    if default_price_list:
        price_doc = frappe.db.get_value(
            "Item Price",
            {"item_code": item_code, "price_list": default_price_list, "selling": 1},
            "price_list_rate",
        )
        if price_doc:
            price = price_doc

    return {
        "ok": True,
        "item": {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "barcode": barcode,
            "price": price,
        },
    }


@frappe.whitelist()
def generate_labels_html(items: str, label_format: str = "medium") -> dict:
    """
    Generate HTML for label printing.

    Args:
        items: JSON string of items with quantities [{item_code, qty}, ...]
        label_format: Label format key (small, medium, large)

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
    columns = format_config["columns"]

    # Collect all labels
    labels = []
    for item_data in items_list:
        item_code = item_data.get("item_code")
        qty = int(item_data.get("qty", 1))

        # Get item details
        result = get_item_for_label(item_code)
        if not result.get("ok"):
            continue

        item = result["item"]

        # Add label for each quantity
        for _ in range(qty):
            labels.append(item)

    if not labels:
        return {"ok": False, "message": _("No valid items found")}

    # Build HTML
    html = _build_labels_html(labels, format_config)

    return {"ok": True, "html": html, "count": len(labels)}


def _build_labels_html(labels: list, format_config: dict) -> str:
    """Build labels HTML grid."""
    columns = format_config["columns"]
    label_width = format_config["width"]
    label_height = format_config["height"]

    labels_html = ""
    for label in labels:
        price_html = ""
        if label.get("price"):
            formatted_price = frappe.format_value(
                label["price"], {"fieldtype": "Currency"}
            )
            price_html = f'<div class="label-price">{formatted_price}</div>'

        barcode_html = ""
        if label.get("barcode"):
            barcode_html = f'<svg class="barcode-svg" data-barcode="{label["barcode"]}"></svg>'
        else:
            barcode_html = f'<div class="label-no-barcode">{_("No barcode")}</div>'

        labels_html += f"""
        <div class="label-item">
            <div class="label-barcode">{barcode_html}</div>
            <div class="label-name">{label["item_name"][:30]}</div>
            <div class="label-code">{label["item_code"]}</div>
            {price_html}
        </div>
        """

    return f"""
    <style>
        .labels-container {{
            font-family: Arial, sans-serif;
        }}
        .labels-grid {{
            display: grid;
            grid-template-columns: repeat({columns}, 1fr);
            gap: 5px;
        }}
        .label-item {{
            border: 1px dashed #ccc;
            padding: 8px;
            text-align: center;
            min-height: {label_height}mm;
            box-sizing: border-box;
            page-break-inside: avoid;
        }}
        .label-barcode {{
            margin-bottom: 4px;
        }}
        .label-barcode svg {{
            max-width: 100%;
            height: 35px;
        }}
        .label-no-barcode {{
            color: #999;
            font-size: 10px;
            padding: 10px 0;
        }}
        .label-name {{
            font-weight: 600;
            font-size: 11px;
            line-height: 1.2;
            margin-bottom: 2px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .label-code {{
            font-size: 9px;
            color: #666;
            margin-bottom: 2px;
        }}
        .label-price {{
            font-weight: 700;
            font-size: 12px;
            color: #333;
        }}
        @media print {{
            .label-item {{
                border: 1px solid #ddd;
            }}
        }}
    </style>
    <div class="labels-container">
        <div class="labels-grid">
            {labels_html}
        </div>
    </div>
    """
