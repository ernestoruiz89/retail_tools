"""Retail indicators: historical balances, explicit expense classification and pure calculations."""
# ruff: noqa: RUF001 -- Mathematical symbols in user-facing formulas are intentional.

import math
from collections import defaultdict
from datetime import date, timedelta

TARGET_KEYS = {
	"Margen bruto (%)": "gross_margin",
	"Margen neto (%)": "net_margin",
	"Peso de gastos operativos (%)": "operating_expenses_pct",
	"ROA anual (%)": "roa",
	"ROE anual (%)": "roe",
	"Razón corriente (veces)": "current_ratio",
	"Prueba ácida (veces)": "quick_ratio",
	"Capital de trabajo (moneda empresa)": "working_capital",
	"Endeudamiento (%)": "debt_ratio",
	"Rotación de inventario anual (veces)": "inventory_turnover",
	"Días de inventario (DIO)": "dio",
	"Ticket promedio (moneda empresa)": "avg_ticket",
	"Unidades por ticket (UPT)": "upt",
	"Cobertura de caja sobre CxP (veces)": "cash_coverage",
	"GMROI": "gmroi",
	"Capital estancado (%)": "dead_stock_pct",
	"Agotados con demanda (%)": "stockout_pct",
	"Descuentos (%)": "discount_pct",
	"Devoluciones (%)": "return_pct",
	"Ciclo de efectivo (días)": "cash_cycle",
	"Cobertura del punto de equilibrio (%)": "break_even_coverage",
}
ANNUAL_TARGETS = {"roa", "roe", "inventory_turnover", "gmroi"}
LOWER_TARGETS = {
	"operating_expenses_pct",
	"debt_ratio",
	"dio",
	"dead_stock_pct",
	"stockout_pct",
	"discount_pct",
	"return_pct",
	"cash_cycle",
}
BOUNDED_PERCENT_TARGETS = {"debt_ratio", "dead_stock_pct", "stockout_pct", "discount_pct"}
SIGNED_TARGETS = {"gross_margin", "net_margin", "roa", "roe", "gmroi", "working_capital", "cash_cycle"}
BEHAVIORS = {"", "Fijo", "Variable", "Costo de ventas", "Excluido"}


def number(value):
	return float(value or 0)


def as_date(value):
	return date.fromisoformat(str(value)[:10])


def validate_settings(settings, accounts):
	for field in ("dead_stock_days", "demand_days"):
		if not 1 <= number(settings.get(field)) <= 3650:
			raise ValueError("Los días de inventario y demanda deben estar entre 1 y 3650.")
	seen = set()
	for row in settings.get("expenses", []):
		name = row.get("account")
		account = accounts.get(name)
		if name in seen:
			raise ValueError(f"Cuenta duplicada: {name}")
		seen.add(name)
		if (
			not account
			or account.get("company") != settings.get("company")
			or account.get("root_type") != "Expense"
		):
			raise ValueError(
				f"La cuenta {name} debe ser una cuenta de gastos de esta empresa, de mayor o de detalle."
			)
		if (row.get("behavior") or "") not in BEHAVIORS:
			raise ValueError(f"Clasificación de gastos inválida: {name}")
		if account.get("account_type") == "Cost of Goods Sold" and row.get("behavior") not in (
			None,
			"",
			"Costo de ventas",
		):
			raise ValueError(
				f"La cuenta {name} es costo de ventas y ya se incluye en el costo comercial; no debe contarse como otro gasto."
			)
	seen = set()
	for row in settings.get("targets", []):
		key = row.get("indicator")
		if key not in TARGET_KEYS or key in seen:
			raise ValueError("Cada meta debe corresponder a un indicador distinto.")
		seen.add(key)
		metric_key = TARGET_KEYS[key]
		target, warning = number(row.get("target")), number(row.get("warning"))
		if not all(math.isfinite(v) for v in (target, warning)):
			raise ValueError("Las metas deben ser números finitos.")
		lower = metric_key in LOWER_TARGETS
		if (not lower and target < warning) or (lower and target > warning):
			raise ValueError(f"El límite moderado de {key} debe ser menos exigente que la meta saludable.")
		if metric_key not in SIGNED_TARGETS and min(target, warning) < 0:
			raise ValueError(f"Las metas de {key} no pueden ser negativas.")
		if metric_key in BOUNDED_PERCENT_TARGETS and max(target, warning) > 100:
			raise ValueError(f"Las metas de {key} no pueden superar 100%.")
		if metric_key == "dio" and not 0 <= number(row.get("healthy_min")) <= target:
			raise ValueError("El mínimo saludable de DIO debe estar entre cero y la meta máxima.")


