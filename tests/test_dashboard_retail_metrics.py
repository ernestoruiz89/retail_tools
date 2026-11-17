"""Verify the new indicators against ledger and invoice data, without a Frappe server."""

import copy
import json
import re
import sqlite3
import unittest
from datetime import date
from pathlib import Path

from test_dashboard_indicators import indicator_inputs
from test_dashboard_pdf import _load_dashboard_module

from retail_tools.retail_tools.page.store_dashboard import retail_metrics as metrics


class Row(dict):
	__getattr__ = dict.get


class Database:
	def __init__(self):
		self.connection = sqlite3.connect(":memory:")
		self.connection.row_factory = sqlite3.Row
		self.connection.create_function(
			"DATEDIFF", 2, lambda end, start: (date.fromisoformat(end) - date.fromisoformat(start)).days
		)
		self.connection.executescript("""
			CREATE TABLE `tabItem` (name TEXT, item_name TEXT, item_group TEXT, is_stock_item INTEGER);
			CREATE TABLE `tabStock Ledger Entry` (company TEXT, item_code TEXT, warehouse TEXT, posting_date TEXT,
				actual_qty REAL, stock_value_difference REAL, is_cancelled INTEGER DEFAULT 0);
			CREATE TABLE `tabAccount` (name TEXT, root_type TEXT, account_type TEXT,
				company TEXT DEFAULT 'A', is_group INTEGER DEFAULT 0, parent_account TEXT, disabled INTEGER DEFAULT 0);
			CREATE TABLE `tabGL Entry` (account TEXT, company TEXT, posting_date TEXT, debit REAL DEFAULT 0,
				credit REAL DEFAULT 0, voucher_type TEXT, is_cancelled INTEGER DEFAULT 0);
		""")
		for parent, child in (("Sales Invoice", "Sales Invoice Item"), ("POS Invoice", "POS Invoice Item")):
			self.connection.execute(f"""CREATE TABLE `tab{parent}` (name TEXT, company TEXT DEFAULT 'A', posting_date TEXT DEFAULT '2026-11-10',
				posting_time TEXT, customer TEXT, docstatus INTEGER DEFAULT 1, is_return INTEGER DEFAULT 0,
				is_pos INTEGER DEFAULT 0, is_consolidated INTEGER DEFAULT 0, consolidated_invoice TEXT, conversion_rate REAL DEFAULT 1)""")
			self.connection.execute(f"""CREATE TABLE `tab{child}` (parent TEXT, item_code TEXT DEFAULT 'X', item_name TEXT,
				item_group TEXT, warehouse TEXT DEFAULT 'W1', qty REAL DEFAULT 1, stock_qty REAL DEFAULT 1,
				base_net_amount REAL DEFAULT 90, base_amount REAL DEFAULT 90, discount_amount REAL DEFAULT 10,
				distributed_discount_amount REAL DEFAULT 0, incoming_rate REAL DEFAULT 30)""")
		self.insert("Item", name="X", item_group="Ropa", is_stock_item=1)

	def insert(self, table, **values):
		self.connection.execute(
			f"INSERT INTO `tab{table}` ({', '.join(values)}) VALUES ({','.join('?' for _ in values)})",
			tuple(values.values()),
		)

	def sql(self, query, params=None, as_dict=False):
		query = re.sub(r"%\((\w+)\)s", r":\1", query)
		return [Row(row) for row in self.connection.execute(query, params or {}).fetchall()]

	def table_exists(self, doctype):
		return (
			self.connection.execute(
				"SELECT name FROM sqlite_master WHERE name = ?", ("tab" + doctype,)
			).fetchone()
			is not None
		)


