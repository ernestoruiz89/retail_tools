# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from retail_tools.setup import setup_custom_fields


def execute():
	setup_custom_fields()
	frappe.reload_doc("retail_tools", "page", "carga_compras", force=True)
	frappe.reload_doc("retail_tools", "workspace", "retail_tools", force=True)
	frappe.clear_cache()