def evaluate_target(key, value, target_row, basis, unit):
	scale = basis["period_days"] / 365 if key in ANNUAL_TARGETS and basis["mode"] != "annualized" else 1
	target, warning = number(target_row.get("target")) * scale, number(target_row.get("warning")) * scale
	lower = key in LOWER_TARGETS
	minimum = number(target_row.get("healthy_min"))
	healthy = value <= target + 1e-9 if lower else value >= target - 1e-9
	if key == "dio":
		healthy = healthy and value >= minimum
	moderate = value <= warning + 1e-9 if lower else value >= warning - 1e-9
	status = "good" if healthy else "warning" if moderate else "danger"
	precision = 1 if unit == "%" else 0 if unit in ("días", "moneda") else 2
	meta = (
		f"{minimum:.0f}–{target:.0f} días"
		if key == "dio"
		else f"{'≤' if lower else '≥'} {target:,.{precision}f} {unit}"
	)
	if key in ANNUAL_TARGETS:
		meta += " anual" if basis["mode"] == "annualized" else f" en {basis['period_days']} días"
	return status, f"Meta {meta}; límite moderado {warning:,.{precision}f} {unit}"


def apply_existing_targets(indicators, settings, basis, upt, symbol):
	targets = {
		TARGET_KEYS[r["indicator"]]: r
		for r in settings.get("targets", [])
		if r.get("indicator") in TARGET_KEYS
	}
	units = {
		"gross_margin": "%",
		"net_margin": "%",
		"operating_expenses_pct": "%",
		"roa": "%",
		"roe": "%",
		"current_ratio": "x",
		"quick_ratio": "x",
		"working_capital": "moneda",
		"debt_ratio": "%",
		"inventory_turnover": "x",
		"dio": "días",
		"avg_ticket": "moneda",
		"upt": "u/t",
		"cash_coverage": "x",
	}
	for row in indicators:
		key = row.get("key")
		keys = ("avg_ticket", "upt") if key == "avg_ticket" else (key,)
		configured = [k for k in keys if k in targets]
		if not configured:
			continue
		if row["value"] is None or row["value_formatted"] in ("N/A", "Sin Deuda", "Sin CxP"):
			# A missing denominator must not be compared to a numeric sentinel.
			row["reference_formatted"] = "Meta personalizada no aplicable sin base de cálculo"
			continue
		results = [
			evaluate_target(k, upt if k == "upt" else row["value"], targets[k], basis, units[k])
			for k in configured
		]
		row["status"] = max((r[0] for r in results), key={"good": 0, "warning": 1, "danger": 2}.get)
		row["status_label"] = {"good": "En meta", "warning": "Vigilancia", "danger": "Fuera de meta"}[
			row["status"]
		]
		row["reference_formatted"] = " · ".join(
			(f"{'Ticket' if k == 'avg_ticket' else 'UPT'}: " if key == "avg_ticket" else "")
			+ result[1].replace("moneda", symbol)
			for k, result in zip(configured, results, strict=True)
		)


def sales_sources(db, include_pending_pos):
	"""Only source invoices; consolidated Sales Invoices must never duplicate POS sales."""
	has_pos = db.table_exists("POS Invoice") and db.table_exists("POS Invoice Item")
	exclude = (
		""
		if not has_pos
		else """
		AND IFNULL(s.is_consolidated, 0) = 0
		AND NOT EXISTS (SELECT 1 FROM `tabPOS Invoice` p
			WHERE p.consolidated_invoice = s.name AND p.docstatus = 1)
	"""
	)
	sources = [("Sales Invoice", "Sales Invoice Item", exclude)]
	if has_pos:
		sources.append(
			(
				"POS Invoice",
				"POS Invoice Item",
				"" if include_pending_pos else "AND IFNULL(s.consolidated_invoice, '') != ''",
			)
		)
	return sources


