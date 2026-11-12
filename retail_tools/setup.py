# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint

RT_ROLES = (
	"RT Cajero",
	"RT Responsable de Tienda",
	"RT Contador",
	"RT Socio",
	"RT Administrador de Sistema",
)

PERM_FLAGS = (
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
)

# Permisos granulares por Rol RT según matriz de roles de tienda
ROLE_PERMISSIONS_MATRIX: dict[str, dict[str, dict[str, int]]] = {
	# 1. Cajero Pos User:
	# - Crear, Devolución, imprimir Facturación POS
	# - Registrar Cierre de caja
	# - Visualizar producto herramienta detail
	# - Crear modificar cliente
	"RT Cajero": {
		"POS Invoice": {"read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "email": 1, "report": 1},
		"Sales Invoice": {"read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "email": 1, "report": 1},
		"POS Opening Entry": {"read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "report": 1},
		"POS Closing Entry": {"read": 1, "write": 1, "create": 1, "submit": 1, "print": 1, "report": 1},
		"POS Profile": {"read": 1},
		"POS Settings": {"read": 1},
		"Mode of Payment": {"read": 1},
		"Payment Entry": {"read": 1, "write": 1, "create": 1, "submit": 1, "print": 1},
		"Sales Taxes and Charges Template": {"read": 1},
		"Item Tax Template": {"read": 1},
		"Tax Category": {"read": 1},
		"Pricing Rule": {"read": 1},
		"Account": {"read": 1},
		"Cost Center": {"read": 1},
		"Currency": {"read": 1},
		"Item": {"read": 1},
		"Item Price": {"read": 1},
		"Price List": {"read": 1},
		"Item Group": {"read": 1},
		"UOM": {"read": 1},
		"Brand": {"read": 1},
		"Bin": {"read": 1},
		"Warehouse": {"read": 1},
		"Batch": {"read": 1},
		"Serial No": {"read": 1},
		"Customer": {"read": 1, "write": 1, "create": 1, "print": 1, "report": 1},
		"Customer Group": {"read": 1},
		"Territory": {"read": 1},
		"Address": {"read": 1, "write": 1, "create": 1},
		"Contact": {"read": 1, "write": 1, "create": 1},
		"Company": {"read": 1},
	},
	# 2. Responsable de tienda (Stock User, Purchase User y POS Manager):
	# - Crear, Devolución, imprimir Facturación POS
	# - Gestionar factura POS
	# - Gestionar Cierre de caja
	# - Visualizar producto herramienta detail
	# - Gestionar productos, importar categorías, tipo producto
	# - Gestionar importar lista de precios
	# - Gestionar, Importar facturas de compra
	# - Generador de código de barra
	# - Gestionar gastos
	# - Visualizar reportes financieros
	# - Gestionar clientes
	"RT Responsable de Tienda": {
		"POS Invoice": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "email": 1, "report": 1, "export": 1,
		},
		"Sales Invoice": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "email": 1, "report": 1, "export": 1,
		},
		"POS Opening Entry": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "report": 1,
		},
		"POS Closing Entry": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "report": 1, "export": 1,
		},
		"POS Profile": {"read": 1, "write": 1, "create": 1, "report": 1},
		"POS Settings": {"read": 1, "write": 1},
		"Mode of Payment": {"read": 1},
		"Sales Taxes and Charges Template": {"read": 1},
		"Purchase Taxes and Charges Template": {"read": 1},
		"Item Tax Template": {"read": 1},
		"Tax Category": {"read": 1},
		"Currency": {"read": 1},
		"Item": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "import": 1, "export": 1, "print": 1, "report": 1,
		},
		"Item Group": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "import": 1, "export": 1, "report": 1,
		},
		"UOM": {"read": 1, "write": 1, "create": 1, "import": 1, "export": 1, "report": 1},
		"Brand": {"read": 1, "write": 1, "create": 1, "import": 1, "export": 1, "report": 1},
		"Price List": {"read": 1, "write": 1, "create": 1, "import": 1, "export": 1, "report": 1},
		"Item Price": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "import": 1, "export": 1, "report": 1,
		},
		"Pricing Rule": {"read": 1, "write": 1, "create": 1, "report": 1},
		"Purchase Invoice": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"import": 1, "export": 1, "print": 1, "email": 1, "report": 1,
		},
		"Purchase Order": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1, "print": 1, "report": 1,
		},
		"Purchase Receipt": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1, "print": 1, "report": 1,
		},
		"Supplier": {"read": 1, "write": 1, "create": 1, "import": 1, "export": 1, "report": 1},
		"Supplier Group": {"read": 1, "write": 1, "create": 1, "report": 1},
		"Stock Entry": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "report": 1, "export": 1,
		},
		"Stock Reconciliation": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "report": 1, "export": 1,
		},
		"Delivery Note": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1, "print": 1, "report": 1,
		},
		"Material Request": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1, "print": 1, "report": 1,
		},
		"Bin": {"read": 1, "report": 1, "export": 1},
		"Stock Ledger Entry": {"read": 1, "report": 1, "export": 1},
		"Warehouse": {"read": 1, "write": 1, "create": 1, "report": 1},
		"Batch": {"read": 1, "write": 1, "create": 1, "report": 1},
		"Serial No": {"read": 1, "write": 1, "create": 1, "report": 1},
		"Payment Entry": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "report": 1, "export": 1,
		},
		"Journal Entry": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "report": 1, "export": 1,
		},
		"Account": {"read": 1, "report": 1},
		"Cost Center": {"read": 1, "report": 1},
		"GL Entry": {"read": 1, "report": 1, "export": 1},
		"Customer": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "import": 1, "export": 1, "print": 1, "report": 1,
		},
		"Customer Group": {"read": 1, "write": 1, "create": 1, "import": 1, "export": 1, "report": 1},
		"Territory": {"read": 1, "write": 1, "create": 1, "report": 1},
		"Address": {"read": 1, "write": 1, "create": 1, "delete": 1},
		"Contact": {"read": 1, "write": 1, "create": 1, "delete": 1},
		"Data Import": {"read": 1, "write": 1, "create": 1, "submit": 1, "report": 1},
		"File": {"read": 1, "write": 1, "create": 1},
		"Company": {"read": 1, "report": 1},
	},
	# 3. Contador:
	# - Gestionar la contabilidad
	# - Visualizar reportes de venta
	"RT Contador": {
		"Account": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "import": 1, "export": 1, "print": 1, "report": 1,
		},
		"Journal Entry": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"import": 1, "export": 1, "print": 1, "email": 1, "report": 1,
		},
		"Payment Entry": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"import": 1, "export": 1, "print": 1, "email": 1, "report": 1,
		},
		"Sales Invoice": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"import": 1, "export": 1, "print": 1, "email": 1, "report": 1,
		},
		"Purchase Invoice": {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"import": 1, "export": 1, "print": 1, "email": 1, "report": 1,
		},
		"POS Invoice": {"read": 1, "print": 1, "report": 1, "export": 1},
		"POS Closing Entry": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1,
			"print": 1, "report": 1, "export": 1,
		},
		"POS Opening Entry": {"read": 1, "print": 1, "report": 1},
		"GL Entry": {"read": 1, "report": 1, "export": 1, "print": 1},
		"Cost Center": {"read": 1, "write": 1, "create": 1, "report": 1, "export": 1},
		"Fiscal Year": {"read": 1, "write": 1, "create": 1, "report": 1},
		"Period Closing Voucher": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1, "print": 1, "report": 1,
		},
		"Bank Account": {"read": 1, "write": 1, "create": 1, "report": 1},
		"Bank Transaction": {
			"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "report": 1, "import": 1,
		},
		"Mode of Payment": {"read": 1, "write": 1, "create": 1},
		"Sales Taxes and Charges Template": {"read": 1, "write": 1, "create": 1},
		"Purchase Taxes and Charges Template": {"read": 1, "write": 1, "create": 1},
		"Item Tax Template": {"read": 1, "write": 1, "create": 1},
		"Tax Category": {"read": 1, "write": 1, "create": 1},
		"Tax Rule": {"read": 1, "write": 1, "create": 1},
		"Currency": {"read": 1},
		"Customer": {"read": 1, "write": 1, "create": 1, "report": 1, "export": 1},
		"Customer Group": {"read": 1},
		"Territory": {"read": 1},
		"Supplier": {"read": 1, "write": 1, "create": 1, "report": 1, "export": 1},
		"Supplier Group": {"read": 1},
		"Item": {"read": 1, "write": 1, "create": 1, "report": 1, "export": 1},
		"Item Group": {"read": 1},
		"UOM": {"read": 1},
		"Brand": {"read": 1},
		"Item Price": {"read": 1, "write": 1, "create": 1, "report": 1, "export": 1},
		"Price List": {"read": 1, "report": 1},
		"Stock Ledger Entry": {"read": 1, "report": 1, "export": 1},
		"Bin": {"read": 1, "report": 1, "export": 1},
		"Warehouse": {"read": 1, "report": 1},
		"File": {"read": 1, "write": 1, "create": 1},
		"Company": {"read": 1, "report": 1},
	},
	# 4. Socio/ReportViewer:
	# - Read only visualizar imprimir reportes de venta, catálogos, financieros
	"RT Socio": {
		dt: {"read": 1, "print": 1, "report": 1, "export": 1}
		for dt in (
			"Sales Invoice",
			"POS Invoice",
			"POS Closing Entry",
			"POS Opening Entry",
			"Sales Order",
			"Delivery Note",
			"Purchase Invoice",
			"Purchase Order",
			"Purchase Receipt",
			"Item",
			"Item Group",
			"Brand",
			"UOM",
			"Item Price",
			"Price List",
			"Bin",
			"Stock Ledger Entry",
			"Warehouse",
			"Stock Entry",
			"Stock Reconciliation",
			"Customer",
			"Customer Group",
			"Territory",
			"Address",
			"Contact",
			"Supplier",
			"Supplier Group",
			"Account",
			"GL Entry",
			"Journal Entry",
			"Payment Entry",
			"Cost Center",
			"Fiscal Year",
			"Currency",
			"Company",
		)
	},
	# 5. Administrador de sistema:
	# - Acceso full
	"RT Administrador de Sistema": {
		dt: {
			"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
			"report": 1, "export": 1, "import": 1, "share": 1, "print": 1, "email": 1,
		}
		for dt in (
			"POS Invoice",
			"Sales Invoice",
			"POS Opening Entry",
			"POS Closing Entry",
			"POS Profile",
			"POS Settings",
			"Mode of Payment",
			"Sales Taxes and Charges Template",
			"Purchase Taxes and Charges Template",
			"Item Tax Template",
			"Tax Category",
			"Tax Rule",
			"Currency",
			"Item",
			"Item Group",
			"UOM",
			"Brand",
			"Price List",
			"Item Price",
			"Pricing Rule",
			"Purchase Invoice",
			"Purchase Order",
			"Purchase Receipt",
			"Supplier",
			"Supplier Group",
			"Stock Entry",
			"Stock Reconciliation",
			"Delivery Note",
			"Material Request",
			"Bin",
			"Stock Ledger Entry",
			"Warehouse",
			"Batch",
			"Serial No",
			"Payment Entry",
			"Journal Entry",
			"Account",
			"Cost Center",
			"GL Entry",
			"Fiscal Year",
			"Period Closing Voucher",
			"Bank Account",
			"Bank Transaction",
			"Customer",
			"Customer Group",
			"Territory",
			"Address",
			"Contact",
			"Data Import",
			"File",
			"Company",
			"User",
			"Role",
			"Role Profile",
			"Stock Settings",
			"Selling Settings",
			"Buying Settings",
			"Accounts Settings",
		)
	},
}

