# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

POS_INVOICE_PRINT_FORMAT_NAME = "Factura POS con QR"

POS_INVOICE_PRINT_FORMAT_CSS = """@page {
	size: 80mm auto;
	margin: 0;
}
.print-format-gutter {
	padding: 0 !important;
}
.print-format {
	width: 80mm !important;
	max-width: 80mm !important;
	min-height: 0 !important;
	padding: 3mm !important;
	margin: 0 auto !important;
}
.rt-pos-ticket {
	font-family: 'Courier New', Courier, monospace;
	font-size: 11px;
	width: 100%;
	margin: 0;
	padding: 0;
	color: #000;
	background: #fff;
}
.rt-pos-ticket * {
	box-sizing: border-box;
}
.rt-pos-header {
	text-align: center;
	border-bottom: 1px dashed #000;
	padding-bottom: 8px;
	margin-bottom: 8px;
}
.rt-pos-company {
	font-size: 14px;
	font-weight: bold;
	text-transform: uppercase;
	margin-bottom: 3px;
}
.rt-pos-company-info {
	font-size: 10px;
	line-height: 1.35;
}
.rt-pos-title {
	font-size: 13px;
	font-weight: bold;
	letter-spacing: 1px;
	margin: 6px 0 4px;
}
.rt-pos-meta {
	font-size: 10px;
	line-height: 1.4;
	text-align: left;
	margin-top: 6px;
}
.rt-pos-items {
	width: 100%;
	border-collapse: collapse;
	font-size: 10px;
	margin-bottom: 8px;
}
.rt-pos-items th {
	text-align: left;
	border-bottom: 1px solid #000;
	padding: 3px 2px;
	font-weight: bold;
}
.rt-pos-items td {
	padding: 3px 2px;
	vertical-align: top;
	border-bottom: 1px dotted #ccc;
}
.rt-pos-items .num {
	text-align: right;
	white-space: nowrap;
}
.rt-pos-item-sub {
	font-size: 9px;
	color: #333;
}
.rt-pos-totals {
	border-top: 1px dashed #000;
	padding-top: 6px;
	margin-top: 4px;
}
.rt-pos-row {
	display: flex;
	justify-content: space-between;
	margin: 2px 0;
	font-size: 11px;
}
.rt-pos-row.grand-total {
	font-size: 13px;
	font-weight: bold;
	border-top: 1px solid #000;
	margin-top: 5px;
	padding-top: 4px;
}
.rt-pos-payments {
	border-top: 1px dashed #000;
	margin-top: 8px;
	padding-top: 6px;
}
.rt-pos-loyalty {
	border-top: 1px dashed #000;
	margin-top: 8px;
	padding-top: 6px;
}
.rt-pos-section-title {
	font-size: 10px;
	font-weight: bold;
	text-transform: uppercase;
	text-align: center;
	margin-bottom: 4px;
}
.rt-pos-qr-block {
	border-top: 1px dashed #000;
	margin-top: 10px;
	padding-top: 8px;
	text-align: center;
}
.rt-pos-qr-img {
	width: 120px;
	height: 120px;
	display: block;
	margin: 4px auto;
	image-rendering: pixelated;
}
.rt-pos-qr-label {
	font-size: 11px;
	font-weight: bold;
	margin-top: 4px;
}
.rt-pos-qr-handle {
	font-size: 10px;
	margin-top: 2px;
}
.rt-pos-footer {
	text-align: center;
	margin-top: 10px;
	font-size: 10px;
	line-height: 1.4;
}
@media print {
	html, body {
		width: 80mm !important;
		margin: 0 !important;
		padding: 0 !important;
		background: #fff !important;
	}
	.print-format-gutter,
	.print-format {
		width: 80mm !important;
		max-width: 80mm !important;
		min-height: 0 !important;
		padding: 2mm 3mm !important;
		margin: 0 !important;
		box-shadow: none !important;
	}
	.rt-pos-ticket {
		max-width: none !important;
		width: 100% !important;
		margin: 0 !important;
		padding: 0 !important;
	}
}
"""