def fetch_inventory_history(db, company, start, end, warehouse=None):
	"""Mean of daily closing stock values, weighted in SQL without materializing daily snapshots."""
	days = (as_date(end) - as_date(start)).days + 1
	return db.sql(
		f"""
		SELECT sle.item_code, sle.warehouse, i.item_group,
			SUM(sle.actual_qty) AS qty, SUM(sle.stock_value_difference) AS stock_value,
			SUM(sle.stock_value_difference * CASE WHEN sle.posting_date < %(start)s THEN 1
				ELSE 1.0 * (DATEDIFF(%(end)s, sle.posting_date) + 1) / %(days)s END) AS average_value,
			MIN(CASE WHEN sle.actual_qty > 0 THEN sle.posting_date END) AS first_receipt
		FROM `tabStock Ledger Entry` sle
		INNER JOIN `tabItem` i ON i.name = sle.item_code
		WHERE sle.company = %(company)s AND sle.is_cancelled = 0 AND sle.posting_date <= %(end)s
			{"AND sle.warehouse = %(warehouse)s" if warehouse else ""}
		GROUP BY sle.item_code, sle.warehouse, i.item_group
	""",
		{"company": company, "start": start, "end": end, "days": days, "warehouse": warehouse},
		as_dict=True,
	)


def fetch_demand(db, company, end, demand_days, warehouse=None, include_pending_pos=True):
	parts = []
	for parent, child, clause in sales_sources(db, include_pending_pos):
		parts.append(f"""
			SELECT l.item_code, l.warehouse, i.item_group, MAX(s.posting_date) AS last_sale,
				SUM(CASE WHEN s.posting_date >= %(demand_start)s THEN l.stock_qty ELSE 0 END) AS recent_qty
			FROM `tab{parent}` s INNER JOIN `tab{child}` l ON l.parent = s.name
			INNER JOIN `tabItem` i ON i.name = l.item_code AND i.is_stock_item = 1
			WHERE s.company = %(company)s AND s.docstatus = 1 AND s.is_return = 0
				AND s.posting_date <= %(end)s AND l.stock_qty > 0 {clause}
				{"AND l.warehouse = %(warehouse)s" if warehouse else ""}
			GROUP BY l.item_code, l.warehouse, i.item_group
		""")
	return db.sql(
		" UNION ALL ".join(parts),
		{
			"company": company,
			"end": end,
			"warehouse": warehouse,
			"demand_start": str(as_date(end) - timedelta(days=demand_days - 1)),
		},
		as_dict=True,
	)


