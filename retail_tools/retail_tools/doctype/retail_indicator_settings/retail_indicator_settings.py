import frappe
from frappe import _
from frappe.model.document import Document

from retail_tools.retail_tools.page.store_dashboard.retail_metrics import (
	ANNUAL_TARGETS,
	LOWER_TARGETS,
	TARGET_KEYS,
	validate_settings,
)


class RetailIndicatorSettings(Document):
	def validate(self):
		for row in self.targets:
			key = TARGET_KEYS.get(row.indicator)
			row.target_rule = (
				"Rango de días" if key == "dio" else "Máximo" if key in LOWER_TARGETS else "Mínimo"
			) + (" anual" if key in ANNUAL_TARGETS else "")
		accounts = {
			row.account: frappe.db.get_value(
				"Account", row.account, ["company", "root_type", "is_group", "account_type"], as_dict=True
			)
			for row in self.expenses
		}
		try:
			validate_settings(self.as_dict(), accounts)
		except ValueError as exc:
			frappe.throw(_(str(exc)))