POS_INVOICE_PRINT_FORMAT_HTML = """{% set rt = get_pos_qr_context() %}
{% set company_tax_id = frappe.db.get_value("Company", doc.company, "tax_id") %}
<div class="rt-pos-ticket">
  <div class="rt-pos-header">
    <div class="rt-pos-company">{{ doc.company }}</div>
    {% if company_tax_id %}
    <div class="rt-pos-company-info">RUC: {{ company_tax_id }}</div>
    {% endif %}
    {% if doc.company_address_display %}
    <div class="rt-pos-company-info">{{ doc.company_address_display | striptags }}</div>
    {% endif %}
    <div class="rt-pos-title">
      {% if doc.is_return %}DEVOLUCIÓN POS{% else %}FACTURA POS{% endif %}
    </div>
    <div class="rt-pos-meta">
      <div><strong>No.:</strong> {{ doc.name }}</div>
      <div><strong>Fecha:</strong> {{ doc.get_formatted("posting_date") }} {{ doc.get_formatted("posting_time") or "" }}</div>
      <div><strong>Cliente:</strong> {{ doc.customer_name or doc.customer }}</div>
      {% if doc.pos_profile %}
      <div><strong>Caja:</strong> {{ doc.pos_profile }}</div>
      {% endif %}
      <div><strong>Cajero:</strong> {{ frappe.db.get_value("User", doc.owner, "full_name") or doc.owner }}</div>
    </div>
  </div>

  <table class="rt-pos-items">
    <thead>
      <tr>
        <th>Artículo</th>
        <th class="num">Cant.</th>
        <th class="num">Precio</th>
        <th class="num">Total</th>
      </tr>
    </thead>
    <tbody>
      {% for item in doc.items %}
      <tr>
        <td>
          {{ item.item_name }}
          {% set item_barcode = item.barcode or frappe.db.get_value("Item Barcode", {"parent": item.item_code}, "barcode") %}
          {% if item_barcode %}
          <div class="rt-pos-item-sub">{{ item_barcode }}</div>
          {% endif %}
          {% if item.discount_percentage %}
          <div class="rt-pos-item-sub">Desc: {{ "%.1f"|format(item.discount_percentage) }}%</div>
          {% endif %}
        </td>
        <td class="num">
          {% if item.qty == item.qty | int %}{{ item.qty | int }}{% else %}{{ item.qty }}{% endif %}
        </td>
        <td class="num">{{ item.get_formatted("rate") }}</td>
        <td class="num">{{ item.get_formatted("amount") }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <div class="rt-pos-totals">
    <div class="rt-pos-row">
      <span>Subtotal:</span>
      <span>{{ doc.get_formatted("total") }}</span>
    </div>
    {% if doc.discount_amount %}
    <div class="rt-pos-row">
      <span>Descuento:</span>
      <span>-{{ doc.get_formatted("discount_amount") }}</span>
    </div>
    {% endif %}
    {% for tax in doc.taxes %}
    {% if tax.tax_amount %}
    <div class="rt-pos-row">
      <span>{{ tax.description }}:</span>
      <span>{{ tax.get_formatted("tax_amount") }}</span>
    </div>
    {% endif %}
    {% endfor %}
    <div class="rt-pos-row grand-total">
      <span>TOTAL:</span>
      <span>{{ doc.get_formatted("rounded_total") if doc.rounded_total else doc.get_formatted("grand_total") }}</span>
    </div>
  </div>

  {% if doc.payments %}
  <div class="rt-pos-payments">
    <div class="rt-pos-section-title">Pagos</div>
    {% for pay in doc.payments %}
    {% if pay.amount %}
    <div class="rt-pos-row">
      <span>{{ pay.mode_of_payment }}:</span>
      <span>{{ pay.get_formatted("amount") }}</span>
    </div>
    {% endif %}
    {% endfor %}
    {% if doc.change_amount %}
    <div class="rt-pos-row">
      <span><strong>Cambio:</strong></span>
      <span><strong>{{ doc.get_formatted("change_amount") }}</strong></span>
    </div>
    {% endif %}
  </div>
  {% endif %}

  {% set lp_name = doc.loyalty_program or frappe.db.get_value("Customer", doc.customer, "loyalty_program") %}
  {% if lp_name %}
  {% set lp_entries = frappe.get_all(
    "Loyalty Point Entry",
    filters={"customer": doc.customer, "company": doc.company, "loyalty_program": lp_name},
    fields=["loyalty_points", "expiry_date"],
    limit_page_length=0
  ) %}
  {% set lp_ns = namespace(balance=0) %}
  {% for lp_e in lp_entries %}
    {% if not lp_e.expiry_date or (lp_e.expiry_date | string) >= (doc.posting_date | string) %}
      {% set lp_ns.balance = lp_ns.balance + (lp_e.loyalty_points or 0) %}
    {% endif %}
  {% endfor %}
  {% set lp_balance = (lp_ns.balance | int) if lp_ns.balance > 0 else 0 %}
  {% set lp_conversion = frappe.db.get_value("Loyalty Program", lp_name, "conversion_factor") or 0 %}
  <div class="rt-pos-loyalty">
    <div class="rt-pos-section-title">Puntos de Fidelidad</div>
    {% if doc.redeem_loyalty_points and doc.loyalty_points %}
    <div class="rt-pos-row">
      <span>Puntos canjeados:</span>
      <span>-{{ doc.loyalty_points | int }} pts</span>
    </div>
    {% endif %}
    <div class="rt-pos-row">
      <span><strong>Saldo disponible:</strong></span>
      <span><strong>{{ lp_balance }} pts{% if lp_conversion and lp_balance %} ({{ frappe.format(lp_balance * lp_conversion, {"fieldtype": "Currency", "currency": doc.currency}) }}){% endif %}</strong></span>
    </div>
  </div>
  {% endif %}

  {% if rt.qr_data_uri %}
  <div class="rt-pos-qr-block">
    {% if rt.qr_label %}
    <div class="rt-pos-qr-label">{{ rt.qr_label }}</div>
    {% endif %}
    <img src="{{ rt.qr_data_uri }}" alt="Código QR" class="rt-pos-qr-img" />
    {% if rt.qr_subtitle %}
    <div class="rt-pos-qr-handle">{{ rt.qr_subtitle }}</div>
    {% endif %}
  </div>
  {% endif %}

  <div class="rt-pos-footer">
    {% if rt.pos_footer_message %}
    <div>{{ rt.pos_footer_message }}</div>
    {% else %}
    <div>¡Gracias por su compra!</div>
    {% endif %}
  </div>
</div>
"""