def inventory_metrics(stock, activity, sales, cost_map, end, dead_days):
	"""All items count in ratios; never derive totals from the dashboard's top-15 alerts."""
	items = {}

	def item(row):
		key = (row.get("item_code"), row.get("warehouse") or "Sin almacén")
		if key not in items:
			items[key] = dict(
				item_code=key[0],
				warehouse=key[1],
				item_group=row.get("item_group") or "Sin categoría",
				qty=0,
				stock_value=0,
				average_value=0,
				recent_qty=0,
				profit=0,
				missing_cost=False,
				first_receipt=None,
				last_sale=None,
				history=False,
			)
		return items[key]

	for row in stock:
		record = item(row)
		record.update({k: number(row.get(k)) for k in ("qty", "stock_value", "average_value")})
		record.update(first_receipt=row.get("first_receipt"), history=True)
	for row in activity:
		record = item(row)
		record["recent_qty"] += number(row.get("recent_qty"))
		if row.get("last_sale"):
			record["last_sale"] = max(str(record["last_sale"] or ""), str(row["last_sale"]))
	for row in sales:
		if not row.get("is_stock_item"):
			continue
		record = item(row)
		rate = number(row.get("incoming_rate")) or number(cost_map.get(row.get("item_code")))
		qty = number(row.get("stock_qty")) or number(row.get("qty"))
		record["profit"] += number(row.get("net_amount")) - qty * rate
		record["missing_cost"] |= rate <= 0 and qty != 0

	def summarize(records):
		by_item = defaultdict(list)
		for record in records:
			by_item[record["item_code"]].append(record)
		stock_value = dead_value = average = profit = 0.0
		demand_count = stockout_count = 0
		valid_history = any(r["history"] for r in records)
		# Sales costs and historical stock valuation are independent inputs. Negative
		# stock invalidates GMROI, but must not block break-even for costed sales.
		valid_cost = not any(r["missing_cost"] for r in records)
		valid_valuation = not any(r["average_value"] < -0.01 for r in records)
		for group in by_item.values():
			qty = sum(r["qty"] for r in group)
			value = sum(max(0, r["stock_value"]) for r in group)
			stock_value += value
			average += sum(r["average_value"] for r in group)
			profit += sum(r["profit"] for r in group)
			if sum(r["recent_qty"] for r in group) > 0:
				demand_count += 1
				stockout_count += qty <= 0
			last_sale = max((str(r["last_sale"]) for r in group if r["last_sale"]), default=None)
			first_receipt = min((str(r["first_receipt"]) for r in group if r["first_receipt"]), default=None)
			inactive_since = last_sale or first_receipt
			if qty > 0 and inactive_since and (as_date(end) - as_date(inactive_since)).days >= dead_days:
				dead_value += value
		return dict(
			average_inventory=average if valid_history else None,
			cost_complete=valid_cost,
			inventory_valuation_valid=valid_valuation,
			stock_value=stock_value,
			dead_value=dead_value,
			demand_count=demand_count,
			stockout_count=stockout_count,
			gmroi=profit / average if valid_history and valid_cost and valid_valuation and average > 0 else None,
			gmroi_note=(
				"Revisar inventario histórico con valoración promedio negativa por artículo y almacén"
				if not valid_valuation
				else "Requiere costo de los artículos vendidos"
				if not valid_cost
				else "Requiere historial e inventario promedio positivo"
				if not valid_history or average <= 0
				else "Inventario histórico; costo comercial con valoración de respaldo cuando sea necesaria"
			),
			dead_stock_pct=dead_value / stock_value * 100 if stock_value > 0 else None,
			stockout_pct=stockout_count / demand_count * 100 if demand_count else None,
		)

	result = summarize(list(items.values()))
	result["details"] = []
	for field, label in (("item_group", "Categoría"), ("warehouse", "Almacén")):
		groups = defaultdict(list)
		for record in items.values():
			groups[record[field]].append(record)
		for name, records in sorted(groups.items()):
			result["details"].append(dict(group=label, name=name, **summarize(records)))
	return result


def sales_quality(sales):
	"""Net-of-tax merchandise discounts; distributed invoice discount is included exactly once."""
	gross_sales = returned = discounts = 0.0
	unknown_discount_basis = False
	for row in sales:
		net = number(row.get("net_amount"))
		if row.get("is_return") or net < 0:
			returned += abs(net)
			continue
		gross_sales += net
		additional = max(
			0, number(row.get("distributed_discount_amount")) * number(row.get("conversion_rate"))
		)
		line_discount = max(
			0,
			number(row.get("discount_amount")) * number(row.get("qty")) * number(row.get("conversion_rate")),
		)
		base_amount = number(row.get("base_amount"))
		if line_discount and base_amount <= 0:
			# A free line with included taxes cannot be reconstructed safely from its zero net amount.
			unknown_discount_basis = True
		elif base_amount > 0:
			line_discount *= (net + additional) / base_amount
		discounts += line_discount + additional
	return dict(
		discount_pct=discounts / (gross_sales + discounts) * 100
		if gross_sales + discounts > 0 and not unknown_discount_basis
		else None,
		return_pct=returned / gross_sales * 100 if gross_sales > 0 else None,
		discounts=discounts,
		returned=returned,
		gross_sales=gross_sales,
		discount_note="Revisar artículos gratuitos: no se puede reconstruir su base sin impuestos"
		if unknown_discount_basis
		else "Descuentos comerciales, sin impuestos; excluye descuentos financieros y devoluciones",
	)


