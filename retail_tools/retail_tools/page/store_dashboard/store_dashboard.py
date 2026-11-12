from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

DASHBOARD_ROLES = {
	"System Manager",
	"Administrator",
	"Sales Manager",
	"Stock Manager",
	"Accounts Manager",
	"Purchase Manager",
	"RT Administrador de Sistema",
	"RT Socio",
	"RT Responsable de Tienda",
	"RT Contador",
}

WEEKDAY_LABELS_ES = [
	"Lunes",
	"Martes",
	"Miércoles",
	"Jueves",
	"Viernes",
	"Sábado",
	"Domingo",
]


def _ensure_dashboard_access() -> None:
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		frappe.throw(_("Debe iniciar sesión para acceder al Panel de Tienda."), frappe.PermissionError)

	if user == "Administrator":
		return

	user_roles = set(frappe.get_roles(user))
	if not (user_roles & DASHBOARD_ROLES):
		frappe.throw(
			_("No tiene permisos para visualizar el Panel de Control de Tienda."),
			frappe.PermissionError,
		)


def _resolve_company(company: str | None = None) -> str:
	if company and frappe.db.exists("Company", company):
		return company

	default_company = (
		frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)
	if default_company and frappe.db.exists("Company", default_company):
		return default_company

	first_company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	if not first_company:
		frappe.throw(_("No se encontró ninguna Empresa configurada en el sistema."))
	return str(first_company)


def _pct_change(current: float, previous: float) -> float:
	current_val = flt(current)
	prev_val = flt(previous)
	if abs(prev_val) < 1e-9:
		return 100.0 if current_val > 0 else (-100.0 if current_val < 0 else 0.0)
	return round(((current_val - prev_val) / abs(prev_val)) * 100.0, 2)


def _format_currency_compact(value: float, currency: str = "USD") -> str:
	symbol = frappe.db.get_value("Currency", currency, "symbol") or "$"
	val = flt(value, 2)
	sign = "-" if val < 0 else ""
	return f"{sign}{symbol} {abs(val):,.2f}"


@frappe.whitelist()
def get_dashboard_defaults(company: str | None = None) -> dict:
	"""Return initial filter options (companies, warehouses, currency, default date range)."""
	_ensure_dashboard_access()

	resolved_company = _resolve_company(company)
	currency = (
		frappe.db.get_value("Company", resolved_company, "default_currency")
		or frappe.db.get_single_value("Global Defaults", "default_currency")
		or "USD"
	)
	symbol = frappe.db.get_value("Currency", currency, "symbol") or "$"

	companies = frappe.get_all(
		"Company",
		fields=["name", "company_name", "default_currency"],
		order_by="name asc",
	)

	warehouses = frappe.get_all(
		"Warehouse",
		filters={"company": resolved_company, "is_group": 0, "disabled": 0},
		fields=["name", "warehouse_name"],
		order_by="name asc",
	)

	today = nowdate()
	from_date = str(add_days(today, -29))

	return {
		"company": resolved_company,
		"currency": currency,
		"currency_symbol": symbol,
		"companies": companies,
		"warehouses": warehouses,
		"default_from_date": from_date,
		"default_to_date": str(today),
	}


def _get_item_cost_map(company: str, warehouse: str | None = None) -> dict[str, float]:
	"""Return fallback unit valuation rate per item_code from Bin and Item."""
	wh_clause = "AND b.warehouse = %(warehouse)s" if warehouse else ""
	params = {"company": company}
	if warehouse:
		params["warehouse"] = warehouse

	bin_rows = frappe.db.sql(
		f"""
		SELECT
			b.item_code,
			CASE
				WHEN SUM(CASE WHEN b.actual_qty > 0 THEN b.actual_qty ELSE 0 END) > 0
				THEN SUM(CASE WHEN b.actual_qty > 0 THEN b.actual_qty * b.valuation_rate ELSE 0 END)
				     / SUM(CASE WHEN b.actual_qty > 0 THEN b.actual_qty ELSE 0 END)
				ELSE MAX(b.valuation_rate)
			END AS unit_cost
		FROM `tabBin` b
		INNER JOIN `tabWarehouse` w ON w.name = b.warehouse
		WHERE w.company = %(company)s
		  AND b.valuation_rate > 0
		  {wh_clause}
		GROUP BY b.item_code
		""",
		params,
		as_dict=True,
	)

	cost_map: dict[str, float] = {}
	for row in bin_rows:
		if row.item_code and flt(row.unit_cost) > 0:
			cost_map[row.item_code] = flt(row.unit_cost)

	item_rows = frappe.db.sql(
		"""
		SELECT
			name AS item_code,
			COALESCE(NULLIF(valuation_rate, 0), NULLIF(last_purchase_rate, 0), 0) AS fallback_cost
		FROM `tabItem`
		WHERE COALESCE(NULLIF(valuation_rate, 0), NULLIF(last_purchase_rate, 0), 0) > 0
		""",
		as_dict=True,
	)
	for row in item_rows:
		if row.item_code not in cost_map and flt(row.fallback_cost) > 0:
			cost_map[row.item_code] = flt(row.fallback_cost)

	return cost_map