def sample_metrics():
	return dict(
		gmroi=0.3,
		dead_stock_pct=12.5,
		stockout_pct=10,
		break_even=5000,
		discount_pct=5,
		return_pct=2,
		cash_cycle=20,
		net_sales=10000,
		dead_value=1500,
		stockout_count=2,
		demand_count=20,
		break_even_note="Empresa completa · gastos clasificados",
		cycle_note="DIO 30 + DSO 10 - DPO 20 días",
		discount_note="Descuentos comerciales sin impuestos",
		settings={
			"dead_stock_days": 60,
			"demand_days": 30,
			"targets": [
				{"indicator": "GMROI", "target": 3, "warning": 1},
				{"indicator": "Capital estancado (%)", "target": 10, "warning": 20},
			],
		},
		details=[
			dict(
				group="Categoría",
				name="Ropa",
				average_inventory=12000,
				gmroi=0.3,
				dead_value=1500,
				dead_stock_pct=12.5,
				stockout_count=2,
				demand_count=20,
				stockout_pct=10,
			)
		],
	)


class RetailLedgerTest(unittest.TestCase):
	def setUp(self):
		self.db = Database()
		self.addCleanup(self.db.connection.close)

	def test_inventory_average_uses_every_daily_closing_balance_and_scope(self):
		for company, wh, day, value, cancelled in [
			("A", "W1", "2026-10-01", 100, 0),
			("A", "W1", "2026-11-16", 100, 0),
			("A", "W1", "2026-11-20", -50, 1),
			("B", "W1", "2026-11-01", 999, 0),
			("A", "W2", "2026-10-01", 500, 0),
			("A", "W1", "2026-12-01", 999, 0),
		]:
			self.db.insert(
				"Stock Ledger Entry",
				company=company,
				item_code="X",
				warehouse=wh,
				posting_date=day,
				stock_value_difference=value,
				actual_qty=value / 10,
				is_cancelled=cancelled,
			)
		rows = metrics.fetch_inventory_history(self.db, "A", "2026-11-01", "2026-11-30", "W1")
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(rows[0]["average_value"], 150)
		self.assertEqual(rows[0]["stock_value"], 200)
		self.assertEqual(rows[0]["qty"], 20)
		all_rows = metrics.fetch_inventory_history(self.db, "A", "2026-11-01", "2026-11-30")
		self.assertEqual(sum(r["average_value"] for r in all_rows), 650)

	def test_sales_and_demand_exclude_consolidation_cancellation_and_other_scope(self):
		invoices = [
			("Sales Invoice", "direct", {}),
			("Sales Invoice", "consolidated", {"is_consolidated": 1}),
			("Sales Invoice", "linked", {}),
			("POS Invoice", "pos", {"consolidated_invoice": "consolidated"}),
			("POS Invoice", "linked-pos", {"consolidated_invoice": "linked"}),
			("POS Invoice", "pending", {}),
			("POS Invoice", "cancelled", {"docstatus": 2}),
			("Sales Invoice", "other-company", {"company": "B"}),
			("Sales Invoice", "refund", {"is_return": 1}),
			("Sales Invoice", "old", {"posting_date": "2026-01-01"}),
		]
		for parent, name, changes in invoices:
			self.db.insert(parent, name=name, **changes)
			self.db.insert(parent + " Item", parent=name, stock_qty=-1 if name == "refund" else 1)
		self.db.insert("Sales Invoice", name="other-warehouse")
		self.db.insert("Sales Invoice Item", parent="other-warehouse", warehouse="W2")
		dashboard = _load_dashboard_module()
		dashboard.frappe.db = self.db
		for include_pending, expected in ((True, 4), (False, 3)):
			activity = metrics.fetch_demand(self.db, "A", "2026-11-30", 30, "W1", include_pending)
			self.assertEqual(sum(r["recent_qty"] for r in activity), expected)
			rows = dashboard._fetch_sales_line_rows("A", "2026-11-01", "2026-11-30", "W1", include_pending)
			positive = [r for r in rows if not r.is_return]
			self.assertEqual(len(positive), expected)
			self.assertAlmostEqual(metrics.sales_quality(positive)["discount_pct"], 10)

	def test_account_averages_credit_origins_and_expenses_have_distinct_bases(self):
		self.db.insert("Account", name="AR", root_type="Asset", account_type="Receivable")
		self.db.insert("Account", name="Rent", root_type="Expense", account_type="")
		for account, day, debit, credit, voucher, company, cancelled in [
			("AR", "2026-10-31", 100, 0, "Journal Entry", "A", 0),
			("AR", "2026-11-01", 200, 0, "Sales Invoice", "A", 0),
			("AR", "2026-11-16", 0, 100, "Payment Entry", "A", 0),
			("AR", "2026-11-01", 1000, 0, "Sales Invoice", "A", 1),
			("AR", "2026-11-01", 1000, 0, "Sales Invoice", "B", 0),
			("Rent", "2026-11-10", 50, 0, "Journal Entry", "A", 0),
			("Rent", "2026-11-30", 0, 50, "Period Closing Voucher", "A", 0),
		]:
			self.db.insert(
				"GL Entry",
				account=account,
				company=company,
				posting_date=day,
				debit=debit,
				credit=credit,
				voucher_type=voucher,
				is_cancelled=cancelled,
			)
		rows = {r["account"]: r for r in metrics.fetch_accounting(self.db, "A", "2026-11-01", "2026-11-30")}
		self.assertEqual(rows["AR"]["average_balance"], 250)
		self.assertEqual(rows["AR"]["credit_origin"], 200)
		self.assertEqual(rows["Rent"]["period_amount"], 50)

	def test_group_rules_use_real_company_tree_and_count_each_posting_once(self):
		for name, parent, group, type_, company in [
			("Expenses", None, 1, "", "A"),
			("Admin", "Expenses", 1, "", "A"),
			("Payroll", "Admin", 1, "", "A"),
			("Rent", "Admin", 0, "", "A"),
			("Salary", "Payroll", 0, "", "A"),
			("Fees", "Admin", 0, "", "A"),
			("COGS", "Expenses", 0, "Cost of Goods Sold", "A"),
			("Excluded", "Admin", 0, "", "A"),
			("Foreign", "Admin", 0, "", "B"),
		]:
			self.db.insert(
				"Account",
				name=name,
				parent_account=parent,
				is_group=group,
				root_type="Expense",
				account_type=type_,
				company=company,
			)
		for account, amount in [
			("Rent", 1000),
			("Salary", 2000),
			("Fees", 500),
			("COGS", 6000),
			("Excluded", 80),
		]:
			self.db.insert(
				"GL Entry",
				account=account,
				company="A",
				posting_date="2026-11-10",
				debit=amount,
				voucher_type="Journal Entry",
			)
		# Historical disabled accounts still inherit. Another company's accounts never do.
		self.db.connection.execute("UPDATE `tabAccount` SET disabled = 1 WHERE name = 'Rent'")
		accounts = metrics.fetch_expense_accounts(self.db, "A")
		self.assertEqual(len(accounts), 8)
		settings = dict(
			company="A",
			expenses=[
				dict(account="Expenses", behavior="Variable"),
				dict(account="Admin", behavior="Fijo"),
				dict(account="Payroll", behavior="Variable"),
				dict(account="Salary", behavior="Fijo"),
				dict(account="Fees", behavior="Variable"),
				dict(account="Rent", behavior=""),  # Blank rows do not block inheritance.
				dict(account="Excluded", behavior="Excluido"),
			],
		)
		rows = metrics.fetch_accounting(self.db, "A", "2026-11-01", "2026-11-30")
		data = metrics.accounting_metrics(rows, settings, 10000, 6000, 30, accounts=accounts)
		self.assertEqual((data["fixed_expenses"], data["variable_expenses"]), (3000, 500))
		self.assertAlmostEqual(data["break_even"], 3000 / 0.35)
		self.assertEqual(data["unclassified_accounts"], [])
		# A new descendant is covered without adding another settings row.
		self.db.insert("Account", name="New salary", parent_account="Payroll", root_type="Expense")
		resolved = metrics.resolve_expense_classifications(
			settings, metrics.fetch_expense_accounts(self.db, "A")
		)
		self.assertEqual(resolved["New salary"], "Variable")
		self.assertEqual(resolved["COGS"], "Costo de ventas")
		self.assertNotIn("Foreign", resolved)
		self.assertNotIn("Admin", resolved)