PAGE_ROLES_MAP: dict[str, list[str]] = {
	"item-inspector": [
		"RT Cajero",
		"RT Responsable de Tienda",
		"RT Contador",
		"RT Socio",
		"RT Administrador de Sistema",
	],
	"item-inspector-light": [
		"RT Cajero",
		"RT Responsable de Tienda",
		"RT Contador",
		"RT Socio",
		"RT Administrador de Sistema",
	],
	"customer-lookup": [
		"RT Cajero",
		"RT Responsable de Tienda",
		"RT Contador",
		"RT Socio",
		"RT Administrador de Sistema",
	],
	"catalog-generator": [
		"RT Responsable de Tienda",
		"RT Socio",
		"RT Administrador de Sistema",
	],
	"label-generator": [
		"RT Responsable de Tienda",
		"RT Administrador de Sistema",
	],
	"carga-compras": [
		"RT Responsable de Tienda",
		"RT Contador",
		"RT Administrador de Sistema",
	],
	"store-dashboard": [
		"RT Responsable de Tienda",
		"RT Contador",
		"RT Socio",
		"RT Administrador de Sistema",
	],
}


def after_install():
	setup_custom_fields()
	sync_pages_and_workspace()
	setup_roles_and_permissions()
	frappe.clear_cache()


def after_migrate():
	setup_custom_fields()
	sync_pages_and_workspace()
	setup_roles_and_permissions()
	frappe.clear_cache()