def _fetch_sales_line_rows(
	company: str,
	from_date: str,
	to_date: str,
	warehouse: str | None = None,
	include_pending_pos: bool = True,
) -> list[dict]:
	"""Fetch non-consolidated Sales Invoice items + individual POS Invoice items (without duplication)."""
	wh_filter_si = "AND sii.warehouse = %(warehouse)s" if warehouse else ""
	params = {
		"company": company,
		"from_date": from_date,
		"to_date": to_date,
	}
	if warehouse:
		params["warehouse"] = warehouse

	has_pos_table = frappe.db.table_exists("POS Invoice") and frappe.db.table_exists("POS Invoice Item")
	exclude_consolidated_clause = ""
	if has_pos_table:
		exclude_consolidated_clause = """
		  AND IFNULL(si.is_consolidated, 0) = 0
		  AND NOT EXISTS (
		      SELECT 1 FROM `tabPOS Invoice` pi_c
		      WHERE pi_c.consolidated_invoice = si.name
		        AND pi_c.docstatus = 1
		  )
		"""

	si_rows = frappe.db.sql(
		f"""
		SELECT
			'Sales Invoice' AS doctype,
			CASE WHEN IFNULL(si.is_pos, 0) = 1 THEN 'POS' ELSE 'Direct' END AS sale_channel,
			si.name AS invoice_name,
			si.posting_date,
			COALESCE(CAST(si.posting_time AS CHAR), '12:00:00') AS posting_time,
			si.customer,
			si.is_return,
			sii.item_code,
			COALESCE(NULLIF(sii.item_name, ''), sii.item_code) AS item_name,
			COALESCE(NULLIF(sii.item_group, ''), i.item_group, 'Sin Categoría') AS item_group,
			sii.warehouse,
			IFNULL(sii.qty, 0) AS qty,
			IFNULL(NULLIF(sii.stock_qty, 0), IFNULL(sii.qty, 0)) AS stock_qty,
			IFNULL(sii.base_net_amount, 0) AS net_amount,
			IFNULL(sii.incoming_rate, 0) AS incoming_rate
		FROM `tabSales Invoice` si
		INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		LEFT JOIN `tabItem` i ON i.name = sii.item_code
		WHERE si.docstatus = 1
		  AND si.company = %(company)s
		  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  {exclude_consolidated_clause}
		  {wh_filter_si}
		""",
		params,
		as_dict=True,
	)

	rows = list(si_rows)

	if has_pos_table:
		wh_filter_pos = "AND pii.warehouse = %(warehouse)s" if warehouse else ""
		pos_status_clause = (
			""
			if include_pending_pos
			else "AND IFNULL(pi.consolidated_invoice, '') != ''"
		)
		pos_rows = frappe.db.sql(
			f"""
			SELECT
				'POS Invoice' AS doctype,
				'POS' AS sale_channel,
				pi.name AS invoice_name,
				pi.posting_date,
				COALESCE(CAST(pi.posting_time AS CHAR), '12:00:00') AS posting_time,
				pi.customer,
				pi.is_return,
				pii.item_code,
				COALESCE(NULLIF(pii.item_name, ''), pii.item_code) AS item_name,
				COALESCE(NULLIF(pii.item_group, ''), i.item_group, 'Sin Categoría') AS item_group,
				pii.warehouse,
				IFNULL(pii.qty, 0) AS qty,
				IFNULL(NULLIF(pii.stock_qty, 0), IFNULL(pii.qty, 0)) AS stock_qty,
				IFNULL(pii.base_net_amount, 0) AS net_amount,
				0 AS incoming_rate
			FROM `tabPOS Invoice` pi
			INNER JOIN `tabPOS Invoice Item` pii ON pii.parent = pi.name
			LEFT JOIN `tabItem` i ON i.name = pii.item_code
			WHERE pi.docstatus = 1
			  AND pi.company = %(company)s
			  AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s
			  {pos_status_clause}
			  {wh_filter_pos}
			""",
			params,
			as_dict=True,
		)
		rows.extend(pos_rows)

	return rows


def _compute_commercial_metrics(
	rows: list[dict],
	cost_map: dict[str, float],
	from_date: str,
	to_date: str,
) -> dict:
	"""Aggregate sales, cost, profit, daily series, category breakdown, top items, and hourly heatmap."""
	start_dt = getdate(from_date)
	end_dt = getdate(to_date)
	total_days = max(1, date_diff(end_dt, start_dt) + 1)

	daily_map: dict[str, dict] = {}
	for offset in range(total_days):
		d_str = str(add_days(start_dt, offset))
		daily_map[d_str] = {
			"sales": 0.0,
			"pos_sales": 0.0,
			"direct_sales": 0.0,
			"cost": 0.0,
			"profit": 0.0,
			"invoices": set(),
		}

	category_map: dict[str, dict] = {}
	item_map: dict[str, dict] = {}
	# Heatmap: (day_idx 0..6 Mon..Sun, hour 0..23) -> {"sales": float, "invoices": set}
	heatmap_grid: dict[tuple[int, int], dict] = {
		(d, h): {"sales": 0.0, "invoices": set()} for d in range(7) for h in range(24)
	}

	all_invoices: set[str] = set()
	return_invoices: set[str] = set()
	total_sales = 0.0
	total_cost = 0.0
	total_returns = 0.0
	total_units = 0.0

	for r in rows:
		inv_key = f"{r.doctype}::{r.invoice_name}"
		net_amount = flt(r.net_amount)
		qty = flt(r.qty)
		stock_qty = flt(r.stock_qty) if flt(r.stock_qty) != 0 else qty

		unit_cost = flt(r.incoming_rate)
		if unit_cost <= 0 and r.item_code:
			unit_cost = flt(cost_map.get(r.item_code, 0.0))

		line_cost = stock_qty * unit_cost
		line_profit = net_amount - line_cost

		total_sales += net_amount
		total_cost += line_cost
		total_units += qty

		if cint(r.is_return) == 1 or net_amount < 0:
			total_returns += abs(net_amount)
			return_invoices.add(inv_key)
		else:
			all_invoices.add(inv_key)

		d_str = str(getdate(r.posting_date))
		if d_str in daily_map:
			daily_map[d_str]["sales"] += net_amount
			if getattr(r, "sale_channel", "") == "POS" or r.doctype == "POS Invoice":
				daily_map[d_str]["pos_sales"] += net_amount
			else:
				daily_map[d_str]["direct_sales"] += net_amount
			daily_map[d_str]["cost"] += line_cost
			daily_map[d_str]["profit"] += line_profit
			if not cint(r.is_return):
				daily_map[d_str]["invoices"].add(inv_key)

		cat = (r.item_group or "Sin Categoría").strip() or "Sin Categoría"
		if cat not in category_map:
			category_map[cat] = {"item_group": cat, "sales": 0.0, "cost": 0.0, "profit": 0.0, "qty": 0.0}
		category_map[cat]["sales"] += net_amount
		category_map[cat]["cost"] += line_cost
		category_map[cat]["profit"] += line_profit
		category_map[cat]["qty"] += qty

		code = r.item_code or r.item_name or "SIN-CODIGO"
		if code not in item_map:
			item_map[code] = {
				"item_code": code,
				"item_name": r.item_name or code,
				"item_group": cat,
				"revenue": 0.0,
				"cost": 0.0,
				"profit": 0.0,
				"qty": 0.0,
			}
		item_map[code]["revenue"] += net_amount
		item_map[code]["cost"] += line_cost
		item_map[code]["profit"] += line_profit
		item_map[code]["qty"] += qty

		# Parse hour and weekday
		p_date = getdate(r.posting_date)
		day_idx = p_date.weekday()  # 0=Monday .. 6=Sunday
		raw_time = str(r.posting_time or "12:00:00").strip()
		try:
			hour = int(raw_time.split(":")[0])
			if hour < 0 or hour > 23:
				hour = 12
		except Exception:
			hour = 12

		cell = heatmap_grid[(day_idx, hour)]
		cell["sales"] += net_amount
		if not cint(r.is_return):
			cell["invoices"].add(inv_key)

	ticket_count = len(all_invoices) if all_invoices else (len(return_invoices) if total_sales != 0 else 0)
	gross_profit = total_sales - total_cost
	gross_margin_pct = round((gross_profit / total_sales) * 100.0, 2) if abs(total_sales) > 1e-9 else 0.0
	avg_ticket = round(total_sales / ticket_count, 2) if ticket_count > 0 else 0.0
	upt = round(total_units / ticket_count, 2) if ticket_count > 0 else 0.0

	# Daily trend arrays
	dates_list = sorted(daily_map.keys())
	daily_sales = [round(daily_map[d]["sales"], 2) for d in dates_list]
	daily_pos_sales = [round(daily_map[d]["pos_sales"], 2) for d in dates_list]
	daily_direct_sales = [round(daily_map[d]["direct_sales"], 2) for d in dates_list]
	daily_cost = [round(daily_map[d]["cost"], 2) for d in dates_list]
	daily_profit = [round(daily_map[d]["profit"], 2) for d in dates_list]
	daily_tickets = [len(daily_map[d]["invoices"]) for d in dates_list]
	daily_margin_pct = [
		round((daily_map[d]["profit"] / daily_map[d]["sales"]) * 100.0, 2)
		if abs(daily_map[d]["sales"]) > 1e-9
		else 0.0
		for d in dates_list
	]

	# Top items
	items_list = [
		{
			**v,
			"revenue": round(v["revenue"], 2),
			"cost": round(v["cost"], 2),
			"profit": round(v["profit"], 2),
			"qty": round(v["qty"], 2),
			"margin_pct": round((v["profit"] / v["revenue"]) * 100.0, 2) if abs(v["revenue"]) > 1e-9 else 0.0,
		}
		for v in item_map.values()
	]
	top_by_revenue = sorted(items_list, key=lambda x: x["revenue"], reverse=True)[:10]
	top_by_profit = sorted(items_list, key=lambda x: x["profit"], reverse=True)[:10]
	top_by_qty = sorted(items_list, key=lambda x: x["qty"], reverse=True)[:10]

	# Heatmap data: [hour, day_idx, sales] (3 elements so ECharts visualMap always maps index 2 = sales)
	heatmap_data = []
	tickets_by_cell: dict[str, int] = {}
	max_cell_sales = 0.0
	for d in range(7):
		for h in range(24):
			cell = heatmap_grid[(d, h)]
			val = round(max(0.0, cell["sales"]), 2)
			t_count = len(cell["invoices"])
			if val > max_cell_sales:
				max_cell_sales = val
			heatmap_data.append([h, d, val])
			if t_count > 0:
				tickets_by_cell[f"{h}_{d}"] = t_count

	return {
		"net_sales": round(total_sales, 2),
		"cogs": round(total_cost, 2),
		"gross_profit": round(gross_profit, 2),
		"gross_margin_pct": gross_margin_pct,
		"returns_total": round(total_returns, 2),
		"ticket_count": ticket_count,
		"total_units": round(total_units, 2),
		"avg_ticket": avg_ticket,
		"upt": upt,
		"daily_trend": {
			"dates": dates_list,
			"sales": daily_sales,
			"pos_sales": daily_pos_sales,
			"direct_sales": daily_direct_sales,
			"cost": daily_cost,
			"profit": daily_profit,
			"margin_pct": daily_margin_pct,
			"tickets": daily_tickets,
		},
		"category_map": category_map,
		"top_items": {
			"by_revenue": top_by_revenue,
			"by_profit": top_by_profit,
			"by_qty": top_by_qty,
		},
		"hourly_heatmap": {
			"days": WEEKDAY_LABELS_ES,
			"hours": [f"{h:02d}:00" for h in range(24)],
			"data": heatmap_data,
			"tickets_by_cell": tickets_by_cell,
			"max_value": round(max_cell_sales, 2),
		},
	}