POS_INVOICE_50MM_PRINT_FORMAT_NAME = "Factura POS con QR 50mm"

POS_INVOICE_50MM_PRINT_FORMAT_CSS = """@page {
	size: 50mm auto;
	margin: 0;
}
.print-format-gutter {
	padding: 0 !important;
}
.print-format {
	width: 50mm !important;
	max-width: 50mm !important;
	min-height: 0 !important;
	padding: 2mm !important;
	margin: 0 auto !important;
}
.rt-pos50-ticket {
	font-family: 'Courier New', Courier, monospace;
	font-size: 9.5px;
	width: 100%;
	margin: 0;
	padding: 0;
	color: #000;
	background: #fff;
}
.rt-pos50-ticket * {
	box-sizing: border-box;
}
.rt-pos50-header {
	text-align: center;
	border-bottom: 1px dashed #000;
	padding-bottom: 5px;
	margin-bottom: 5px;
}
.rt-pos50-company {
	font-size: 11.5px;
	font-weight: bold;
	text-transform: uppercase;
	margin-bottom: 2px;
	word-break: break-word;
}
.rt-pos50-company-info {
	font-size: 8.5px;
	line-height: 1.3;
	word-break: break-word;
}
.rt-pos50-title {
	font-size: 10.5px;
	font-weight: bold;
	letter-spacing: 0.5px;
	margin: 4px 0 3px;
}
.rt-pos50-meta {
	font-size: 8.5px;
	line-height: 1.35;
	text-align: left;
	margin-top: 4px;
	word-break: break-word;
}
.rt-pos50-items {
	margin-bottom: 5px;
}
.rt-pos50-item {
	padding: 3px 0;
	border-bottom: 1px dotted #aaa;
}
.rt-pos50-item:last-child {
	border-bottom: none;
}
.rt-pos50-item-name {
	font-size: 9.5px;
	font-weight: bold;
	line-height: 1.25;
	word-break: break-word;
}
.rt-pos50-item-sub {
	font-size: 8px;
	color: #333;
	line-height: 1.2;
}
.rt-pos50-item-calc {
	display: flex;
	justify-content: space-between;
	align-items: baseline;
	font-size: 9px;
	margin-top: 1px;
	gap: 4px;
}
.rt-pos50-totals {
	border-top: 1px dashed #000;
	padding-top: 4px;
	margin-top: 3px;
}
.rt-pos50-row {
	display: flex;
	justify-content: space-between;
	align-items: baseline;
	gap: 4px;
	margin: 2px 0;
	font-size: 9px;
}
.rt-pos50-row span:last-child {
	text-align: right;
	white-space: nowrap;
}
.rt-pos50-row.grand-total {
	font-size: 11px;
	font-weight: bold;
	border-top: 1px solid #000;
	margin-top: 4px;
	padding-top: 3px;
}
.rt-pos50-payments,
.rt-pos50-loyalty {
	border-top: 1px dashed #000;
	margin-top: 5px;
	padding-top: 4px;
}
.rt-pos50-section-title {
	font-size: 8.5px;
	font-weight: bold;
	text-transform: uppercase;
	text-align: center;
	margin-bottom: 3px;
}
.rt-pos50-qr-block {
	border-top: 1px dashed #000;
	margin-top: 6px;
	padding-top: 6px;
	text-align: center;
}
.rt-pos50-qr-img {
	width: 96px;
	height: 96px;
	display: block;
	margin: 3px auto;
	image-rendering: pixelated;
}
.rt-pos50-qr-label {
	font-size: 9.5px;
	font-weight: bold;
	margin-top: 2px;
}
.rt-pos50-qr-handle {
	font-size: 8.5px;
	margin-top: 2px;
	word-break: break-all;
}
.rt-pos50-footer {
	text-align: center;
	margin-top: 6px;
	font-size: 8.5px;
	line-height: 1.3;
}
@media print {
	html, body {
		width: 50mm !important;
		margin: 0 !important;
		padding: 0 !important;
		background: #fff !important;
	}
	.print-format-gutter,
	.print-format {
		width: 50mm !important;
		max-width: 50mm !important;
		min-height: 0 !important;
		padding: 1.5mm 2mm !important;
		margin: 0 !important;
		box-shadow: none !important;
	}
	.rt-pos50-ticket {
		max-width: none !important;
		width: 100% !important;
		margin: 0 !important;
		padding: 0 !important;
	}
}
"""