def fetch_expense_accounts(db, company):
	# Include disabled accounts: they can still have historical movements to classify.
	return db.sql(
		"""
		SELECT name, company, root_type, account_type, is_group, parent_account
		FROM `tabAccount` WHERE company = %(company)s AND root_type = 'Expense'
		""",
		{"company": company},
		as_dict=True,
	)


def resolve_expense_classifications(settings, accounts):
	"""Resolve each leaf once, using its nearest nonempty rule in the actual account tree."""
	account_map = {
		row["name"]: row
		for row in accounts
		if row.get("company") == settings.get("company") and row.get("root_type") == "Expense"
	}
	rules = {row["account"]: row.get("behavior") for row in settings.get("expenses", [])}
	resolved = {}
	for name, account in account_map.items():
		if account.get("is_group"):
			continue
		# A broad fixed/variable rule must never charge commercial COGS a second time.
		if account.get("account_type") == "Cost of Goods Sold":
			resolved[name] = "Costo de ventas"
			continue
		current, visited = name, set()
		while current in account_map and current not in visited:
			visited.add(current)
			if rules.get(current):
				resolved[name] = rules[current]
				break
			current = account_map[current].get("parent_account")
	return resolved


def fetch_accounting(db, company, start, end):
	days = (as_date(end) - as_date(start)).days + 1
	return db.sql(
		"""
		SELECT a.name AS account, a.root_type, a.account_type,
			SUM(CASE WHEN gl.posting_date >= %(start)s AND gl.voucher_type != 'Period Closing Voucher'
				THEN gl.debit - gl.credit ELSE 0 END) AS period_amount,
			SUM((gl.debit - gl.credit) * CASE WHEN gl.posting_date < %(start)s THEN 1
				ELSE 1.0 * (DATEDIFF(%(end)s, gl.posting_date) + 1) / %(days)s END) AS average_balance,
			SUM(CASE WHEN gl.posting_date >= %(start)s AND (
				(a.account_type = 'Receivable' AND gl.voucher_type = 'Sales Invoice') OR
				(a.account_type = 'Payable' AND gl.voucher_type = 'Purchase Invoice'))
				THEN gl.debit - gl.credit ELSE 0 END) AS credit_origin
		FROM `tabGL Entry` gl INNER JOIN `tabAccount` a ON a.name = gl.account
		WHERE gl.company = %(company)s AND gl.is_cancelled = 0 AND gl.posting_date <= %(end)s
			AND a.company = %(company)s AND a.is_group = 0
			AND (a.root_type = 'Expense' OR a.account_type IN ('Receivable', 'Payable', 'Stock'))
		GROUP BY a.name, a.root_type, a.account_type
	""",
		{"company": company, "start": start, "end": end, "days": days},
		as_dict=True,
	)


