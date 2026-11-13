"""Calendar-aware comparison periods for the store dashboard."""

from calendar import monthrange
from datetime import date, timedelta


def previous_period(start_date: date, end_date: date, range_key: str | None = None) -> tuple[date, date]:
	"""Return the comparison dates for the selected range."""
	if range_key == "this_month" and start_date == end_date.replace(day=1):
		previous_month_end = start_date - timedelta(days=1)
		previous_to = previous_month_end.replace(day=min(end_date.day, previous_month_end.day))
		return previous_month_end.replace(day=1), previous_to

	if (
		range_key == "last_month"
		and start_date == end_date.replace(day=1)
		and (end_date + timedelta(days=1)).day == 1
	):
		previous_month_end = start_date - timedelta(days=1)
		return previous_month_end.replace(day=1), previous_month_end

	if range_key == "ytd" and start_date == date(end_date.year, 1, 1):
		previous_year = end_date.year - 1
		previous_day = min(end_date.day, monthrange(previous_year, end_date.month)[1])
		return date(previous_year, 1, 1), date(previous_year, end_date.month, previous_day)

	previous_to = start_date - timedelta(days=1)
	return previous_to - (end_date - start_date), previous_to