POS_INVOICE_50MM_PRINT_FORMAT_HTML = """{% set rt = get_pos_qr_context() %}
{% set company_tax_id = frappe.db.get_value("Company", doc.company, "tax_id") %}
<div class="rt-pos50-ticket">
  <div class="rt-pos50-header">
    <div class="rt-pos50-company">{{ doc.company }}</div>
    {% if company_tax_id %}
    <div class="rt-pos50-company-info">RUC: {{ company_tax_id }}</div>
    {% endif %}
    {% if doc.company_address_display %}
    <div class="rt-pos50-company-info">{{ doc.company_address_display | striptags }}</div>
    {% endif %}
    <div class="rt-pos50-title">
      {% if doc.is_return %}DEVOLUCIÓN POS{% else %}FACTURA POS{% endif %}
    </div>
    <div class="rt-pos50-meta">
      <div><strong>No.:</strong> {{ doc.name }}</div>
      <div><strong>Fecha:</strong> {{ doc.get_formatted("posting_date") }} {{ doc.get_formatted("posting_time") or "" }}</div>
      <div><strong>Cliente:</strong> {{ doc.customer_name or doc.customer }}</div>
      {% if doc.pos_profile %}
      <div><strong>Caja:</strong> {{ doc.pos_profile }}</div>
      {% endif %}
      <div><strong>Cajero:</strong> {{ frappe.db.get_value("User", doc.owner, "full_name") or doc.owner }}</div>
    </div>
  </div>

  <div class="rt-pos50-items">
    {% for item in doc.items %}
    {% set item_barcode = item.barcode or frappe.db.get_value("Item Barcode", {"parent": item.item_code}, "barcode") %}
    <div class="rt-pos50-item">
      <div class="rt-pos50-item-name">{{ item.item_name }}</div>
      {% if item_barcode %}
      <div class="rt-pos50-item-sub">{{ item_barcode }}</div>
      {% endif %}
      {% if item.discount_percentage %}
      <div class="rt-pos50-item-sub">Desc: {{ "%.1f"|format(item.discount_percentage) }}%</div>
      {% endif %}
      <div class="rt-pos50-item-calc">
        <span>{% if item.qty == item.qty | int %}{{ item.qty | int }}{% else %}{{ item.qty }}{% endif %} x {{ item.get_formatted("rate") }}</span>
        <strong>{{ item.get_formatted("amount") }}</strong>
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="rt-pos50-totals">
    <div class="rt-pos50-row">
      <span>Subtotal:</span>
      <span>{{ doc.get_formatted("total") }}</span>
    </div>
    {% if doc.discount_amount %}
    <div class="rt-pos50-row">
      <span>Descuento:</span>
      <span>-{{ doc.get_formatted("discount_amount") }}</span>
    </div>
    {% endif %}
    {% for tax in doc.taxes %}
    {% if tax.tax_amount %}
    <div class="rt-pos50-row">
      <span>{{ tax.description }}:</span>
      <span>{{ tax.get_formatted("tax_amount") }}</span>
    </div>
    {% endif %}
    {% endfor %}
    <div class="rt-pos50-row grand-total">
      <span>TOTAL:</span>
      <span>{{ doc.get_formatted("rounded_total") if doc.rounded_total else doc.get_formatted("grand_total") }}</span>
    </div>
  </div>

  {% if doc.payments %}
  <div class="rt-pos50-payments">
    <div class="rt-pos50-section-title">Pagos</div>
    {% for pay in doc.payments %}
    {% if pay.amount %}
    <div class="rt-pos50-row">
      <span>{{ pay.mode_of_payment }}:</span>
      <span>{{ pay.get_formatted("amount") }}</span>
    </div>
    {% endif %}
    {% endfor %}
    {% if doc.change_amount %}
    <div class="rt-pos50-row">
      <span><strong>Cambio:</strong></span>
      <span><strong>{{ doc.get_formatted("change_amount") }}</strong></span>
    </div>
    {% endif %}
  </div>
  {% endif %}

  {% set lp_name = doc.loyalty_program or frappe.db.get_value("Customer", doc.customer, "loyalty_program") %}
  {% if lp_name %}
  {% set lp_entries = frappe.get_all(
    "Loyalty Point Entry",
    filters={"customer": doc.customer, "company": doc.company, "loyalty_program": lp_name},
    fields=["loyalty_points", "expiry_date"],
    limit_page_length=0
  ) %}
  {% set lp_ns = namespace(balance=0) %}
  {% for lp_e in lp_entries %}
    {% if not lp_e.expiry_date or (lp_e.expiry_date | string) >= (doc.posting_date | string) %}
      {% set lp_ns.balance = lp_ns.balance + (lp_e.loyalty_points or 0) %}
    {% endif %}
  {% endfor %}
  {% set lp_balance = (lp_ns.balance | int) if lp_ns.balance > 0 else 0 %}
  {% set lp_conversion = frappe.db.get_value("Loyalty Program", lp_name, "conversion_factor") or 0 %}
  <div class="rt-pos50-loyalty">
    <div class="rt-pos50-section-title">Puntos de Fidelidad</div>
    {% if doc.redeem_loyalty_points and doc.loyalty_points %}
    <div class="rt-pos50-row">
      <span>Canjeados:</span>
      <span>-{{ doc.loyalty_points | int }} pts</span>
    </div>
    {% endif %}
    <div class="rt-pos50-row">
      <span><strong>Saldo:</strong></span>
      <span><strong>{{ lp_balance }} pts{% if lp_conversion and lp_balance %} ({{ frappe.format(lp_balance * lp_conversion, {"fieldtype": "Currency", "currency": doc.currency}) }}){% endif %}</strong></span>
    </div>
  </div>
  {% endif %}

  {% if rt.qr_data_uri %}
  <div class="rt-pos50-qr-block">
    {% if rt.qr_label %}
    <div class="rt-pos50-qr-label">{{ rt.qr_label }}</div>
    {% endif %}
    <img src="{{ rt.qr_data_uri }}" alt="Código QR" class="rt-pos50-qr-img" />
    {% if rt.qr_subtitle %}
    <div class="rt-pos50-qr-handle">{{ rt.qr_subtitle }}</div>
    {% endif %}
  </div>
  {% endif %}

  <div class="rt-pos50-footer">
    {% if rt.pos_footer_message %}
    <div>{{ rt.pos_footer_message }}</div>
    {% else %}
    <div>¡Gracias por su compra!</div>
    {% endif %}
  </div>
</div>
"""

POS_INVOICE_PRINT_FORMATS = (
	(POS_INVOICE_PRINT_FORMAT_NAME, POS_INVOICE_PRINT_FORMAT_HTML, POS_INVOICE_PRINT_FORMAT_CSS, 11),
	(POS_INVOICE_50MM_PRINT_FORMAT_NAME, POS_INVOICE_50MM_PRINT_FORMAT_HTML, POS_INVOICE_50MM_PRINT_FORMAT_CSS, 9),
)

