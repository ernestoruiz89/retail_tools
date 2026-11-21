# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, cstr

ALLOWED_TRANSFER_ROLES = {
	"Administrator",
	"System Manager",
	"Accounts Manager",
	"RT Responsable de Tienda",
	"RT Administrador de Sistema",
}


def _can_transfer_pos_invoice() -> bool:
	user = frappe.session.user
	if not user or user == "Guest":
		return False
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)) & ALLOWED_TRANSFER_ROLES)


def _is_pos_invoice_closed(invoice_name: str, inv: dict) -> bool:
	if cstr(inv.get("consolidated_invoice") or "").strip():
		return True
	if cstr(inv.get("status") or "").strip() == "Consolidated":
		return True

	closed_ref = frappe.db.sql(
		"""
		SELECT ref.parent
		FROM `tabPOS Invoice Reference` ref
		INNER JOIN `tabPOS Closing Entry` pce ON pce.name = ref.parent
		WHERE ref.pos_invoice = %s
		  AND pce.docstatus = 1
		LIMIT 1
		""",
		(invoice_name,),
	)
	return bool(closed_ref)


@frappe.whitelist()
def transfer_pos_invoice_owner(invoice_name: str, new_owner: str) -> dict:
	"""Transfer a POS Invoice to another enabled user if it has not been closed/consolidated."""
	if not _can_transfer_pos_invoice():
		frappe.throw(
			_("No tiene permisos para trasladar facturas POS a otro usuario."),
			frappe.PermissionError,
		)

	clean_invoice = cstr(invoice_name or "").strip()
	clean_new_owner = cstr(new_owner or "").strip()
	if not clean_invoice or not clean_new_owner:
		frappe.throw(_("Debe indicar la factura POS y el usuario destino."))

	inv = frappe.db.get_value(
		"POS Invoice",
		clean_invoice,
		["name", "owner", "docstatus", "status", "consolidated_invoice"],
		as_dict=True,
	)
	if not inv:
		frappe.throw(_("La Factura POS '{0}' no existe.").format(clean_invoice))

	if cint(inv.docstatus) == 2:
		frappe.throw(_("No se puede trasladar una Factura POS cancelada."))

	if _is_pos_invoice_closed(clean_invoice, inv):
		frappe.throw(
			_("No se puede trasladar la Factura POS '{0}' porque ya fue cerrada o consolidada.").format(
				clean_invoice
			)
		)

	if clean_new_owner == "Guest":
		frappe.throw(_("No se puede trasladar una factura al usuario Guest."))

	target_user = frappe.db.get_value("User", clean_new_owner, ["name", "enabled"], as_dict=True)
	if not target_user or not cint(target_user.enabled):
		frappe.throw(_("El usuario '{0}' no existe o está deshabilitado.").format(clean_new_owner))

	old_owner = cstr(inv.owner or "").strip()
	if old_owner == clean_new_owner:
		frappe.throw(_("La Factura POS ya pertenece al usuario '{0}'.").format(clean_new_owner))

	frappe.db.set_value(
		"POS Invoice",
		clean_invoice,
		{"owner": clean_new_owner},
		update_modified=False,
	)

	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "POS Invoice",
			"reference_name": clean_invoice,
			"content": _("Factura POS trasladada de {0} a {1} por {2}.").format(
				old_owner, clean_new_owner, frappe.session.user
			),
		}
	).insert(ignore_permissions=True)

	return {
		"ok": True,
		"invoice_name": clean_invoice,
		"old_owner": old_owner,
		"new_owner": clean_new_owner,
	}
