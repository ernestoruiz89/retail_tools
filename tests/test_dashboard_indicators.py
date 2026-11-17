"""Annualized indicators share a time basis, targets and DuPont components."""

import unittest

from test_dashboard_pdf import _load_dashboard_module


def indicator_inputs(days=30):
	comm = {"gross_margin_pct": 40, "cogs": 6000, "avg_ticket": 100, "upt": 2}
	financials = {
		"balance_sheet": {
			"total_assets": 100000, "total_equity": 50000, "cash_and_bank": 10000,
			"accounts_receivable": 2000, "inventory": 12000,
			"total_liabilities": 50000, "accounts_payable": 5000,
		},
		"income_statement": {
			"net_profit": 3000, "total_income": 10000, "net_margin_pct": 30,
			"op_expense_pct": 10, "cogs": 6000,
		},
	}
	return dict(
		currency="NIO", period_days=days, current_comm=comm, prev_comm=comm.copy(),
		financials=financials, prev_financials=financials,
		inventory_data={"stock_cost_value": 12000},
	)


class DashboardIndicatorsTest(unittest.TestCase):
	def setUp(self):
		self.dashboard = _load_dashboard_module()
		self.dashboard.frappe.db.get_value = lambda *args, **kwargs: "C$"

	def views(self, inputs):
		return [self.dashboard._build_indicator_view(mode, **inputs) for mode in ("period", "annualized")]

	def test_only_returns_and_turnovers_scale_for_short_full_and_multi_year_periods(self):
		for days in (1, 7, 17, 30, 365, 366, 730):
			with self.subTest(days=days):
				period, annual = self.views(indicator_inputs(days))
				factor = 365 / days
				for row, scaled in zip(period["indicators"], annual["indicators"]):
					if row.get("key") in ("roa", "roe", "inventory_turnover"):
						self.assertAlmostEqual(scaled["value"], row["value"] * factor)
						self.assertEqual(scaled["status"], row["status"])
					else:
						self.assertEqual(scaled, row)
				self.assertAlmostEqual(annual["dupont"]["turnover"], period["dupont"]["turnover"] * factor)
				for key in ("margin", "multiplier"):
					self.assertEqual(annual["dupont"][key], period["dupont"][key])

	def test_dupont_product_and_status_match_roe_in_both_views(self):
		for view in self.views(indicator_inputs(17)):
			d = view["dupont"]
			roe_row = next(row for row in view["indicators"] if row.get("key") == "roe")
			self.assertAlmostEqual(d["margin"] * d["turnover"] * d["multiplier"], d["roe"])
			self.assertAlmostEqual(d["roe"], roe_row["value"])
			self.assertEqual(d["status"], roe_row["status"])
			self.assertEqual(d["reference_formatted"], roe_row["reference_formatted"])
			self.assertAlmostEqual(d["scaled_profit"] / d["equity"] * 100, d["roe"])
			self.assertAlmostEqual(d["scaled_sales"] / d["assets"], d["turnover"])

	def test_targets_preserve_thirty_day_thresholds_and_same_daily_performance(self):
		for days in (1, 17, 30, 365, 366):
			inputs = indicator_inputs(days)
			inputs["financials"]["income_statement"]["net_profit"] = 3000 * days / 30
			inputs["current_comm"]["cogs"] = 6000 * days / 30
			for view in self.views(inputs):
				for row in view["indicators"]:
					if row.get("key") in ("roa", "roe", "inventory_turnover"):
						self.assertEqual(row["status"], "good")
		period, annual = self.views(indicator_inputs())
		by_key = {row["key"]: row for row in annual["indicators"] if row.get("key")}
		self.assertIn("36.5%", by_key["roa"]["reference_formatted"])
		self.assertIn("60.8%", by_key["roe"]["reference_formatted"])
		self.assertIn("6.08x", by_key["inventory_turnover"]["reference_formatted"])
		self.assertIn("1.82x", by_key["inventory_turnover"]["reference_formatted"])

	def test_warning_and_loss_statuses_are_invariant_under_display_mode(self):
		for profit, expected in ((1000, "warning"), (-100, "danger"), (0, "warning")):
			inputs = indicator_inputs()
			inputs["financials"]["income_statement"]["net_profit"] = profit
			for view in self.views(inputs):
				self.assertEqual(view["dupont"]["status"], expected)

	def test_nonpositive_denominators_are_not_presented_as_healthy_zero_returns(self):
		for denominator in (0, -100):
			inputs = indicator_inputs()
			inputs["financials"]["balance_sheet"].update(total_assets=denominator, total_equity=denominator)
			inputs["inventory_data"]["stock_cost_value"] = denominator
			for view in self.views(inputs):
				for row in view["indicators"]:
					if row.get("key") in ("roa", "roe", "inventory_turnover"):
						self.assertIsNone(row["value"])
						self.assertEqual(row["value_formatted"], "N/A")
						self.assertEqual(row["status"], "neutral")
				self.assertIsNone(view["dupont"]["roe"])
				self.assertIsNone(view["dupont"]["turnover"])
				self.assertIsNone(view["dupont"]["multiplier"])

	def test_unrecognized_mode_defaults_to_period_and_empty_sales_has_no_margin(self):
		inputs = indicator_inputs()
		inputs["financials"]["income_statement"]["total_income"] = 0
		view = self.dashboard._build_indicator_view("invalid", **inputs)
		self.assertEqual(view["mode"], "period")
		self.assertEqual(view["factor"], 1)
		self.assertIsNone(view["dupont"]["margin"])


if __name__ == "__main__":
	unittest.main()
