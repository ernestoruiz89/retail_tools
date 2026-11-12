from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate

from retail_tools.retail_tools.page.store_dashboard.store_dashboard import (
	get_dashboard_defaults,
	get_store_dashboard_data,
)
from retail_tools.setup import setup_roles_and_permissions, sync_pages_and_workspace


class TestStoreDashboard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		sync_pages_and_workspace()
		setup_roles_and_permissions()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _ensure_single_role_user(self, email: str, role_name: str) -> str:
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": f"Test {role_name}",
					"enabled": 1,
					"user_type": "System User",
					"send_welcome_email": 0,
				}
			)
			user.insert(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", email)
			user.enabled = 1
			user.user_type = "System User"

		user.roles = []
		user.append("roles", {"role": role_name})
		user.save(ignore_permissions=True)
		return email

	def test_defaults_and_dashboard_structure_and_accounting_equation(self):
		frappe.set_user("Administrator")
		defaults = get_dashboard_defaults()
		self.assertIn("company", defaults)
		self.assertIn("currency", defaults)
		self.assertTrue(len(defaults.get("companies", [])) >= 1)

		data = get_store_dashboard_data(
			company=defaults["company"],
			from_date=defaults["default_from_date"],
			to_date=defaults["default_to_date"],
			include_pending_pos=1,
		)

		self.assertIn("kpis", data)
		self.assertIn("financials", data)
		self.assertIn("charts", data)
		self.assertIn("alerts", data)
		self.assertIn("indicators_table", data)

		bs = data["financials"]["balance_sheet"]
		pnl = data["financials"]["income_statement"]

		# Verify Balance Sheet equation: Total Assets == Total Liabilities + Total Equity
		self.assertAlmostEqual(
			flt(bs["total_assets"], 2),
			flt(bs["total_liabilities_and_equity"], 2),
			places=1,
		)

		# Verify Income Statement equation: Gross Profit - Operating Expenses == Net Profit
		self.assertAlmostEqual(
			flt(pnl["gross_profit"] - pnl["operating_expenses"], 2),
			flt(pnl["net_profit"], 2),
			places=1,
		)

		# Verify 13 indicators in the final table
		indicators = data["indicators_table"]
		self.assertEqual(len(indicators), 13)
		categories = {row["category"] for row in indicators}
		self.assertEqual(
			categories,
			{"Rentabilidad", "Liquidez y Solvencia", "Inventario y Operación"},
		)

		# Verify Heatmap dimensions (24 hours x 7 days = 168 cells)
		heatmap = data["charts"]["hourly_heatmap"]
		self.assertEqual(len(heatmap["days"]), 7)
		self.assertEqual(len(heatmap["hours"]), 24)
		self.assertEqual(len(heatmap["data"]), 168)

		# Verify Workspace 'Retail Tools' contains 'Store Dashboard' shortcut & link
		ws = frappe.get_doc("Workspace", "Retail Tools")
		shortcut_links = {s.link_to for s in ws.shortcuts}
		self.assertIn("store-dashboard", shortcut_links)
		self.assertIn("Store Dashboard", ws.content or "")

	def test_sales_and_inventory_reflection_in_dashboard(self):
		frappe.set_user("Administrator")
		defaults = get_dashboard_defaults()
		company = defaults["company"]
		today = nowdate()

		wh = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name"
		)
		customer = frappe.db.get_value("Customer", {}, "name")
		supplier = frappe.db.get_value("Supplier", {}, "name")
		if not (wh and customer and supplier):
			self.skipTest("Missing base master records for transaction test")

		item_code = "RT-DASH-TEST-ITEM-001"
		if not frappe.db.exists("Item", item_code):
			item_Group = (
				frappe.db.get_value("Item Group", {"is_group": 0}, "name")
				or frappe.db.get_value("Item Group", {}, "name")
			)
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item_code,
					"item_name": "Producto Estrella Dashboard",
					"item_group": item_Group,
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"valuation_rate": 50.0,
					"standard_rate": 100.0,
				}
			).insert(ignore_permissions=True)

		before = get_store_dashboard_data(
			company=company, from_date=today, to_date=today, warehouse=wh
		)

		# Create a Purchase Invoice to add 10 units @ $50 cost
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": company,
				"supplier": supplier,
				"posting_date": today,
				"due_date": today,
				"update_stock": 1,
				"set_warehouse": wh,
				"items": [
					{
						"item_code": item_code,
						"qty": 10,
						"rate": 50.0,
						"warehouse": wh,
					}
				],
			}
		)
		pi.insert(ignore_permissions=True)
		pi.submit()

		# Create a Sales Invoice selling 4 units @ $100
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": company,
				"customer": customer,
				"posting_date": today,
				"due_date": today,
				"update_stock": 1,
				"set_warehouse": wh,
				"items": [
					{
						"item_code": item_code,
						"qty": 4,
						"rate": 100.0,
						"warehouse": wh,
					}
				],
			}
		)
		si.insert(ignore_permissions=True)
		si.submit()

		after = get_store_dashboard_data(
			company=company, from_date=today, to_date=today, warehouse=wh
		)

		self.assertAlmostEqual(
			flt(after["kpis"]["net_sales"]) - flt(before["kpis"]["net_sales"]),
			400.0,
			places=1,
		)
		self.assertGreater(flt(after["kpis"]["gross_profit"]), flt(before["kpis"]["gross_profit"]))
		self.assertGreaterEqual(after["kpis"]["ticket_count"], before["kpis"]["ticket_count"] + 1)

	def test_rt_roles_access_control(self):
		allowed_roles = [
			("rt_socio_dash@example.com", "RT Socio"),
			("rt_resp_dash@example.com", "RT Responsable de Tienda"),
			("rt_cont_dash@example.com", "RT Contador"),
			("rt_admin_dash@example.com", "RT Administrador de Sistema"),
		]
		for email, role_name in allowed_roles:
			frappe.set_user("Administrator")
			self._ensure_single_role_user(email, role_name)
			frappe.set_user(email)
			defaults = get_dashboard_defaults()
			data = get_store_dashboard_data(company=defaults["company"])
			self.assertIn("kpis", data)
			self.assertEqual(len(data["indicators_table"]), 13)

		# RT Cajero should NOT have access to executive store dashboard
		frappe.set_user("Administrator")
		cajero_email = self._ensure_single_role_user("rt_cajero_dash@example.com", "RT Cajero")
		frappe.set_user(cajero_email)
		with self.assertRaises(frappe.PermissionError):
			get_store_dashboard_data()