def _get_payment_methods_breakdown(
	company: str,
	from_date: str,
	to_date: str,
	warehouse: str | None = None,
	include_pending_pos: bool = True,
) -> list[dict]:
	"""Aggregate payment methods from Sales Invoice Payment, Payment Entry, and POS Invoice Payment."""
	params = {"company": company, "from_date": from_date, "to_date": to_date}
	wh_exists_si = ""
	if warehouse:
		params["warehouse"] = warehouse
		wh_exists_si = """
		  AND EXISTS (
		      SELECT 1 FROM `tabSales Invoice Item` sii
		      WHERE sii.parent = si.name AND sii.warehouse = %(warehouse)s
		  )
		"""

	mode_totals: dict[str, float] = {}
	has_pos_table = frappe.db.table_exists("POS Invoice") and frappe.db.table_exists("POS Invoice Payment")
	exclude_consolidated_si = ""
	if has_pos_table:
		exclude_consolidated_si = """
		  AND IFNULL(si.is_consolidated, 0) = 0
		  AND NOT EXISTS (
		      SELECT 1 FROM `tabPOS Invoice` pi_c
		      WHERE pi_c.consolidated_invoice = si.name
		        AND pi_c.docstatus = 1
		  )
		"""

	# 1. POS payments directly on non-consolidated Sales Invoice (`Sales Invoice Payment`)
	sip_rows = frappe.db.sql(
		f"""
		SELECT
			COALESCE(NULLIF(sip.mode_of_payment, ''), 'Efectivo') AS mode_of_payment,
			SUM(IFNULL(sip.base_amount, sip.amount)) AS total_amount
		FROM `tabSales Invoice Payment` sip
		INNER JOIN `tabSales Invoice` si ON si.name = sip.parent
		WHERE si.docstatus = 1
		  AND si.company = %(company)s
		  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  {exclude_consolidated_si}
		  {wh_exists_si}
		GROUP BY COALESCE(NULLIF(sip.mode_of_payment, ''), 'Efectivo')
		""",
		params,
		as_dict=True,
	)
	for r in sip_rows:
		if flt(r.total_amount) > 0:
			mode_totals[r.mode_of_payment] = mode_totals.get(r.mode_of_payment, 0.0) + flt(r.total_amount)

	# 2. All POS Invoices (both consolidated and optionally pending unconsolidated) on their real posting_date
	if has_pos_table:
		wh_exists_pos = ""
		if warehouse:
			wh_exists_pos = """
			  AND EXISTS (
			      SELECT 1 FROM `tabPOS Invoice Item` pii
			      WHERE pii.parent = pi.name AND pii.warehouse = %(warehouse)s
			  )
			"""
		pos_status_clause = (
			""
			if include_pending_pos
			else "AND IFNULL(pi.consolidated_invoice, '') != ''"
		)
		pos_pay_rows = frappe.db.sql(
			f"""
			SELECT
				COALESCE(NULLIF(pip.mode_of_payment, ''), 'Efectivo') AS mode_of_payment,
				SUM(IFNULL(pip.base_amount, pip.amount)) AS total_amount
			FROM `tabPOS Invoice Payment` pip
			INNER JOIN `tabPOS Invoice` pi ON pi.name = pip.parent
			WHERE pi.docstatus = 1
			  AND pi.company = %(company)s
			  AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s
			  {pos_status_clause}
			  {wh_exists_pos}
			GROUP BY COALESCE(NULLIF(pip.mode_of_payment, ''), 'Efectivo')
			""",
			params,
			as_dict=True,
		)
		for r in pos_pay_rows:
			if flt(r.total_amount) > 0:
				mode_totals[r.mode_of_payment] = mode_totals.get(r.mode_of_payment, 0.0) + flt(r.total_amount)

	# 3. Payment Entries in the period (Receive from Customers) when not using POS payments
	if frappe.db.table_exists("Payment Entry") and not warehouse:
		pe_rows = frappe.db.sql(
			"""
			SELECT
				COALESCE(NULLIF(pe.mode_of_payment, ''), 'Transferencia / Pago') AS mode_of_payment,
				SUM(IFNULL(pe.base_paid_amount, pe.paid_amount)) AS total_amount
			FROM `tabPayment Entry` pe
			WHERE pe.docstatus = 1
			  AND pe.company = %(company)s
			  AND pe.payment_type = 'Receive'
			  AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s
			GROUP BY COALESCE(NULLIF(pe.mode_of_payment, ''), 'Transferencia / Pago')
			""",
			params,
			as_dict=True,
		)
		for r in pe_rows:
			if flt(r.total_amount) > 0:
				mode_totals[r.mode_of_payment] = mode_totals.get(r.mode_of_payment, 0.0) + flt(r.total_amount)

	# 4. Credit / Pending collection on non-consolidated Sales Invoices in the period
	credit_row = frappe.db.sql(
		f"""
		SELECT SUM(CASE WHEN si.outstanding_amount > 0 THEN si.outstanding_amount ELSE 0 END) AS pending_credit
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1
		  AND si.company = %(company)s
		  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  {exclude_consolidated_si}
		  {wh_exists_si}
		""",
		params,
		as_dict=True,
	)
	pending_credit = flt(credit_row[0].pending_credit) if credit_row else 0.0
	if pending_credit > 0:
		mode_totals["Crédito / Por Cobrar"] = mode_totals.get("Crédito / Por Cobrar", 0.0) + pending_credit

	result = [
		{"name": mode, "value": round(val, 2)}
		for mode, val in sorted(mode_totals.items(), key=lambda item: item[1], reverse=True)
		if round(val, 2) > 0
	]
	return result


