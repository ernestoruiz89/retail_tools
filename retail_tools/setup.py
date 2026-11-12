# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
	setup_custom_fields()


def after_migrate():
	setup_custom_fields()


def setup_custom_fields():
	if not frappe.db.exists("DocType", "Purchase Invoice"):
		return

	custom_fields = {
		"Purchase Invoice": [
			{
				"fieldname": "retail_tools_upload_id",
				"label": "Retail Tools Upload ID",
				"fieldtype": "Data",
				"insert_after": "bill_date",
				"read_only": 1,
				"no_copy": 1,
				"hidden": 1,
				"unique": 1,
			}
		]
	}
	create_custom_fields(custom_fields, update=True)
