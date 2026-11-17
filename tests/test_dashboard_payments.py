"""Exercise payment queries against the shared ERPNext invoice payment schema."""

import re
import sqlite3
import unittest
from types import SimpleNamespace

from test_dashboard_pdf import _load_dashboard_module


class DashboardPaymentsTest(unittest.TestCase):
	def setUp(self):
		self.dashboard = _load_dashboard_module()
		self.db = sqlite3.connect(":memory:")
		self.addCleanup(self.db.close)
		self.db.row_factory = sqlite3.Row
		self.db.executescript("""
			CREATE TABLE `tabSales Invoice` (
				name TEXT PRIMARY KEY, company TEXT, posting_date TEXT,
				docstatus INTEGER, is_consolidated INTEGER DEFAULT 0,
				outstanding_amount REAL DEFAULT 0
			);
			CREATE TABLE `tabPOS Invoice` (
				name TEXT PRIMARY KEY, company TEXT, posting_date TEXT,
				docstatus INTEGER, consolidated_invoice TEXT DEFAULT ''
			);
			CREATE TABLE `tabSales Invoice Payment` (
				parent TEXT, parenttype TEXT, parentfield TEXT,
				mode_of_payment TEXT, base_amount REAL, amount REAL
			);
			CREATE TABLE `tabSales Invoice Item` (parent TEXT, warehouse TEXT);
			CREATE TABLE `tabPOS Invoice Item` (parent TEXT, warehouse TEXT);
			CREATE TABLE `tabPayment Entry` (
				company TEXT, posting_date TEXT, docstatus INTEGER,
				payment_type TEXT, mode_of_payment TEXT,
				base_paid_amount REAL, paid_amount REAL
			);
		""")
		self.dashboard.frappe.db = SimpleNamespace(
			table_exists=lambda name: self.db.execute(
				"SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (f"tab{name}",)
			).fetchone() is not None,
			sql=self._sql,
		)

	def _sql(self, query, params, as_dict=False):
		query = re.sub(r"%\((\w+)\)s", r":\1", query)
		return [SimpleNamespace(**dict(row)) for row in self.db.execute(query, params)]

	def _invoice(self, doctype, name, *, company="Store", day="2026-11-10", status=1,
				 warehouse="Shop", **fields):
		values = dict(name=name, company=company, posting_date=day, docstatus=status, **fields)
		columns = ", ".join(values)
		placeholders = ", ".join("?" for _ in values)
		self.db.execute(f"INSERT INTO `tab{doctype}` ({columns}) VALUES ({placeholders})", tuple(values.values()))
		self.db.execute(f"INSERT INTO `tab{doctype} Item` VALUES (?, ?)", (name, warehouse))

	def _payment(self, doctype, name, amount, mode="Efectivo", field="payments"):
		self.db.execute(
			"INSERT INTO `tabSales Invoice Payment` VALUES (?, ?, ?, ?, ?, ?)",
			(name, doctype, field, mode, amount, amount),
		)

	def _totals(self, **kwargs):
		return {row["name"]: row["value"] for row in self.dashboard._get_payment_methods_breakdown(
			"Store", "2026-11-01", "2026-11-17", **kwargs
		)}

	def test_pos_collections_use_shared_sales_invoice_payment_table(self):
		self._invoice("POS Invoice", "POS-1")
		self._payment("POS Invoice", "POS-1", 200)
		self._payment("POS Invoice", "POS-1", 300, "Tarjeta")
		self.assertEqual(self._totals(), {"Efectivo": 200, "Tarjeta": 300})

	def test_child_rows_are_scoped_to_parent_type_and_payment_field(self):
		self._invoice("Sales Invoice", "SAME-NAME")
		self._invoice("POS Invoice", "SAME-NAME")
		self._payment("Sales Invoice", "SAME-NAME", 100)
		self._payment("POS Invoice", "SAME-NAME", 250, "Tarjeta")
		self._payment("Sales Invoice", "SAME-NAME", 800, field="other_payments")
		self._payment("POS Invoice", "SAME-NAME", 900, field="other_payments")
		self.assertEqual(self._totals(), {"Efectivo": 100, "Tarjeta": 250})

	def test_consolidation_does_not_duplicate_collections_and_pending_is_optional(self):
		self._invoice("Sales Invoice", "CLOSE-1", is_consolidated=1)
		self._payment("Sales Invoice", "CLOSE-1", 500)
		self._invoice("POS Invoice", "CLOSED", consolidated_invoice="CLOSE-1")
		self._payment("POS Invoice", "CLOSED", 500)
		self._invoice("POS Invoice", "PENDING")
		self._payment("POS Invoice", "PENDING", 200)
		self.assertEqual(self._totals(), {"Efectivo": 700})
		self.assertEqual(self._totals(include_pending_pos=False), {"Efectivo": 500})

	def test_pos_filters_use_sale_date_company_status_and_warehouse(self):
		self._invoice("Sales Invoice", "DEC-CLOSE", day="2026-12-01", is_consolidated=1)
		self._invoice("POS Invoice", "VALID", consolidated_invoice="DEC-CLOSE")
		self._payment("POS Invoice", "VALID", 100)
		for name, filters in (
			("OLD", {"day": "2026-10-31"}), ("FUTURE", {"day": "2026-11-18"}),
			("DRAFT", {"status": 0}), ("CANCELLED", {"status": 2}),
			("OTHER-COMPANY", {"company": "Other"}), ("OTHER-SHOP", {"warehouse": "Other"}),
		):
			self._invoice("POS Invoice", name, **filters)
			self._payment("POS Invoice", name, 800)
		self.assertEqual(self._totals(warehouse="Shop"), {"Efectivo": 100})
		self.assertEqual(self._totals(), {"Efectivo": 900})

	def test_direct_invoice_payment_entry_and_pending_credit_still_work(self):
		self._invoice("Sales Invoice", "DIRECT", outstanding_amount=80)
		self._payment("Sales Invoice", "DIRECT", 120)
		self.db.execute("""
			INSERT INTO `tabPayment Entry` VALUES
			('Store', '2026-11-12', 1, 'Receive', 'Transferencia', 300, 300)
		""")
		self.assertEqual(self._totals(), {"Efectivo": 120, "Transferencia": 300, "Crédito / Por Cobrar": 80})

	def test_empty_period_returns_no_payment_methods(self):
		self.assertEqual(self._totals(), {})


if __name__ == "__main__":
	unittest.main()
