"""Check dashboard comparisons at month and year boundaries."""

import unittest
from datetime import date

from retail_tools.retail_tools.page.store_dashboard.periods import previous_period


class DashboardPeriodsTest(unittest.TestCase):
	def test_current_month_compares_same_days_of_previous_month(self):
		self.assertEqual(
			previous_period(date(2026, 11, 1), date(2026, 11, 13), "this_month"),
			(date(2026, 10, 1), date(2026, 10, 13)),
		)
		self.assertEqual(
			previous_period(date(2026, 3, 1), date(2026, 3, 31), "this_month"),
			(date(2026, 2, 1), date(2026, 2, 28)),
		)

	def test_previous_month_compares_complete_month_before_it(self):
		self.assertEqual(
			previous_period(date(2026, 10, 1), date(2026, 10, 31), "last_month"),
			(date(2026, 9, 1), date(2026, 9, 30)),
		)

	def test_year_to_date_compares_same_date_last_year(self):
		self.assertEqual(
			previous_period(date(2026, 1, 1), date(2026, 11, 13), "ytd"),
			(date(2025, 1, 1), date(2025, 11, 13)),
		)
		self.assertEqual(
			previous_period(date(2024, 1, 1), date(2024, 2, 29), "ytd"),
			(date(2023, 1, 1), date(2023, 2, 28)),
		)

	def test_rolling_period_uses_previous_equal_length_window(self):
		self.assertEqual(
			previous_period(date(2026, 10, 15), date(2026, 11, 13), "30d"),
			(date(2026, 9, 15), date(2026, 10, 14)),
		)
		self.assertEqual(
			previous_period(date(2026, 11, 1), date(2026, 11, 13)),
			(date(2026, 10, 19), date(2026, 10, 31)),
		)


if __name__ == "__main__":
	unittest.main()