def _get_inventory_and_alerts(
	company: str,
	warehouse: str | None,
	to_date: str,
	category_sales_map: dict[str, dict],
) -> dict:
	"""Compute current inventory value (cost vs retail), category stock vs sales, low-stock stars & dead stock."""
	default_price_list = (
		frappe.db.get_single_value("Selling Settings", "selling_price_list")
		or frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
		or "Standard Selling"
	)

	wh_clause = "AND b.warehouse = %(warehouse)s" if warehouse else ""
	params = {
		"company": company,
		"price_list": default_price_list,
		"to_date": to_date,
		"from_30d": str(add_days(to_date, -29)),
	}
	if warehouse:
		params["warehouse"] = warehouse

	bin_items = frappe.db.sql(
		f"""
		SELECT
			b.item_code,
			COALESCE(NULLIF(i.item_name, ''), b.item_code) AS item_name,
			COALESCE(NULLIF(i.item_group, ''), 'Sin Categoría') AS item_group,
			SUM(IFNULL(b.actual_qty, 0)) AS actual_qty,
			SUM(IFNULL(b.stock_value, IFNULL(b.actual_qty, 0) * IFNULL(b.valuation_rate, 0))) AS stock_value,
			MAX(IFNULL(b.valuation_rate, 0)) AS valuation_rate,
			MAX(IFNULL(ip.price_list_rate, IFNULL(i.standard_rate, 0))) AS selling_rate
		FROM `tabBin` b
		INNER JOIN `tabWarehouse` w ON w.name = b.warehouse
		LEFT JOIN `tabItem` i ON i.name = b.item_code
		LEFT JOIN (
			SELECT item_code, MAX(price_list_rate) AS price_list_rate
			FROM `tabItem Price`
			WHERE selling = 1 AND price_list = %(price_list)s
			GROUP BY item_code
		) ip ON ip.item_code = b.item_code
		WHERE w.company = %(company)s
		  AND IFNULL(i.disabled, 0) = 0
		  {wh_clause}
		GROUP BY b.item_code, i.item_name, i.item_group
		""",
		params,
		as_dict=True,
	)

	# Sales velocity in last 30 days + last sale date per item
	wh_si_clause = "AND sii.warehouse = %(warehouse)s" if warehouse else ""
	sales_stats_rows = frappe.db.sql(
		f"""
		SELECT
			sii.item_code,
			SUM(CASE WHEN si.posting_date BETWEEN %(from_30d)s AND %(to_date)s AND si.is_return = 0 THEN IFNULL(sii.stock_qty, sii.qty) ELSE 0 END) AS qty_30d,
			SUM(CASE WHEN si.posting_date BETWEEN %(from_30d)s AND %(to_date)s THEN IFNULL(sii.base_net_amount, 0) ELSE 0 END) AS revenue_30d,
			MAX(CASE WHEN si.is_return = 0 THEN si.posting_date ELSE NULL END) AS last_sale_date
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE si.docstatus = 1
		  AND si.company = %(company)s
		  AND si.posting_date <= %(to_date)s
		  {wh_si_clause}
		GROUP BY sii.item_code
		""",
		params,
		as_dict=True,
	)
	sales_stats_map = {r.item_code: r for r in sales_stats_rows if r.item_code}

	total_stock_cost = 0.0
	total_stock_retail = 0.0
	sku_with_stock = 0
	sku_out_of_stock = 0

	cat_stock_map: dict[str, float] = {}
	low_stock_candidates: list[dict] = []
	dead_stock_candidates: list[dict] = []

	ref_date = getdate(to_date)

	for item in bin_items:
		code = item.item_code
		qty = flt(item.actual_qty)
		stock_val = flt(item.stock_value)
		if stock_val <= 0 and qty > 0 and flt(item.valuation_rate) > 0:
			stock_val = qty * flt(item.valuation_rate)

		selling_rate = flt(item.selling_rate)
		if selling_rate <= 0 and flt(item.valuation_rate) > 0:
			selling_rate = flt(item.valuation_rate)

		cat = (item.item_group or "Sin Categoría").strip() or "Sin Categoría"

		if qty > 0:
			sku_with_stock += 1
			total_stock_cost += max(0.0, stock_val)
			total_stock_retail += max(0.0, qty * selling_rate)
			cat_stock_map[cat] = cat_stock_map.get(cat, 0.0) + max(0.0, stock_val)
		else:
			sku_out_of_stock += 1

		stat = sales_stats_map.get(code)
		qty_30d = flt(stat.qty_30d) if stat else 0.0
		rev_30d = flt(stat.revenue_30d) if stat else 0.0
		last_sale = stat.last_sale_date if stat else None

		# 1. Low stock star items: had sales in last 30d and coverage <= 7 days (or qty <= 0)
		if qty_30d > 0:
			daily_velocity = qty_30d / 30.0
			coverage_days = round(qty / daily_velocity, 1) if daily_velocity > 0 and qty > 0 else 0.0
			if qty <= 0 or coverage_days <= 7.0:
				low_stock_candidates.append(
					{
						"item_code": code,
						"item_name": item.item_name or code,
						"item_group": cat,
						"actual_qty": round(qty, 2),
						"qty_sold_30d": round(qty_30d, 2),
						"revenue_30d": round(rev_30d, 2),
						"coverage_days": max(0.0, coverage_days),
					}
				)

		# 2. Dead stock: positive stock and >= 60 days without sale (or never sold)
		if qty > 0 and stock_val > 0:
			days_without_sale = date_diff(ref_date, getdate(last_sale)) if last_sale else 999
			if days_without_sale >= 60:
				dead_stock_candidates.append(
					{
						"item_code": code,
						"item_name": item.item_name or code,
						"item_group": cat,
						"actual_qty": round(qty, 2),
						"stock_value": round(stock_val, 2),
						"last_sale_date": str(last_sale) if last_sale else _("Sin ventas"),
						"days_without_sale": None if not last_sale else int(days_without_sale),
					}
				)

	# Also check items sold in last 30d that didn't appear in Bin at all
	bin_codes = {b.item_code for b in bin_items}
	for code, stat in sales_stats_map.items():
		if code not in bin_codes and flt(stat.qty_30d) > 0:
			item_meta = frappe.db.get_value(
				"Item", code, ["item_name", "item_group", "is_stock_item"], as_dict=True
			)
			if item_meta and cint(item_meta.is_stock_item) == 1:
				low_stock_candidates.append(
					{
						"item_code": code,
						"item_name": item_meta.item_name or code,
						"item_group": item_meta.item_group or "Sin Categoría",
						"actual_qty": 0.0,
						"qty_sold_30d": round(flt(stat.qty_30d), 2),
						"revenue_30d": round(flt(stat.revenue_30d), 2),
						"coverage_days": 0.0,
					}
				)

	low_stock_stars = sorted(
		low_stock_candidates,
		key=lambda x: (x["coverage_days"], -x["revenue_30d"]),
	)[:15]

	dead_stock = sorted(
		dead_stock_candidates,
		key=lambda x: x["stock_value"],
		reverse=True,
	)[:15]

	# Combine categories from sales & inventory
	all_categories = set(category_sales_map.keys()) | set(cat_stock_map.keys())
	by_category = []
	for cat in all_categories:
		sales_info = category_sales_map.get(cat, {})
		s_val = round(flt(sales_info.get("sales", 0.0)), 2)
		p_val = round(flt(sales_info.get("profit", 0.0)), 2)
		q_val = round(flt(sales_info.get("qty", 0.0)), 2)
		st_val = round(flt(cat_stock_map.get(cat, 0.0)), 2)
		if s_val != 0 or st_val != 0:
			by_category.append(
				{
					"item_group": cat,
					"sales": s_val,
					"profit": p_val,
					"qty": q_val,
					"stock_value": st_val,
				}
			)

	by_category.sort(key=lambda x: (x["sales"], x["stock_value"]), reverse=True)

	return {
		"stock_cost_value": round(total_stock_cost, 2),
		"stock_retail_value": round(total_stock_retail, 2),
		"potential_profit": round(max(0.0, total_stock_retail - total_stock_cost), 2),
		"sku_with_stock": sku_with_stock,
		"sku_out_of_stock": sku_out_of_stock,
		"by_category": by_category,
		"low_stock_stars": low_stock_stars,
		"dead_stock": dead_stock,
	}