def sync_pages_and_workspace():
	for page_module in ("carga_compras", "store_dashboard"):
		try:
			frappe.reload_doc("retail_tools", "page", page_module, force=True)
		except Exception:
			pass
	try:
		frappe.reload_doc("retail_tools", "workspace", "retail_tools", force=True)
	except Exception:
		pass


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


def setup_roles_and_permissions():
	"""Create or update RT Roles, Custom DocPerms, and Page Roles."""
	# 1. Ensure RT Roles exist
	for role_name in RT_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": 1,
					"is_custom": 1,
					"disabled": 0,
				}
			).insert(ignore_permissions=True)
		else:
			frappe.db.set_value(
				"Role",
				role_name,
				{"desk_access": 1, "disabled": 0},
				update_modified=False,
			)

	# 2. Ensure Custom DocPerm entries for each RT Role and DocType
	for role_name, doctype_perms in ROLE_PERMISSIONS_MATRIX.items():
		for dt_name, perms in doctype_perms.items():
			if not frappe.db.exists("DocType", dt_name):
				continue

			meta = frappe.get_meta(dt_name)
			if cint(meta.istable):
				continue

			is_submittable = bool(cint(meta.is_submittable))
			is_single = bool(cint(meta.issingle))
			allow_import = bool(cint(meta.allow_import))

			normalized_perms = {flag: cint(perms.get(flag, 0)) for flag in PERM_FLAGS}
			if not is_submittable:
				normalized_perms["submit"] = 0
				normalized_perms["cancel"] = 0
				normalized_perms["amend"] = 0
			if is_single:
				normalized_perms["create"] = 0
				normalized_perms["delete"] = 0
				normalized_perms["report"] = 0
				normalized_perms["export"] = 0
				normalized_perms["import"] = 0
			if not allow_import:
				normalized_perms["import"] = 0

			existing_name = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": dt_name, "role": role_name, "permlevel": 0, "if_owner": 0},
				"name",
			)
			if existing_name:
				doc = frappe.get_doc("Custom DocPerm", existing_name)
				changed = False
				for flag, val in normalized_perms.items():
					if cint(doc.get(flag)) != val:
						doc.set(flag, val)
						changed = True
				if changed:
					doc.save(ignore_permissions=True)
			else:
				doc_data = {
					"doctype": "Custom DocPerm",
					"parent": dt_name,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": role_name,
					"permlevel": 0,
					"if_owner": 0,
				}
				doc_data.update(normalized_perms)
				frappe.get_doc(doc_data).insert(ignore_permissions=True)

	# 3. Ensure Page Roles for Retail Tools pages
	for page_name, rt_page_roles in PAGE_ROLES_MAP.items():
		if not frappe.db.exists("Page", page_name):
			continue
		page_doc = frappe.get_doc("Page", page_name)
		existing_roles = {row.role for row in page_doc.roles}
		added = False
		for r in rt_page_roles:
			if r not in existing_roles and frappe.db.exists("Role", r):
				page_doc.append("roles", {"role": r})
				existing_roles.add(r)
				added = True
		if added:
			page_doc.save(ignore_permissions=True)

	frappe.db.commit()
