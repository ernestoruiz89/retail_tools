"""Restore standard permissions on sites that received the RT role fixtures."""

import frappe

from retail_tools.setup import restore_standard_permissions_for_rt_doctypes


def execute():
	# Frappe v15 syncs fixtures and customizations after post_model_sync patches.
	# Ask our after_migrate hook to verify permissions again after those imports.
	frappe.flags.retail_tools_restore_permissions_after_migrate = True
	restored, doctypes, skipped = restore_standard_permissions_for_rt_doctypes()
	print(f"Retail Tools: restored {restored} standard permissions in {len(doctypes)} DocTypes")
	if skipped:
		print(
			"Retail Tools: review customized permissions manually for: "
			+ ", ".join(skipped)
		)