def _get_financial_statements(
	company: str,
	from_date: str,
	to_date: str,
	commercial_sales: float,
	commercial_cogs: float,
	stock_cost_value: float,
) -> dict:
	"""Compute Balance Sheet (as of to_date) and Income Statement (from_date..to_date) from GL Entries."""
	# 1. Balance Sheet as of to_date (cumulative GL entries where is_cancelled = 0)
	bs_rows = frappe.db.sql(
		"""
		SELECT
			acc.name AS account,
			acc.account_name,
			acc.root_type,
			IFNULL(acc.account_type, '') AS account_type,
			SUM(IFNULL(gl.debit, 0)) AS total_debit,
			SUM(IFNULL(gl.credit, 0)) AS total_credit
		FROM `tabGL Entry` gl
		INNER JOIN `tabAccount` acc ON acc.name = gl.account
		WHERE gl.is_cancelled = 0
		  AND gl.company = %(company)s
		  AND gl.posting_date <= %(to_date)s
		GROUP BY acc.name, acc.account_name, acc.root_type, acc.account_type
		""",
		{"company": company, "to_date": to_date},
		as_dict=True,
	)

	cash_and_bank = 0.0
	accounts_receivable = 0.0
	gl_inventory = 0.0
	other_assets = 0.0

	accounts_payable = 0.0
	other_liabilities = 0.0
	equity_capital = 0.0
	unclosed_pnl_to_date = 0.0

	for r in bs_rows:
		root = r.root_type
		acc_type = (r.account_type or "").strip()
		debit = flt(r.total_debit)
		credit = flt(r.total_credit)

		if root == "Asset":
			bal = debit - credit
			if acc_type in ("Cash", "Bank"):
				cash_and_bank += bal
			elif acc_type == "Receivable":
				accounts_receivable += bal
			elif acc_type == "Stock":
				gl_inventory += bal
			else:
				other_assets += bal
		elif root == "Liability":
			bal = credit - debit
			if acc_type == "Payable":
				accounts_payable += bal
			else:
				other_liabilities += bal
		elif root == "Equity":
			bal = credit - debit
			equity_capital += bal
		elif root in ("Income", "Expense"):
			# Credit - Debit across Income and Expense equals cumulative unclosed profit up to to_date
			unclosed_pnl_to_date += credit - debit

	# If GL Stock account wasn't used (e.g. non-perpetual or opening stock only in Bin), synchronize with Bin stock
	inventory_asset = gl_inventory
	if abs(gl_inventory) < 1e-2 and stock_cost_value > 0:
		inventory_asset = stock_cost_value
		equity_capital += stock_cost_value

	total_assets = cash_and_bank + accounts_receivable + inventory_asset + other_assets
	total_liabilities = accounts_payable + other_liabilities
	retained_and_current_earnings = unclosed_pnl_to_date
	total_equity = equity_capital + retained_and_current_earnings
	total_liabilities_and_equity = total_liabilities + total_equity

	# 2. Income Statement for period [from_date, to_date]
	pnl_rows = frappe.db.sql(
		"""
		SELECT
			acc.name AS account,
			COALESCE(NULLIF(acc.account_name, ''), acc.name) AS account_name,
			acc.root_type,
			IFNULL(acc.account_type, '') AS account_type,
			SUM(IFNULL(gl.debit, 0)) AS total_debit,
			SUM(IFNULL(gl.credit, 0)) AS total_credit
		FROM `tabGL Entry` gl
		INNER JOIN `tabAccount` acc ON acc.name = gl.account
		WHERE gl.is_cancelled = 0
		  AND gl.company = %(company)s
		  AND IFNULL(gl.voucher_type, '') != 'Period Closing Voucher'
		  AND gl.posting_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY acc.name, acc.account_name, acc.root_type, acc.account_type
		""",
		{"company": company, "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)

	gl_income = 0.0
	gl_cogs = 0.0
	gl_op_expenses = 0.0
	expense_breakdown_map: dict[str, float] = {}

	cogs_types = {"Cost of Goods Sold", "Stock Adjustment", "Expenses Included In Valuation"}

	for r in pnl_rows:
		root = r.root_type
		acc_type = (r.account_type or "").strip()
		acc_name_lower = (r.account_name or "").lower()
		debit = flt(r.total_debit)
		credit = flt(r.total_credit)

		if root == "Income":
			gl_income += credit - debit
		elif root == "Expense":
			exp_amount = debit - credit
			is_cogs = acc_type in cogs_types or any(
				kw in acc_name_lower for kw in ("costo de venta", "cost of goods", "cogs", "costo mercader")
			)
			if is_cogs:
				gl_cogs += exp_amount
			else:
				gl_op_expenses += exp_amount
				if exp_amount > 0:
					label = r.account_name or r.account
					expense_breakdown_map[label] = expense_breakdown_map.get(label, 0.0) + exp_amount

	# Reconcile with commercial sales/COGS if pending POS or non-perpetual COGS exists
	total_income = max(gl_income, commercial_sales) if commercial_sales > 0 else gl_income
	cogs = gl_cogs if gl_cogs > 0 else commercial_cogs
	gross_profit = total_income - cogs
	operating_expenses = max(0.0, gl_op_expenses)
	net_profit = gross_profit - operating_expenses
	net_margin_pct = round((net_profit / total_income) * 100.0, 2) if abs(total_income) > 1e-9 else 0.0
	op_expense_pct = round((operating_expenses / total_income) * 100.0, 2) if abs(total_income) > 1e-9 else 0.0

	expense_breakdown = [
		{"account": k, "amount": round(v, 2)}
		for k, v in sorted(expense_breakdown_map.items(), key=lambda x: x[1], reverse=True)[:10]
	]

	return {
		"balance_sheet": {
			"as_of_date": to_date,
			"cash_and_bank": round(cash_and_bank, 2),
			"accounts_receivable": round(accounts_receivable, 2),
			"inventory": round(inventory_asset, 2),
			"other_assets": round(other_assets, 2),
			"total_assets": round(total_assets, 2),
			"accounts_payable": round(accounts_payable, 2),
			"other_liabilities": round(other_liabilities, 2),
			"total_liabilities": round(total_liabilities, 2),
			"equity_capital": round(equity_capital, 2),
			"retained_and_current_earnings": round(retained_and_current_earnings, 2),
			"total_equity": round(total_equity, 2),
			"total_liabilities_and_equity": round(total_liabilities_and_equity, 2),
		},
		"income_statement": {
			"from_date": from_date,
			"to_date": to_date,
			"total_income": round(total_income, 2),
			"cogs": round(cogs, 2),
			"gross_profit": round(gross_profit, 2),
			"operating_expenses": round(operating_expenses, 2),
			"net_profit": round(net_profit, 2),
			"net_margin_pct": net_margin_pct,
			"op_expense_pct": op_expense_pct,
			"expense_breakdown": expense_breakdown,
		},
	}


def _build_indicators_table(
	currency: str,
	period_days: int,
	current_comm: dict,
	prev_comm: dict,
	financials: dict,
	prev_financials: dict,
	inventory_data: dict,
) -> list[dict]:
	"""Build the 13 executive financial & operational indicators table at the bottom of the dashboard."""
	bs = financials["balance_sheet"]
	pnl = financials["income_statement"]
	prev_pnl = prev_financials["income_statement"]

	# 1. Margen Bruto (%)
	gross_margin = flt(current_comm["gross_margin_pct"])
	prev_gross_margin = flt(prev_comm["gross_margin_pct"])

	# 2. Margen Neto Contable (%)
	net_margin = flt(pnl["net_margin_pct"])
	prev_net_margin = flt(prev_pnl["net_margin_pct"])

	# 3. Peso de Gastos Operativos (%)
	op_exp_pct = flt(pnl["op_expense_pct"])
	prev_op_exp_pct = flt(prev_pnl["op_expense_pct"])

	# 4. ROA (%)
	total_assets = flt(bs["total_assets"])
	roa = round((flt(pnl["net_profit"]) / total_assets) * 100.0, 2) if total_assets > 0 else 0.0

	# 5. ROE (%)
	total_equity = flt(bs["total_equity"])
	roe = round((flt(pnl["net_profit"]) / total_equity) * 100.0, 2) if total_equity > 0 else 0.0

	# 6. Razón Corriente (Liquidez General)
	current_assets = max(0.0, flt(bs["cash_and_bank"])) + max(0.0, flt(bs["accounts_receivable"])) + max(0.0, flt(bs["inventory"]))
	total_liabilities = max(0.0, flt(bs["total_liabilities"]))
	current_ratio = round(current_assets / total_liabilities, 2) if total_liabilities > 0 else None

	# 7. Prueba Ácida (Liquidez Inmediata)
	quick_assets = max(0.0, flt(bs["cash_and_bank"])) + max(0.0, flt(bs["accounts_receivable"]))
	quick_ratio = round(quick_assets / total_liabilities, 2) if total_liabilities > 0 else None

	# 8. Capital de Trabajo Neto
	working_capital = round(current_assets - total_liabilities, 2)

	# 9. Índice de Endeudamiento (%)
	debt_ratio = round((total_liabilities / total_assets) * 100.0, 2) if total_assets > 0 else 0.0

	# 10. Rotación de Inventario (período)
	stock_cost = flt(inventory_data["stock_cost_value"])
	period_cogs = flt(current_comm["cogs"]) or flt(pnl["cogs"])
	inv_turnover = round(period_cogs / stock_cost, 2) if stock_cost > 0 else 0.0

	# 11. Días Estimados de Inventario (DIO)
	daily_cogs = period_cogs / max(1, period_days)
	dio_days = round(stock_cost / daily_cogs, 1) if daily_cogs > 0 else None

	# 12. Ticket Promedio y Unidades por Ticket (UPT)
	avg_ticket = flt(current_comm["avg_ticket"])
	prev_avg_ticket = flt(prev_comm["avg_ticket"])
	upt = flt(current_comm["upt"])

	# 13. Cobertura de Caja sobre Cuentas por Pagar
	ap = max(0.0, flt(bs["accounts_payable"]))
	cash_val = max(0.0, flt(bs["cash_and_bank"]))
	cash_coverage = round(cash_val / ap, 2) if ap > 0 else None

	indicators = [
		{
			"category": "Rentabilidad",
			"name": "Margen Bruto (%)",
			"formula": "(Ventas Netas - Costo de Ventas) / Ventas Netas",
			"value": gross_margin,
			"value_formatted": f"{gross_margin:.2f}%",
			"reference_formatted": f"Período ant.: {prev_gross_margin:.2f}% (Meta >= 25%)",
			"status": "good" if gross_margin >= 25 else ("warning" if gross_margin >= 15 else "danger"),
			"status_label": "Saludable" if gross_margin >= 25 else ("Moderado" if gross_margin >= 15 else "Bajo"),
		},
		{
			"category": "Rentabilidad",
			"name": "Margen Neto Contable (%)",
			"formula": "Utilidad Neta / Ingresos Totales",
			"value": net_margin,
			"value_formatted": f"{net_margin:.2f}%",
			"reference_formatted": f"Período ant.: {prev_net_margin:.2f}% (Meta >= 10%)",
			"status": "good" if net_margin >= 10 else ("warning" if net_margin >= 0 else "danger"),
			"status_label": "Rentable" if net_margin >= 10 else ("Equilibrio" if net_margin >= 0 else "Pérdida"),
		},
		{
			"category": "Rentabilidad",
			"name": "Peso de Gastos Operativos (%)",
			"formula": "Gastos Operativos / Ingresos Totales",
			"value": op_exp_pct,
			"value_formatted": f"{op_exp_pct:.2f}%",
			"reference_formatted": f"Período ant.: {prev_op_exp_pct:.2f}% (Ideal <= 20%)",
			"status": "good" if op_exp_pct <= 20 else ("warning" if op_exp_pct <= 35 else "danger"),
			"status_label": "Controlado" if op_exp_pct <= 20 else ("Vigilancia" if op_exp_pct <= 35 else "Elevado"),
		},
		{
			"category": "Rentabilidad",
			"name": "ROA (Retorno sobre Activos)",
			"formula": "Utilidad Neta del Período / Activo Total",
			"value": roa,
			"value_formatted": f"{roa:.2f}%",
			"reference_formatted": "Meta periodo >= 3.0%",
			"status": "good" if roa >= 3 else ("warning" if roa >= 0 else "danger"),
			"status_label": "Positivo" if roa >= 3 else ("Moderado" if roa >= 0 else "Negativo"),
		},
		{
			"category": "Rentabilidad",
			"name": "ROE (Retorno sobre Patrimonio)",
			"formula": "Utilidad Neta del Período / Patrimonio Total",
			"value": roe,
			"value_formatted": f"{roe:.2f}%",
			"reference_formatted": "Meta periodo >= 5.0%",
			"status": "good" if roe >= 5 else ("warning" if roe >= 0 else "danger"),
			"status_label": "Óptimo" if roe >= 5 else ("Moderado" if roe >= 0 else "Negativo"),
		},
		{
			"category": "Liquidez y Solvencia",
			"name": "Razón Corriente (Liquidez General)",
			"formula": "(Caja/Bancos + Cuentas por Cobrar + Inventario) / Pasivo Total",
			"value": current_ratio if current_ratio is not None else 99.0,
			"value_formatted": f"{current_ratio:.2f}x" if current_ratio is not None else "Sin Deuda",
			"reference_formatted": "Meta recomendada >= 1.50x",
			"status": "good"
			if (current_ratio is None or current_ratio >= 1.5)
			else ("warning" if current_ratio >= 1.0 else "danger"),
			"status_label": "Solvente"
			if (current_ratio is None or current_ratio >= 1.5)
			else ("Ajustado" if current_ratio >= 1.0 else "Riesgo Liquidez"),
		},
		{
			"category": "Liquidez y Solvencia",
			"name": "Prueba Ácida (Liquidez Inmediata)",
			"formula": "(Caja/Bancos + Cuentas por Cobrar) / Pasivo Total",
			"value": quick_ratio if quick_ratio is not None else 99.0,
			"value_formatted": f"{quick_ratio:.2f}x" if quick_ratio is not None else "Sin Deuda",
			"reference_formatted": "Meta recomendada >= 0.80x",
			"status": "good"
			if (quick_ratio is None or quick_ratio >= 0.8)
			else ("warning" if quick_ratio >= 0.4 else "danger"),
			"status_label": "Sólida"
			if (quick_ratio is None or quick_ratio >= 0.8)
			else ("Moderada" if quick_ratio >= 0.4 else "Baja"),
		},
		{
			"category": "Liquidez y Solvencia",
			"name": "Capital de Trabajo Neto",
			"formula": "Activo Corriente - Pasivo Total",
			"value": working_capital,
			"value_formatted": _format_currency_compact(working_capital, currency),
			"reference_formatted": "Debe ser positivo (> 0)",
			"status": "good" if working_capital > 0 else ("warning" if working_capital == 0 else "danger"),
			"status_label": "Positivo" if working_capital > 0 else ("Neutro" if working_capital == 0 else "Déficit"),
		},
		{
			"category": "Liquidez y Solvencia",
			"name": "Índice de Endeudamiento (%)",
			"formula": "Pasivo Total / Activo Total",
			"value": debt_ratio,
			"value_formatted": f"{debt_ratio:.2f}%",
			"reference_formatted": "Límite prudente <= 50%",
			"status": "good" if debt_ratio <= 50 else ("warning" if debt_ratio <= 70 else "danger"),
			"status_label": "Bajo Endeudamiento"
			if debt_ratio <= 50
			else ("Moderado" if debt_ratio <= 70 else "Alto Apalancamiento"),
		},
		{
			"category": "Inventario y Operación",
			"name": "Rotación de Inventario (Período)",
			"formula": "Costo de Ventas del Período / Valor del Inventario Actual",
			"value": inv_turnover,
			"value_formatted": f"{inv_turnover:.2f}x",
			"reference_formatted": f"En {period_days} días analizados",
			"status": "good" if inv_turnover >= 0.5 else ("warning" if inv_turnover >= 0.15 else "danger"),
			"status_label": "Alta Rotación"
			if inv_turnover >= 0.5
			else ("Rotación Media" if inv_turnover >= 0.15 else "Rotación Lenta"),
		},
		{
			"category": "Inventario y Operación",
			"name": "Días Estimados de Inventario (DIO)",
			"formula": "Inventario Actual / Costo de Venta Diario Promedio",
			"value": dio_days if dio_days is not None else 0.0,
			"value_formatted": f"{dio_days:.1f} días" if dio_days is not None else "N/A",
			"reference_formatted": "Rango óptimo retail: 15 a 60 días",
			"status": "good"
			if (dio_days is not None and 10 <= dio_days <= 60)
			else ("warning" if (dio_days is not None and dio_days <= 90) else "danger"),
			"status_label": "Óptimo"
			if (dio_days is not None and 10 <= dio_days <= 60)
			else ("Revisar Cobertura" if dio_days is not None else "Sin Salidas"),
		},
		{
			"category": "Inventario y Operación",
			"name": "Ticket Promedio y Unidades (UPT)",
			"formula": "Ventas Netas / N.º Tickets | Unidades / N.º Tickets",
			"value": avg_ticket,
			"value_formatted": f"{_format_currency_compact(avg_ticket, currency)} ({upt:.2f} u/t)",
			"reference_formatted": f"Período ant.: {_format_currency_compact(prev_avg_ticket, currency)}",
			"status": "good"
			if avg_ticket >= prev_avg_ticket and avg_ticket > 0
			else ("warning" if avg_ticket > 0 else "danger"),
			"status_label": "En Crecimiento"
			if avg_ticket >= prev_avg_ticket and avg_ticket > 0
			else ("Estable" if avg_ticket > 0 else "Sin Ventas"),
		},
		{
			"category": "Inventario y Operación",
			"name": "Cobertura de Caja sobre Cuentas por Pagar",
			"formula": "Efectivo y Bancos / Cuentas por Pagar a Proveedores",
			"value": cash_coverage if cash_coverage is not None else 99.0,
			"value_formatted": f"{cash_coverage:.2f}x" if cash_coverage is not None else "Sin CxP",
			"reference_formatted": "Meta recomendada >= 1.00x",
			"status": "good"
			if (cash_coverage is None or cash_coverage >= 1.0)
			else ("warning" if cash_coverage >= 0.5 else "danger"),
			"status_label": "Cubierto"
			if (cash_coverage is None or cash_coverage >= 1.0)
			else ("Parcial" if cash_coverage >= 0.5 else "Ajustado"),
		},
	]
	return indicators


@frappe.whitelist()
def get_store_dashboard_data(
	company: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	warehouse: str | None = None,
	include_pending_pos: int | str = 1,
) -> dict:
	"""Return complete executive dashboard payload for a retail store business owner."""
	_ensure_dashboard_access()

	resolved_company = _resolve_company(company)
	currency = (
		frappe.db.get_value("Company", resolved_company, "default_currency")
		or frappe.db.get_single_value("Global Defaults", "default_currency")
		or "USD"
	)
	symbol = frappe.db.get_value("Currency", currency, "symbol") or "$"

	end_date = str(getdate(to_date)) if to_date else str(nowdate())
	start_date = str(getdate(from_date)) if from_date else str(add_days(end_date, -29))
	if getdate(start_date) > getdate(end_date):
		start_date, end_date = end_date, start_date

	period_days = max(1, date_diff(getdate(end_date), getdate(start_date)) + 1)
	prev_to_date = str(add_days(start_date, -1))
	prev_from_date = str(add_days(prev_to_date, -(period_days - 1)))

	clean_warehouse = warehouse.strip() if isinstance(warehouse, str) and warehouse.strip() else None
	include_pos_bool = bool(cint(include_pending_pos))

	cost_map = _get_item_cost_map(resolved_company, clean_warehouse)

	# Current & previous period commercial metrics
	curr_rows = _fetch_sales_line_rows(
		resolved_company, start_date, end_date, clean_warehouse, include_pos_bool
	)
	prev_rows = _fetch_sales_line_rows(
		resolved_company, prev_from_date, prev_to_date, clean_warehouse, include_pos_bool
	)

	curr_comm = _compute_commercial_metrics(curr_rows, cost_map, start_date, end_date)
	prev_comm = _compute_commercial_metrics(prev_rows, cost_map, prev_from_date, prev_to_date)

	# Inventory & operational alerts
	inventory_data = _get_inventory_and_alerts(
		resolved_company, clean_warehouse, end_date, curr_comm["category_map"]
	)

	# Accounting financials (Balance Sheet & Income Statement)
	financials = _get_financial_statements(
		resolved_company,
		start_date,
		end_date,
		curr_comm["net_sales"],
		curr_comm["cogs"],
		inventory_data["stock_cost_value"],
	)
	prev_financials = _get_financial_statements(
		resolved_company,
		prev_from_date,
		prev_to_date,
		prev_comm["net_sales"],
		prev_comm["cogs"],
		inventory_data["stock_cost_value"],
	)

	payment_methods = _get_payment_methods_breakdown(
		resolved_company, start_date, end_date, clean_warehouse, include_pos_bool
	)

	indicators_table = _build_indicators_table(
		currency=currency,
		period_days=period_days,
		current_comm=curr_comm,
		prev_comm=prev_comm,
		financials=financials,
		prev_financials=prev_financials,
		inventory_data=inventory_data,
	)

	bs = financials["balance_sheet"]
	pnl = financials["income_statement"]
	prev_pnl = prev_financials["income_statement"]

	return {
		"filters": {
			"company": resolved_company,
			"currency": currency,
			"currency_symbol": symbol,
			"from_date": start_date,
			"to_date": end_date,
			"prev_from_date": prev_from_date,
			"prev_to_date": prev_to_date,
			"period_days": period_days,
			"warehouse": clean_warehouse or "",
			"include_pending_pos": 1 if include_pos_bool else 0,
		},
		"kpis": {
			"net_sales": curr_comm["net_sales"],
			"prev_net_sales": prev_comm["net_sales"],
			"net_sales_delta_pct": _pct_change(curr_comm["net_sales"], prev_comm["net_sales"]),
			"gross_profit": curr_comm["gross_profit"],
			"prev_gross_profit": prev_comm["gross_profit"],
			"gross_profit_delta_pct": _pct_change(curr_comm["gross_profit"], prev_comm["gross_profit"]),
			"gross_margin_pct": curr_comm["gross_margin_pct"],
			"prev_gross_margin_pct": prev_comm["gross_margin_pct"],
			"net_profit": pnl["net_profit"],
			"prev_net_profit": prev_pnl["net_profit"],
			"net_profit_delta_pct": _pct_change(pnl["net_profit"], prev_pnl["net_profit"]),
			"net_margin_pct": pnl["net_margin_pct"],
			"operating_expenses": pnl["operating_expenses"],
			"ticket_count": curr_comm["ticket_count"],
			"prev_ticket_count": prev_comm["ticket_count"],
			"avg_ticket": curr_comm["avg_ticket"],
			"prev_avg_ticket": prev_comm["avg_ticket"],
			"avg_ticket_delta_pct": _pct_change(curr_comm["avg_ticket"], prev_comm["avg_ticket"]),
			"upt": curr_comm["upt"],
			"total_units": curr_comm["total_units"],
			"returns_total": curr_comm["returns_total"],
			"stock_cost_value": inventory_data["stock_cost_value"],
			"stock_retail_value": inventory_data["stock_retail_value"],
			"potential_profit": inventory_data["potential_profit"],
			"sku_with_stock": inventory_data["sku_with_stock"],
			"sku_out_of_stock": inventory_data["sku_out_of_stock"],
			"cash_and_bank": bs["cash_and_bank"],
			"accounts_receivable": bs["accounts_receivable"],
			"accounts_payable": bs["accounts_payable"],
		},
		"financials": financials,
		"charts": {
			"daily_trend": curr_comm["daily_trend"],
			"by_category": inventory_data["by_category"],
			"top_items": curr_comm["top_items"],
			"payment_methods": payment_methods,
			"hourly_heatmap": curr_comm["hourly_heatmap"],
		},
		"alerts": {
			"low_stock_stars": inventory_data["low_stock_stars"],
			"dead_stock": inventory_data["dead_stock"],
		},
		"indicators_table": indicators_table,
	}
