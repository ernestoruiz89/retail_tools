# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from retail_tools.setup import setup_custom_fields, setup_roles_and_permissions, sync_pages_and_workspace


def execute():
	setup_custom_fields()
	sync_pages_and_workspace()
	setup_roles_and_permissions()
	frappe.clear_cache()