def accounting_metrics(
	rows, settings, net_sales, commercial_cogs, period_days, warehouse=None, cost_complete=True, accounts=None
):
	classification = (
		resolve_expense_classifications(settings, accounts)
		if accounts is not None
		else {r["account"]: r.get("behavior") for r in settings.get("expenses", [])}
	)
	fixed = variable = cogs = ar = ap = credit_sales = credit_purchases = average_stock = 0.0
	unclassified = []
	for row in rows:
		type_ = row.get("account_type")
		amount = number(row.get("period_amount"))
		if type_ == "Receivable":
			ar += number(row.get("average_balance"))
			credit_sales += number(row.get("credit_origin"))
		elif type_ == "Payable":
			ap -= number(row.get("average_balance"))
			credit_purchases -= number(row.get("credit_origin"))
		elif type_ == "Stock":
			average_stock += number(row.get("average_balance"))
		if row.get("root_type") != "Expense":
			continue
		behavior = "Costo de ventas" if type_ == "Cost of Goods Sold" else classification.get(row["account"])
		if behavior == "Costo de ventas":
			cogs += amount
		elif behavior == "Fijo":
			fixed += amount
		elif behavior == "Variable":
			variable += amount
		elif behavior != "Excluido" and abs(amount) > 0.005:
			unclassified.append(row["account"])

	# Break-even uses the same commercial COGS as the dashboard; classified COGS is not added again.
	contribution = (net_sales - commercial_cogs - variable) / net_sales if net_sales > 0 else None
	break_even = None
	if warehouse:
		note = "Seleccione todos los almacenes: los gastos se contabilizan por empresa"
	elif not settings:
		note = "Pendiente de configurar gastos por empresa"
	elif unclassified:
		note = "Pendiente de clasificar: " + ", ".join(sorted(unclassified)[:5])
		if len(unclassified) > 5:
			note += f" y {len(unclassified) - 5} cuentas más"
	elif not cost_complete:
		note = "Requiere costo de los artículos vendidos"
	elif contribution is None or contribution <= 0:
		note = "Requiere ventas y margen de contribución positivos"
	elif fixed < 0 or variable < 0:
		note = "Revisar gastos netos negativos en el período"
	else:
		break_even = fixed / contribution
		note = f"Empresa completa · contribución {contribution * 100:.1f}% · gastos del período"

	# CCC uses only posted company accounting, including taxes in AR/AP and their matching flows.
	def days_for(balance, flow):
		if balance < -0.005 or flow < -0.005:
			return None
		if flow > 0:
			return max(0, balance) / flow * period_days
		return 0.0 if abs(balance) < 0.005 else None

	dio = (
		days_for(average_stock, cogs)
		if any(r.get("account_type") == "Stock" for r in rows) and cogs > 0
		else None
	)
	dso, dpo = days_for(ar, credit_sales), days_for(ap, credit_purchases)
	cycle = dio + dso - dpo if not warehouse and all(v is not None for v in (dio, dso, dpo)) else None
	cycle_note = (
		f"DIO {dio:.0f} + DSO {dso:.0f} − DPO {dpo:.0f} días · contabilidad de la empresa; excluye POS sin cierre"
		if cycle is not None
		else "Seleccione todos los almacenes"
		if warehouse
		else "Requiere inventario y costo contabilizados, y flujos de crédito compatibles con CxC/CxP"
	)
	return dict(
		break_even=break_even,
		break_even_note=note,
		fixed_expenses=fixed,
		variable_expenses=variable,
		contribution_pct=contribution * 100 if contribution is not None else None,
		net_sales=net_sales,
		cash_cycle=cycle,
		cycle_note=cycle_note,
		dio=dio,
		dso=dso,
		dpo=dpo,
		unclassified_accounts=sorted(unclassified),
	)