class RetailCalculationTest(unittest.TestCase):
	def test_stockouts_count_unique_demand_items_and_dead_stock_uses_all_items(self):
		stock = [
			dict(
				item_code=f"old-{i}",
				warehouse="W1",
				item_group="Ropa",
				qty=1,
				stock_value=10,
				average_value=10,
				first_receipt="2025-01-01",
			)
			for i in range(20)
		]
		stock += [
			dict(
				item_code="new",
				warehouse="W1",
				item_group="Ropa",
				qty=1,
				stock_value=100,
				average_value=100,
				first_receipt="2026-11-15",
			)
		]
		stock += [
			dict(
				item_code="popular",
				warehouse="W2",
				item_group="Ropa",
				qty=1,
				stock_value=100,
				average_value=100,
				first_receipt="2026-10-01",
			)
		]
		activity = [
			dict(item_code=code, warehouse="W1", item_group="Ropa", last_sale="2026-11-15", recent_qty=1)
			for code in ("popular", "missing")
		]
		data = metrics.inventory_metrics(stock, activity, [], {}, "2026-11-30", 60)
		self.assertEqual(data["dead_value"], 200)  # not the top fifteen only
		self.assertEqual(data["dead_stock_pct"], 50)
		self.assertEqual(data["stockout_pct"], 50)  # W2 covers "popular" for company totals
		w1 = next(row for row in data["details"] if row["name"] == "W1")
		self.assertEqual(w1["stockout_pct"], 100)

	def test_gmroi_excludes_services_and_needs_history_and_cost(self):
		stock = [dict(item_code="X", warehouse="W1", qty=5, stock_value=100, average_value=80)]
		sales = [
			dict(item_code="X", warehouse="W1", is_stock_item=1, qty=2, net_amount=100, incoming_rate=20),
			dict(item_code="Service", is_stock_item=0, qty=1, net_amount=999),
		]
		data = metrics.inventory_metrics(stock, [], sales, {}, "2026-11-30", 60)
		self.assertEqual(data["gmroi"], 0.75)
		sales[0]["incoming_rate"] = 0
		self.assertIsNone(metrics.inventory_metrics(stock, [], sales, {}, "2026-11-30", 60)["gmroi"])
		self.assertIsNone(metrics.inventory_metrics([], [], sales, {"X": 20}, "2026-11-30", 60)["gmroi"])

	def test_negative_unsold_inventory_does_not_block_break_even_for_costed_sales(self):
		stock = [
			dict(item_code="X", warehouse="W1", qty=5, stock_value=100, average_value=100),
			dict(item_code="OLD", warehouse="W1", qty=-1, stock_value=-20, average_value=-20),
		]
		sales = [dict(item_code="X", warehouse="W1", is_stock_item=1, qty=2, net_amount=10000)]
		data = metrics.inventory_metrics(stock, [], sales, {"X": 3000}, "2026-11-30", 60)
		self.assertEqual(data["average_inventory"], 80)
		self.assertTrue(data["cost_complete"])
		self.assertFalse(data["inventory_valuation_valid"])
		self.assertIsNone(data["gmroi"])
		self.assertIn("valoración promedio negativa", data["gmroi_note"])
		rows, settings = self.accounting_fixture()
		accounting = metrics.accounting_metrics(
			rows, settings, 10000, 6000, 30, cost_complete=data["cost_complete"]
		)
		self.assertAlmostEqual(accounting["break_even"], 1000 / 0.35)
		basis = dict(factor=1, label="Del período", period_days=30)
		gmroi = next(r for r in metrics.build_retail_indicators(data, basis, "C$") if r["key"] == "gmroi")
		self.assertEqual(gmroi["reference_formatted"], data["gmroi_note"])
		self.assertEqual(gmroi["value_formatted"], "N/A")

	def test_missing_sold_item_cost_still_blocks_break_even_with_valid_inventory(self):
		stock = [dict(item_code="X", warehouse="W1", qty=5, stock_value=100, average_value=80)]
		sales = [dict(item_code="X", warehouse="W1", is_stock_item=1, qty=2, net_amount=100)]
		data = metrics.inventory_metrics(stock, [], sales, {}, "2026-11-30", 60)
		self.assertFalse(data["cost_complete"])
		self.assertTrue(data["inventory_valuation_valid"])
		self.assertIsNone(data["gmroi"])
		rows, settings = self.accounting_fixture()
		accounting = metrics.accounting_metrics(
			rows, settings, 10000, 6000, 30, cost_complete=data["cost_complete"]
		)
		self.assertIsNone(accounting["break_even"])
		self.assertEqual(accounting["break_even_note"], "Requiere costo de los artículos vendidos")

	def test_discount_handles_currency_included_tax_and_additional_discount_once(self):
		# List 115, line rate 103.5 includes 15% tax: 10% line + 10% additional => 19% net discount.
		rows = [
			dict(
				net_amount=162,
				base_amount=207,
				conversion_rate=2,
				discount_amount=11.5,
				distributed_discount_amount=9,
				qty=1,
			)
		]
		data = metrics.sales_quality(rows)
		self.assertAlmostEqual(data["discounts"], 38)
		self.assertAlmostEqual(data["discount_pct"], 19)
		rows.append(dict(is_return=1, net_amount=-81, qty=-1))
		self.assertAlmostEqual(metrics.sales_quality(rows)["return_pct"], 50)
		self.assertAlmostEqual(metrics.sales_quality(rows)["discount_pct"], 19)
		self.assertIsNone(metrics.sales_quality([dict(is_return=1, net_amount=-20)])["return_pct"])

	def test_free_discount_or_empty_sales_do_not_generate_false_zero(self):
		self.assertIsNone(
			metrics.sales_quality(
				[dict(net_amount=0, base_amount=0, discount_amount=100, conversion_rate=1, qty=1)]
			)["discount_pct"]
		)
		self.assertIsNone(metrics.sales_quality([])["discount_pct"])

	def accounting_fixture(self):
		settings = {
			"expenses": [dict(account="Rent", behavior="Fijo"), dict(account="Fees", behavior="Variable")]
		}
		rows = [
			dict(account="Rent", root_type="Expense", period_amount=1000),
			dict(account="Fees", root_type="Expense", period_amount=500),
			dict(account="COGS", root_type="Expense", account_type="Cost of Goods Sold", period_amount=6000),
			dict(account="Stock", account_type="Stock", average_balance=12000),
			dict(account="AR", account_type="Receivable", average_balance=1000, credit_origin=3000),
			dict(account="AP", account_type="Payable", average_balance=-4000, credit_origin=-6000),
		]
		return rows, settings

	def test_break_even_does_not_double_count_cogs_and_cash_cycle_uses_average_balances(self):
		rows, settings = self.accounting_fixture()
		data = metrics.accounting_metrics(rows, settings, 10000, 6000, 30)
		self.assertAlmostEqual(data["break_even"], 1000 / 0.35)
		self.assertAlmostEqual(data["contribution_pct"], 35)
		self.assertEqual((data["dio"], data["dso"], data["dpo"], data["cash_cycle"]), (60, 10, 20, 50))
		rows.append(dict(account="Unknown", root_type="Expense", period_amount=20))
		self.assertIsNone(metrics.accounting_metrics(rows, settings, 10000, 6000, 30)["break_even"])
		self.assertIsNone(metrics.accounting_metrics(rows, {}, 10000, 6000, 30)["break_even"])

	def test_accounting_scope_and_invalid_denominators_are_explicit(self):
		rows, settings = self.accounting_fixture()
		data = metrics.accounting_metrics(rows, settings, 10000, 6000, 30, "W1")
		self.assertIsNone(data["break_even"])
		self.assertIsNone(data["cash_cycle"])
		self.assertIsNone(metrics.accounting_metrics(rows, settings, 6000, 6000, 30)["break_even"])
		self.assertIsNone(
			metrics.accounting_metrics(rows, settings, 10000, 6000, 30, cost_complete=False)["break_even"]
		)
		rows[-2]["credit_origin"] = 0
		self.assertIsNone(metrics.accounting_metrics(rows, settings, 10000, 6000, 30)["cash_cycle"])
		rows[-2]["average_balance"] = 0
		self.assertEqual(metrics.accounting_metrics(rows, settings, 10000, 6000, 30)["dso"], 0)

	def test_all_seven_rows_and_detail_share_mode_but_only_gmroi_scales(self):
		dashboard = _load_dashboard_module()
		dashboard.frappe.db.get_value = lambda *args: "C$"
		inputs = indicator_inputs()
		inputs["retail_metrics"] = sample_metrics()
		period, annual = [
			dashboard._build_indicator_view(mode, **inputs) for mode in ("period", "annualized")
		]
		self.assertEqual(len(period["indicators"]), 20)
		for a, b in zip(period["indicators"][13:], annual["indicators"][13:], strict=True):
			if a["key"] == "gmroi":
				self.assertAlmostEqual(b["value"], a["value"] * 365 / 30)
				self.assertEqual(a["status"], b["status"])
			else:
				self.assertEqual(a, b)
		self.assertEqual(annual["inventory_details"][0]["gmroi"], "3.65x")
		self.assertEqual(period["inventory_details"][0]["gmroi"], "0.30x")
		self.assertEqual(period["indicators"][14]["status"], "warning")
		self.assertEqual(period["indicators"][15]["status"], "neutral")

	def test_break_even_projects_short_and_long_periods_to_thirty_days_in_both_modes(self):
		dashboard = _load_dashboard_module()
		dashboard.frappe.db.get_value = lambda *args: "C$"
		for days in (1, 7, 17, 28, 30, 31, 365, 366, 730):
			with self.subTest(days=days):
				rows, settings = self.accounting_fixture()
				for row in rows:
					row["period_amount"] = row.get("period_amount", 0) * days / 30
				inputs = indicator_inputs(days)
				inputs["retail_metrics"] = metrics.accounting_metrics(
					rows, settings, 10000 * days / 30, 6000 * days / 30, days
				)
				period, annual = [
					next(r for r in dashboard._build_indicator_view(mode, **inputs)["indicators"] if r["key"] == "break_even")
					for mode in ("period", "annualized")
				]
				self.assertAlmostEqual(period["value"], 1000 / 0.35)
				self.assertEqual(period["value_formatted"], "C$ 2,857 / mes")
				self.assertEqual(period["name"], "Punto de equilibrio mensual")
				self.assertIn("30 / Días", period["formula"])
				self.assertIn("ritmo de ventas C$ 10,000/mes", period["reference_formatted"])
				self.assertEqual(period["status"], "good")
				self.assertEqual(period, annual)

	def test_monthly_break_even_coverage_compares_sales_and_threshold_on_same_basis(self):
		dashboard = _load_dashboard_module()
		dashboard.frappe.db.get_value = lambda *args: "C$"
		for days in (7, 60):
			for sales, target, status in ((2500, False, "danger"), (10000, False, "good"), (10000, True, "warning")):
				with self.subTest(days=days, sales=sales, target=target):
					inputs = indicator_inputs(days)
					data = sample_metrics()
					data["net_sales"] = sales
					if target:
						data["settings"]["targets"].append(
							dict(indicator="Cobertura del punto de equilibrio (%)", target=250, warning=150)
						)
					inputs["retail_metrics"] = data
					row = next(r for r in dashboard._build_indicator_view("period", **inputs)["indicators"] if r["key"] == "break_even")
					self.assertAlmostEqual(row["value"], 5000 * 30 / days)
					self.assertEqual(row["status"], status)
					if target:
						self.assertIn("Cobertura 200.0%", row["reference_formatted"])
					self.assertEqual(data["break_even"], 5000)  # period input stays reusable

	def test_monthly_break_even_keeps_missing_and_zero_distinct(self):
		dashboard = _load_dashboard_module()
		dashboard.frappe.db.get_value = lambda *args: "C$"
		for amount, text, status in ((None, "N/A", "neutral"), (0, "C$ 0 / mes", "good")):
			inputs = indicator_inputs(17)
			inputs["retail_metrics"] = sample_metrics()
			inputs["retail_metrics"]["break_even"] = amount
			inputs["retail_metrics"]["settings"]["targets"].append(
				dict(indicator="Cobertura del punto de equilibrio (%)", target=120, warning=100)
			)
			row = next(r for r in dashboard._build_indicator_view("period", **inputs)["indicators"] if r["key"] == "break_even")
			self.assertEqual(row["value_formatted"], text)
			self.assertEqual(row["status"], status)

	def test_config_accepts_groups_but_rejects_other_company_duplicates_and_reversed_targets(self):
		settings = dict(
			company="A",
			dead_stock_days=60,
			demand_days=30,
			expenses=[dict(account="Rent", behavior="Fijo")],
			targets=[],
		)
		accounts = {"Rent": dict(company="A", root_type="Expense", is_group=0)}
		metrics.validate_settings(settings, accounts)
		metrics.validate_settings(settings, {"Rent": {**accounts["Rent"], "is_group": 1}})
		for change in ({"company": "B"}, {"root_type": "Asset"}):
			with self.assertRaises(ValueError):
				metrics.validate_settings(settings, {"Rent": {**accounts["Rent"], **change}})
		invalid = copy.deepcopy(settings)
		invalid["expenses"] *= 2
		with self.assertRaises(ValueError):
			metrics.validate_settings(invalid, accounts)
		for target in (
			dict(indicator="GMROI", target=1, warning=3),
			dict(indicator="Descuentos (%)", target=20, warning=10),
		):
			with self.assertRaises(ValueError):
				metrics.validate_settings({**settings, "targets": [target]}, accounts)

	def test_inheritance_does_not_cross_companies_use_prefixes_or_loop_on_broken_trees(self):
		settings = dict(company="A", expenses=[dict(account="54", behavior="Fijo")])
		accounts = [
			dict(name="54", company="B", root_type="Expense", is_group=1),
			dict(name="Foreign parent", parent_account="54", company="A", root_type="Expense"),
			dict(name="5401", company="A", root_type="Expense"),
			dict(name="Cycle", parent_account="Cycle group", company="A", root_type="Expense"),
			dict(name="Cycle group", parent_account="Cycle", company="A", root_type="Expense", is_group=1),
		]
		self.assertEqual(metrics.resolve_expense_classifications(settings, accounts), {})
		rows = [dict(account="5401", root_type="Expense", period_amount=10)]
		data = metrics.accounting_metrics(rows, settings, 100, 50, 30, accounts=accounts)
		self.assertEqual(data["unclassified_accounts"], ["5401"])
		self.assertIsNone(data["break_even"])

	def test_direct_cogs_cannot_be_classified_as_another_expense(self):
		settings = dict(
			company="A", dead_stock_days=60, demand_days=30, expenses=[dict(account="Cost", behavior="Fijo")]
		)
		accounts = {"Cost": dict(company="A", root_type="Expense", account_type="Cost of Goods Sold")}
		with self.assertRaises(ValueError):
			metrics.validate_settings(settings, accounts)

	def test_custom_targets_apply_to_all_previous_indicators_and_dupont(self):
		dashboard = _load_dashboard_module()
		dashboard.frappe.db.get_value = lambda *args: "C$"
		inputs = indicator_inputs()
		inputs["retail_metrics"] = sample_metrics()
		values = [
			("Margen bruto (%)", 50, 45),
			("Margen neto (%)", 40, 35),
			("Peso de gastos operativos (%)", 5, 8),
			("ROA anual (%)", 50, 40),
			("ROE anual (%)", 90, 80),
			("Razón corriente (veces)", 1, 0.8),
			("Prueba ácida (veces)", 0.5, 0.3),
			("Capital de trabajo (moneda empresa)", 0, -10000),
			("Endeudamiento (%)", 30, 40),
			("Rotación de inventario anual (veces)", 8, 7),
			("Días de inventario (DIO)", 30, 40),
			("Ticket promedio (moneda empresa)", 200, 150),
			("Unidades por ticket (UPT)", 3, 2.5),
			("Cobertura de caja sobre CxP (veces)", 3, 2.5),
		]
		settings = inputs["retail_metrics"]["settings"]
		settings["targets"] = [
			dict(indicator=name, target=target, warning=warning, healthy_min=10)
			for name, target, warning in values
		]
		metrics.validate_settings(settings, {})
		for mode in ("period", "annualized"):
			view = dashboard._build_indicator_view(mode, **inputs)
			for row in view["indicators"][:13]:
				self.assertEqual(row["status"], "danger", row["key"])
			self.assertEqual(view["dupont"]["status"], "danger")
			roe = next(row for row in view["indicators"] if row["key"] == "roe")
			self.assertEqual(view["dupont"]["reference_formatted"], roe["reference_formatted"])

	def test_upt_and_ticket_use_worst_configured_target_and_dio_uses_interval(self):
		basis = {"mode": "period", "period_days": 30}
		self.assertEqual(
			metrics.evaluate_target("dio", 5, dict(target=60, warning=90, healthy_min=10), basis, "días")[0],
			"warning",
		)
		self.assertEqual(
			metrics.evaluate_target("dio", 30, dict(target=60, warning=90, healthy_min=10), basis, "días")[0],
			"good",
		)
		rows = [dict(key="avg_ticket", value=100, value_formatted="100 (2 u/t)")]
		settings = {
			"targets": [
				dict(indicator="Ticket promedio (moneda empresa)", target=90, warning=70),
				dict(indicator="Unidades por ticket (UPT)", target=3, warning=2.5),
			]
		}
		metrics.apply_existing_targets(rows, settings, basis, 2, "C$")
		self.assertEqual(rows[0]["status"], "danger")
		self.assertIn("UPT", rows[0]["reference_formatted"])
		self.assertIn("Ticket", rows[0]["reference_formatted"])

	def test_unconfigured_targets_preserve_existing_rules_and_missing_denominators(self):
		dashboard = _load_dashboard_module()
		dashboard.frappe.db.get_value = lambda *args: "C$"
		inputs = indicator_inputs()
		old = dashboard._build_indicator_view("annualized", **inputs)
		inputs["retail_metrics"] = {"settings": {}}
		new = dashboard._build_indicator_view("annualized", **inputs)
		self.assertEqual(old["indicators"], new["indicators"][:13])
		inputs["financials"]["balance_sheet"]["total_equity"] = 0
		inputs["retail_metrics"]["settings"]["targets"] = [
			dict(indicator="ROE anual (%)", target=90, warning=80)
		]
		missing = dashboard._build_indicator_view("annualized", **inputs)
		self.assertIsNone(missing["dupont"]["roe"])
		self.assertEqual(missing["dupont"]["status"], "neutral")

	def test_doctype_json_has_only_new_standard_permissions_and_child_tables(self):
		root = Path(__file__).resolve().parents[1] / "retail_tools/retail_tools/doctype"
		settings = json.loads(
			(root / "retail_indicator_settings/retail_indicator_settings.json").read_text(encoding="utf-8")
		)
		self.assertEqual(settings["autoname"], "field:company")
		self.assertNotIn("Guest", [row["role"] for row in settings["permissions"]])
		for field in settings["fields"]:
			if field["fieldtype"] == "Table":
				name = field["options"].lower().replace(" ", "_")
				child = json.loads((root / name / f"{name}.json").read_text(encoding="utf-8"))
				self.assertEqual(child["istable"], 1)
				if name == "retail_indicator_target":
					options = next(f["options"] for f in child["fields"] if f["fieldname"] == "indicator")
					self.assertEqual(set(options.splitlines()), set(metrics.TARGET_KEYS))


if __name__ == "__main__":
	unittest.main()
