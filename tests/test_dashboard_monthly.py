"""Monthly sales aggregation without a running Frappe bench."""

import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from test_dashboard_pdf import _load_dashboard_module


class DashboardMonthlyTest(unittest.TestCase):
	def setUp(self):
		self.dashboard = _load_dashboard_module()
		self.dashboard.getdate = lambda value: date.fromisoformat(str(value))
		self.dashboard.nowdate = lambda: "2026-11-14"
		self.dashboard.add_days = lambda value, days: self.dashboard.getdate(value) + timedelta(days=days)
		self.dashboard.date_diff = lambda end, start: (end - start).days
		self.dashboard.cint = lambda value: int(value or 0)

	def row(self, day, sales, qty=1, rate=0, channel="POS"):
		return SimpleNamespace(
			posting_date=day, net_amount=sales, qty=qty, stock_qty=qty,
			incoming_rate=rate, item_code="Item", sale_channel=channel,
			doctype="POS Invoice" if channel == "POS" else "Sales Invoice",
			invoice_name=f"{day}-{sales}", item_name="Item", item_group="Goods",
			posting_time="12:00:00", is_return=int(sales < 0),
		)

	def test_combined_sales_returns_empty_months_and_weighted_margin(self):
		rows = [
			self.row("2025-12-01", 100, rate=80),
			self.row("2025-12-15", 900, rate=450, channel="Direct"),
			self.row("2025-12-20", -100, qty=-1, rate=80),
			self.row("2026-02-28", 200, qty=2),
		]
		trend = self.dashboard._compute_monthly_trend(rows, {"Item": 30}, "2025-12-01", "2026-02-28")
		self.assertEqual(trend["dates"], ["2025-12-01", "2026-01-01", "2026-02-01"])
		self.assertEqual(trend["sales"], [900, 0, 200])
		self.assertEqual(trend["profit"], [450, 0, 140])
		self.assertEqual(trend["margin_pct"], [50, None, 70])
		daily = self.dashboard._compute_commercial_metrics(rows, {"Item": 30}, "2025-12-01", "2026-02-28")
		self.assertEqual(sum(trend["sales"]), daily["net_sales"])
		self.assertEqual(sum(trend["profit"]), daily["gross_profit"])

	def test_zero_net_sales_have_no_margin_and_partial_month_respects_bounds(self):
		rows = [self.row("2026-11-01", 500), self.row("2026-11-10", 100), self.row("2026-11-11", -100, qty=-1), self.row("2026-11-15", 500)]
		trend = self.dashboard._compute_monthly_trend(rows, {}, "2026-11-10", "2026-11-14")
		self.assertEqual(trend["sales"], [0])
		self.assertEqual(trend["margin_pct"], [None])

	def test_short_presets_fetch_thirteen_months_with_same_company_warehouse_and_pos_filter(self):
		with patch.object(self.dashboard, "_fetch_sales_line_rows", return_value=[]) as fetch:
			for preset in ("today", "7d", "30d", "this_month", "last_month"):
				trend = self.dashboard._get_monthly_trend("Company", "Store", False, {}, "2026-10-01", "2026-10-31", preset, [])
				fetch.assert_called_with("Company", "2025-11-01", "2026-11-14", "Store", False)
				self.assertEqual(len(trend["dates"]), 13)
				self.assertEqual(trend["dates"][0], "2025-11-01")
				self.assertEqual(trend["dates"][-1], "2026-11-01")
				self.assertEqual(trend["scope"], "13m")

	def test_ytd_and_custom_ranges_reuse_loaded_sales(self):
		with patch.object(self.dashboard, "_fetch_sales_line_rows") as fetch:
			trend = self.dashboard._get_monthly_trend("Company", None, True, {}, "2026-01-01", "2026-11-14", "ytd", [])
			self.assertEqual(len(trend["dates"]), 11)
			self.assertEqual(trend["scope"], "ytd")
			trend = self.dashboard._get_monthly_trend("Company", None, True, {}, "2025-03-15", "2025-04-05", None, [])
			self.assertEqual(trend["dates"], ["2025-03-01", "2025-04-01"])
			self.assertEqual(trend["scope"], "custom")
			fetch.assert_not_called()

	def test_month_to_day_uses_same_cutoff_for_sales_profit_and_margin_without_extra_query(self):
		rows = [
			self.row("2025-11-14", 100, rate=60),
			self.row("2025-11-15", 400, rate=200),
			self.row("2026-10-01", 100, rate=60),
			self.row("2026-10-14", 200, rate=100, channel="Direct"),
			self.row("2026-10-14", -100, qty=-1, rate=60),
			self.row("2026-10-15", 900, rate=400),
			self.row("2026-11-14", 300, rate=150),
		]
		with patch.object(self.dashboard, "_fetch_sales_line_rows", return_value=rows) as fetch:
			trend = self.dashboard._get_monthly_trend("Company", "Store", True, {}, "2026-11-14", "2026-11-14", "today", [])
			fetch.assert_called_once_with("Company", "2025-11-01", "2026-11-14", "Store", True)
		self.assertEqual(trend["sales"][0], 500)
		self.assertEqual(trend["sales"][-2:], [1100, 300])
		partial = trend["to_day"]
		self.assertEqual(partial["cutoff_day"], 14)
		self.assertEqual(partial["scope"], "13m")
		self.assertEqual(partial["dates"], trend["dates"])
		self.assertEqual(partial["sales"][-2:], [200, 300])
		self.assertEqual(partial["profit"][-2:], [100, 150])
		self.assertEqual(partial["margin_pct"][-2:], [50, 50])
		self.assertEqual(partial["sales"][0], 100)
		self.assertEqual(partial["profit"][0], 40)
		self.assertEqual(partial["sales"][1], 0)
		self.assertIsNone(partial["margin_pct"][1])

	def test_month_to_day_handles_first_day_and_short_leap_months(self):
		rows = [self.row("2024-02-01", 100), self.row("2024-02-29", 200), self.row("2024-03-01", 300), self.row("2024-03-31", 400)]
		first = self.dashboard._compute_monthly_trend(rows, {}, "2024-02-01", "2024-03-31", cutoff_day=1)
		self.assertEqual(first["sales"], [100, 300])
		last = self.dashboard._compute_monthly_trend(rows, {}, "2024-02-01", "2024-03-31", cutoff_day=31)
		self.assertEqual(last["sales"], [300, 700])
		self.dashboard.nowdate = lambda: "2026-11-07"
		with patch.object(self.dashboard, "_fetch_sales_line_rows", return_value=[]):
			trend = self.dashboard._get_monthly_trend("Company", None, True, {}, "2026-01-01", "2026-11-07", "ytd", [])
		self.assertEqual(trend["to_day"]["cutoff_day"], 7)
		self.assertEqual(trend["to_day"]["scope"], "ytd")
		self.assertEqual(len(trend["to_day"]["dates"]), 11)


if __name__ == "__main__":
	unittest.main()