def build_retail_indicators(metrics, basis, symbol):
	"""Single presentation contract for the screen and PDF; no invented sector benchmarks."""
	factor = basis["factor"]
	monthly_factor = 30 / basis["period_days"]
	targets = {
		TARGET_KEYS[r["indicator"]]: r
		for r in metrics.get("settings", {}).get("targets", [])
		if r.get("indicator") in TARGET_KEYS
	}
	settings = metrics.get("settings", {})
	dead_days, demand_days = settings.get("dead_stock_days", 60), settings.get("demand_days", 30)

	def money(value):
		return f"{symbol} {value:,.0f}"

	definitions = [
		(
			"gmroi",
			"Rentabilidad",
			"GMROI · " + basis["label"],
			"Utilidad bruta de artículos de stock / Inventario promedio diario al costo"
			+ (" × 365 / Días" if factor != 1 else ""),
			"x",
			metrics.get(
				"gmroi_note",
				"Inventario histórico; costo comercial con valoración de respaldo cuando sea necesaria",
			),
		),
		(
			"dead_stock_pct",
			"Inventario y Operación",
			"Capital estancado (%)",
			f"Stock al costo sin ventas ≥ {dead_days} días / Stock al costo al corte",
			"%",
			f"{money(metrics.get('dead_value', 0))} inmovilizados; productos nuevos sin ventas esperan {dead_days} días",
		),
		(
			"stockout_pct",
			"Inventario y Operación",
			"Agotados con demanda (%)",
			f"Artículos sin stock / Artículos con ventas en {demand_days} días",
			"%",
			f"{metrics.get('stockout_count', 0)} de {metrics.get('demand_count', 0)} artículos; existencias registradas al corte",
		),
		(
			"break_even",
			"Rentabilidad",
			"Punto de equilibrio mensual",
			"(Gastos fijos del período × 30 / Días) / "
			"[1 − (Costo comercial + Otros gastos variables) / Ventas netas]",
			"money",
			metrics.get("break_even_note", "Pendiente de configurar"),
		),
		(
			"discount_pct",
			"Rentabilidad",
			"Descuentos (%)",
			"Descuentos / Venta de artículos antes de descuentos (sin devoluciones)",
			"%",
			metrics.get("discount_note", "Sin ventas"),
		),
		(
			"return_pct",
			"Rentabilidad",
			"Devoluciones (%)",
			"Devoluciones del período / Ventas antes de devoluciones, sin impuestos",
			"%",
			"Incluye devoluciones de ventas realizadas en períodos anteriores",
		),
		(
			"cash_cycle",
			"Liquidez y Solvencia",
			"Ciclo de conversión de efectivo",
			"DIO + DSO − DPO; saldos promedio diarios / flujos contables diarios",
			"days",
			metrics.get("cycle_note", "Sin datos contables"),
		),
	]
	result = []
	for key, category, name, formula, unit, note in definitions:
		value = metrics.get(key)
		if key == "gmroi" and value is not None:
			value *= factor
		status, label = "neutral", "Sin meta" if value is not None else "No evaluable"
		if value is not None and key in targets:
			status, reference = evaluate_target(
				key, value, targets[key], basis, "días" if unit == "days" else unit
			)
			label = {"good": "En meta", "warning": "Vigilancia", "danger": "Fuera de meta"}[status]
			note = reference + ". " + note
		if key == "break_even" and value is not None:
			# Both amounts use the same 30-day basis, independently of annualized mode.
			value *= monthly_factor
			monthly_sales = metrics["net_sales"] * monthly_factor
			note = (
				f"Estimación a 30 días; ritmo de ventas {money(monthly_sales)}/mes. " + note
			)
			status = "good" if monthly_sales >= value else "danger"
			label = "Ritmo suficiente" if status == "good" else "Ritmo insuficiente"
			if value > 0 and "break_even_coverage" in targets:
				coverage = monthly_sales / value * 100
				status, reference = evaluate_target(
					"break_even_coverage", coverage, targets["break_even_coverage"], basis, "%"
				)
				label = {"good": "En meta", "warning": "Vigilancia", "danger": "Fuera de meta"}[status]
				note = f"Cobertura {coverage:.1f}%. {reference}. " + note
		text = (
			"N/A"
			if value is None
			else (
				money(value)
				if unit == "money"
				else f"{value:.1f}%"
				if unit == "%"
				else f"{value:.2f}x"
				if unit == "x"
				else f"{value:,.0f} días"
			)
		)
		if key == "break_even" and value is not None:
			text += " / mes"
		result.append(
			dict(
				key=key,
				category=category,
				name=name,
				formula=formula,
				value=value,
				value_formatted=text,
				reference_formatted=note,
				status=status,
				status_label=label,
			)
		)
	return result


def inventory_detail_view(metrics, basis, symbol):
	rows = []
	for row in metrics.get("details", []):
		rows.append(
			dict(
				group=row["group"],
				name=row["name"],
				average=f"{symbol} {row['average_inventory']:,.0f}"
				if row["average_inventory"] is not None
				else "N/A",
				gmroi=f"{row['gmroi'] * basis['factor']:.2f}x" if row["gmroi"] is not None else "N/A",
				dead_value=f"{symbol} {row['dead_value']:,.0f}",
				dead_pct=f"{row['dead_stock_pct']:.1f}%" if row["dead_stock_pct"] is not None else "N/A",
				stockout=f"{row['stockout_count']} / {row['demand_count']}",
				stockout_pct=f"{row['stockout_pct']:.1f}%" if row["stockout_pct"] is not None else "N/A",
			)
		)
	return rows
