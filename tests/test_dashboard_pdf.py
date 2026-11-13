"""Check PDF export inputs without requiring a running Frappe bench."""

import base64
import importlib.util
import json
import struct
import sys
import unittest
import zlib
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


def _load_dashboard_module():
	frappe = ModuleType("frappe")
	frappe.__path__ = []
	frappe._ = lambda value: value
	frappe.whitelist = lambda: lambda function: function
	frappe.ValidationError = ValueError
	frappe.parse_json = json.loads
	frappe.db = SimpleNamespace(get_single_value=lambda doctype, field: "dd/mm/yyyy")

	def throw(message, exception=ValueError):
		raise exception(message)

	frappe.throw = throw
	utils = ModuleType("frappe.utils")
	for name in ("add_days", "cint", "date_diff", "getdate", "nowdate"):
		setattr(utils, name, lambda *args, **kwargs: None)
	utils.flt = lambda value, precision=None: round(float(value or 0), precision) if precision is not None else float(value or 0)
	utils.formatdate = lambda value, _format: datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
	path = Path(__file__).resolve().parents[1] / "retail_tools/retail_tools/page/store_dashboard/store_dashboard.py"
	spec = importlib.util.spec_from_file_location("dashboard_pdf_test_module", path)
	module = importlib.util.module_from_spec(spec)
	with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
		spec.loader.exec_module(module)
	return module


def _png_data_uri(width=960, height=420):
	def chunk(tag, data):
		return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

	rows = (b"\x00" + b"\xff\xff\xff" * width) * height
	image = b"\x89PNG\r\n\x1a\n"
	image += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
	image += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
	return "data:image/png;base64," + base64.b64encode(image).decode("ascii")


class DashboardPdfTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.dashboard = _load_dashboard_module()

	def test_requires_all_known_png_charts_with_print_dimensions(self):
		charts = dict.fromkeys(self.dashboard.PDF_CHART_KEYS, _png_data_uri())
		self.assertEqual(self.dashboard._validate_pdf_charts(charts), charts)
		with self.assertRaises(ValueError):
			self.dashboard._validate_pdf_charts({"rt-chart-balance": charts["rt-chart-balance"]})
		with self.assertRaises(ValueError):
			self.dashboard._validate_pdf_charts(dict.fromkeys(self.dashboard.PDF_CHART_KEYS, _png_data_uri(1, 1)))
		with self.assertRaises(ValueError):
			self.dashboard._validate_pdf_charts(dict.fromkeys(self.dashboard.PDF_CHART_KEYS, "data:text/html;base64,PHNjcmlwdD4="))

	def test_report_uses_system_date_format_and_chart_mode_captions(self):
		data = {
			"filters": {
				"company": "Tienda <Centro>", "currency": "NIO", "currency_symbol": "C$",
				"from_date": "2026-11-01", "to_date": "2026-11-13",
				"prev_from_date": "2026-10-01", "prev_to_date": "2026-10-13",
				"period_days": 13, "warehouse": "", "include_pending_pos": 1,
			},
			"kpis": {
				"net_sales": 100, "prev_net_sales": 80, "gross_profit": 40,
				"gross_margin_pct": 40, "net_profit": 20, "net_margin_pct": 20,
				"avg_ticket": 10, "ticket_count": 10, "stock_cost_value": 300,
				"sku_with_stock": 4, "cash_and_bank": 50, "accounts_receivable": 5,
			},
			"financials": {
				"balance_sheet": {
					"cash_and_bank": 50, "accounts_receivable": 5, "inventory": 300,
					"other_assets": 0, "total_assets": 355, "total_liabilities": 100,
					"total_equity": 255,
				},
				"income_statement": {
					"total_income": 100, "cogs": 60, "gross_profit": 40,
					"operating_expenses": 20, "net_profit": 20,
				},
			},
			"alerts": {"low_stock_stars": [], "dead_stock": []},
			"indicators_table": [],
		}
		charts = dict.fromkeys(self.dashboard.PDF_CHART_KEYS, _png_data_uri())
		context = self.dashboard._dashboard_pdf_context(data, charts, {"pnl": "expenses", "top": "by_qty"})
		self.assertEqual(context["from_date"], "01/11/2026")
		self.assertEqual(context["prev_to_date"], "13/10/2026")
		self.assertEqual(context["charts"][1]["title"], "Desglose de gastos")
		self.assertEqual(context["charts"][4]["title"], "Productos por unidades")
		self.assertEqual(context["dupont"]["roe"], "7.8%")


if __name__ == "__main__":
	unittest.main()
