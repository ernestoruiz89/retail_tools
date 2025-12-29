"""
Catalog Generator - Backend API

Provides API endpoints for generating product catalogs with:
- Item filtering by group, brand, warehouse
- Price list integration
- Barcode generation
- PDF export
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_items_for_catalog(
    item_group: str = None,
    brand: str = None,
    warehouse: str = None,
    price_list: str = None,
    include_disabled: int = 0,
) -> dict:
    """
    Get items for catalog generation.

    Args:
        item_group: Filter by item group (includes children)
        brand: Filter by brand
        warehouse: Filter by items with stock in this warehouse
        price_list: Get prices from this price list
        include_disabled: Include disabled items (0 or 1)

    Returns:
        dict with items array
    """
    filters = {"is_stock_item": 1}

    if not include_disabled:
        filters["disabled"] = 0

    if item_group:
        # Get item group and its descendants
        item_groups = get_item_group_descendants(item_group)
        filters["item_group"] = ["in", item_groups]

    if brand:
        filters["brand"] = brand

    # Get base item data
    items = frappe.get_all(
        "Item",
        filters=filters,
        fields=[
            "name",
            "item_code",
            "item_name",
            "item_group",
            "brand",
            "description",
            "image",
            "stock_uom",
        ],
        order_by="item_name asc",
        limit=500,
    )

    if not items:
        return {"ok": True, "items": []}

    item_codes = [i.name for i in items]

    # Get barcodes
    barcodes = get_item_barcodes(item_codes)

    # Get prices if price list specified
    prices = {}
    if price_list:
        prices = get_item_prices(item_codes, price_list)

    # Get stock if warehouse specified
    stock = {}
    if warehouse:
        stock = get_item_stock(item_codes, warehouse)

    # Filter items by stock if warehouse is specified
    if warehouse:
        items = [i for i in items if stock.get(i.name, 0) > 0]

    # Enrich items with additional data
    for item in items:
        item["barcode"] = barcodes.get(item.name)
        item["price"] = prices.get(item.name, {}).get("price", 0)
        item["currency"] = prices.get(item.name, {}).get("currency", "")
        item["qty"] = stock.get(item.name, 0)

    return {"ok": True, "items": items, "count": len(items)}


def get_item_group_descendants(item_group: str) -> list:
    """Get item group and all its descendants."""
    groups = [item_group]

    children = frappe.get_all(
        "Item Group",
        filters={"parent_item_group": item_group},
        fields=["name"],
    )

    for child in children:
        groups.extend(get_item_group_descendants(child.name))

    return groups


def get_item_barcodes(item_codes: list) -> dict:
    """Get primary barcode for each item."""
    if not item_codes:
        return {}

    barcodes = frappe.get_all(
        "Item Barcode",
        filters={"parent": ["in", item_codes]},
        fields=["parent", "barcode"],
        order_by="idx asc",
    )

    # Return first barcode per item
    result = {}
    for b in barcodes:
        if b.parent not in result:
            result[b.parent] = b.barcode

    return result


def get_item_prices(item_codes: list, price_list: str) -> dict:
    """Get prices from specified price list."""
    if not item_codes or not price_list:
        return {}

    prices = frappe.get_all(
        "Item Price",
        filters={
            "item_code": ["in", item_codes],
            "price_list": price_list,
            "selling": 1,
        },
        fields=["item_code", "price_list_rate", "currency"],
        order_by="valid_from desc",
    )

    # Return latest price per item
    result = {}
    for p in prices:
        if p.item_code not in result:
            result[p.item_code] = {
                "price": p.price_list_rate,
                "currency": p.currency,
            }

    return result


def get_item_stock(item_codes: list, warehouse: str) -> dict:
    """Get stock quantity per item in warehouse."""
    if not item_codes or not warehouse:
        return {}

    bins = frappe.get_all(
        "Bin",
        filters={
            "item_code": ["in", item_codes],
            "warehouse": warehouse,
        },
        fields=["item_code", "actual_qty"],
    )

    return {b.item_code: b.actual_qty for b in bins}


@frappe.whitelist()
def generate_catalog_html(
    item_group: str = None,
    brand: str = None,
    warehouse: str = None,
    price_list: str = None,
    columns: int = 3,
    show_barcode: int = 1,
    show_barcode_image: int = 0,
    show_price: int = 1,
    show_description: int = 0,
    group_by_item_group: int = 1,
) -> dict:
    """
    Generate HTML for catalog preview/print.

    Args:
        item_group: Filter by item group
        brand: Filter by brand
        warehouse: Filter by warehouse
        price_list: Price list for prices
        columns: Number of columns (2, 3, or 4)
        show_barcode: Show barcode text (0 or 1)
        show_barcode_image: Show scannable barcode image (0 or 1)
        show_price: Show price (0 or 1)
        show_description: Show description (0 or 1)
        group_by_item_group: Group items by item group (0 or 1)

    Returns:
        dict with HTML content
    """
    # Get items
    result = get_items_for_catalog(
        item_group=item_group,
        brand=brand,
        warehouse=warehouse,
        price_list=price_list,
    )

    if not result.get("ok"):
        return result

    items = result.get("items", [])

    if not items:
        return {"ok": False, "message": _("No items found with the selected filters")}

    # Build HTML
    columns = int(columns) if columns else 3
    columns = max(2, min(4, columns))  # Clamp between 2 and 4

    html = _build_catalog_html(
        items,
        columns=columns,
        show_barcode=int(show_barcode),
        show_barcode_image=int(show_barcode_image),
        show_price=int(show_price),
        show_description=int(show_description),
        group_by_item_group=int(group_by_item_group),
        price_list=price_list,
    )

    return {"ok": True, "html": html, "count": len(items)}


def _build_catalog_html(
    items: list,
    columns: int,
    show_barcode: int,
    show_barcode_image: int,
    show_price: int,
    show_description: int,
    group_by_item_group: int,
    price_list: str = None,
) -> str:
    """Build catalog HTML grid with optional grouping."""
    width_percent = 100 // columns

    header = f"""
    <div class="catalog-header">
        <h2>{_("Product Catalog")}</h2>
        <p class="catalog-meta">
            {len(items)} {_("products")}
            {f' • {price_list}' if price_list else ''}
        </p>
    </div>
    """

    # Group items if requested
    if group_by_item_group:
        from collections import defaultdict
        grouped = defaultdict(list)
        for item in items:
            grouped[item.get("item_group", _("Other"))].append(item)
        
        content_html = ""
        for group_name in sorted(grouped.keys()):
            group_items = grouped[group_name]
            content_html += f'<div class="catalog-group"><h3 class="catalog-group-title">{group_name}</h3>'
            content_html += '<div class="catalog-grid">'
            content_html += _build_items_html(group_items, width_percent, show_barcode, show_barcode_image, show_price, show_description)
            content_html += '</div></div>'
    else:
        content_html = '<div class="catalog-grid">'
        content_html += _build_items_html(items, width_percent, show_barcode, show_barcode_image, show_price, show_description)
        content_html += '</div>'

    # JsBarcode is now loaded and executed from the frontend JS

    return f"""
    <style>
        .catalog-container {{ font-family: sans-serif; }}
        .catalog-header {{ text-align: center; margin-bottom: 20px; }}
        .catalog-header h2 {{ margin: 0; }}
        .catalog-meta {{ color: #666; margin-top: 5px; }}
        .catalog-group {{ margin-bottom: 30px; page-break-inside: avoid; }}
        .catalog-group-title {{
            font-size: 18px;
            font-weight: 600;
            color: #333;
            border-bottom: 2px solid #333;
            padding-bottom: 8px;
            margin-bottom: 15px;
        }}
        .catalog-grid {{ 
            display: grid; 
            grid-template-columns: repeat({columns}, 1fr);
            gap: 15px;
            align-items: start;
        }}
        .catalog-item {{ 
            box-sizing: border-box;
            background: white;
        }}
        .catalog-item-inner {{
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
            page-break-inside: avoid;
            background: white;
        }}
        .catalog-item-image-container {{
            height: 100px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 10px;
        }}
        .catalog-item-image {{
            max-width: 100%;
            max-height: 100px;
            object-fit: contain;
        }}
        .catalog-item-placeholder {{
            width: 100%;
            height: 80px;
            background: #f0f0f0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
            color: #999;
            margin-bottom: 10px;
            border-radius: 4px;
        }}
        .catalog-item-name {{
            font-weight: 600;
            font-size: 13px;
            margin-bottom: 4px;
            line-height: 1.2;
            min-height: 32px;
        }}
        .catalog-item-code {{
            color: #666;
            font-size: 11px;
            margin-bottom: 6px;
        }}
        .catalog-item-barcode {{
            font-family: monospace;
            font-size: 10px;
            background: #f5f5f5;
            padding: 3px;
            border-radius: 4px;
            margin-bottom: 6px;
        }}
        .catalog-item-barcode-image {{
            margin: 8px 0;
        }}
        .catalog-item-barcode-image svg {{
            max-width: 100%;
            height: auto;
        }}
        .catalog-item-price {{
            font-size: 16px;
            font-weight: 700;
            color: #2e7d32;
            margin-top: auto;
        }}
        .catalog-item-desc {{
            font-size: 10px;
            color: #666;
            margin-top: 6px;
        }}
        @media print {{
            .catalog-item-inner {{ break-inside: avoid; }}
            .catalog-group {{ break-inside: avoid; }}
        }}
    </style>
    <div class="catalog-container">
        {header}
        {content_html}
    </div>
    """


def _build_items_html(
    items: list,
    width_percent: int,
    show_barcode: int,
    show_barcode_image: int,
    show_price: int,
    show_description: int,
) -> str:
    """Build HTML for a list of items."""
    items_html = ""
    for item in items:
        image_html = ""
        if item.get("image"):
            image_html = f'<div class="catalog-item-image-container"><img src="{item.image}" alt="{item.item_name}" class="catalog-item-image"></div>'
        else:
            image_html = f'<div class="catalog-item-image-container"><div class="catalog-item-placeholder">{item.item_name[:1]}</div></div>'

        barcode_html = ""
        if show_barcode and item.get("barcode") and not show_barcode_image:
            barcode_html = f'<div class="catalog-item-barcode">{item.barcode}</div>'

        barcode_image_html = ""
        if show_barcode_image and item.get("barcode"):
            barcode_image_html = f'<div class="catalog-item-barcode-image"><svg class="barcode-svg" data-barcode="{item.barcode}"></svg></div>'

        price_html = ""
        if show_price and item.get("price"):
            formatted_price = frappe.format_value(
                item.price, {"fieldtype": "Currency", "currency": item.get("currency")}
            )
            price_html = f'<div class="catalog-item-price">{formatted_price}</div>'

        desc_html = ""
        if show_description and item.get("description"):
            desc_text = frappe.utils.strip_html_tags(item.description or "")[:80]
            desc_html = f'<div class="catalog-item-desc">{desc_text}</div>'

        items_html += f"""
        <div class="catalog-item">
            <div class="catalog-item-inner">
                {image_html}
                <div class="catalog-item-name">{item.item_name}</div>
                <div class="catalog-item-code">{item.item_code}</div>
                {barcode_html}
                {barcode_image_html}
                {price_html}
                {desc_html}
            </div>
        </div>
        """

    return items_html

