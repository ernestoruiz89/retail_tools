"""Tests for transferring unconsolidated POS Invoices to another user."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


class Row(dict):
	def __getattr__(self, key):
		return self[key]


def load_pos_invoice_module(
	*,
	session_user="Administrator",
	roles=None,
	invoice_row=None,
	user_row=None,
	closing_refs=None,
):
	roles = roles if roles is not None else ["System Manager"]
	updates = []
	comments = []

	frappe = types.ModuleType("frappe")
	frappe.__path__ = []
	frappe._ = lambda msg: msg
	frappe.PermissionError = PermissionError
	frappe.whitelist = lambda *a, **kw: (lambda fn: fn)
	frappe.session = types.SimpleNamespace(user=session_user)
	frappe.get_roles = lambda user=None: list(roles)

	def _throw(msg, exc=Exception):
		raise exc(msg)

	frappe.throw = _throw

	def _get_value(dt, name, fields=None, as_dict=False):
		if dt == "POS Invoice":
			return invoice_row
		if dt == "User":
			return user_row
		return None

	frappe.db = types.SimpleNamespace(
		get_value=_get_value,
		set_value=lambda dt, name, values, update_modified=True: updates.append(
			(dt, name, dict(values), update_modified)
		),
		sql=lambda query, params=None: list(closing_refs or []),
	)
	frappe.get_doc = lambda payload: types.SimpleNamespace(
		insert=lambda ignore_permissions=False: comments.append((payload, ignore_permissions))
	)

	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda v: int(v or 0)
	utils.cstr = lambda v: "" if v is None else str(v)

	path = Path(__file__).resolve().parents[1] / "retail_tools" / "utils" / "pos_invoice.py"
	with mock.patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
		spec = importlib.util.spec_from_file_location("pos_invoice_transfer_test", path)
		mod = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(mod)

	return mod, updates, comments


class PosInvoiceTransferTest(unittest.TestCase):
	def test_transfers_open_pos_invoice_and_logs_comment(self):
		inv = Row(
			name="ACC-PSINV-2026-01839",
			owner="Administrator",
			docstatus=1,
			status="Paid",
			consolidated_invoice=None,
		)
		target = Row(name="ligiadelgadillo86@correo.com", enabled=1)
		mod, updates, comments = load_pos_invoice_module(invoice_row=inv, user_row=target)

		res = mod.transfer_pos_invoice_owner("ACC-PSINV-2026-01839", "ligiadelgadillo86@correo.com")

		self.assertTrue(res["ok"])
		self.assertEqual(res["old_owner"], "Administrator")
		self.assertEqual(res["new_owner"], "ligiadelgadillo86@correo.com")
		self.assertEqual(
			updates,
			[("POS Invoice", "ACC-PSINV-2026-01839", {"owner": "ligiadelgadillo86@correo.com"}, False)],
		)
		self.assertEqual(len(comments), 1)
		self.assertEqual(comments[0][0]["reference_name"], "ACC-PSINV-2026-01839")

	def test_rejects_consolidated_or_closed_invoice(self):
		inv_consolidated = Row(
			name="ACC-PSINV-1",
			owner="Administrator",
			docstatus=1,
			status="Consolidated",
			consolidated_invoice="ACC-SINV-1",
		)
		target = Row(name="ligia@correo.com", enabled=1)
		mod, updates, _ = load_pos_invoice_module(invoice_row=inv_consolidated, user_row=target)
		with self.assertRaises(Exception):
			mod.transfer_pos_invoice_owner("ACC-PSINV-1", "ligia@correo.com")
		self.assertEqual(updates, [])

		inv_with_closing = Row(
			name="ACC-PSINV-2",
			owner="Administrator",
			docstatus=1,
			status="Paid",
			consolidated_invoice=None,
		)
		mod2, updates2, _ = load_pos_invoice_module(
			invoice_row=inv_with_closing, user_row=target, closing_refs=[("POS-CLO-1",)]
		)
		with self.assertRaises(Exception):
			mod2.transfer_pos_invoice_owner("ACC-PSINV-2", "ligia@correo.com")
		self.assertEqual(updates2, [])

	def test_rejects_cancelled_invoice_and_unauthorized_role(self):
		inv_cancelled = Row(
			name="ACC-PSINV-3",
			owner="Administrator",
			docstatus=2,
			status="Cancelled",
			consolidated_invoice=None,
		)
		target = Row(name="ligia@correo.com", enabled=1)
		mod, updates, _ = load_pos_invoice_module(invoice_row=inv_cancelled, user_row=target)
		with self.assertRaises(Exception):
			mod.transfer_pos_invoice_owner("ACC-PSINV-3", "ligia@correo.com")
		self.assertEqual(updates, [])

		inv_ok = Row(
			name="ACC-PSINV-4",
			owner="Administrator",
			docstatus=1,
			status="Paid",
			consolidated_invoice=None,
		)
		mod_unauth, updates_unauth, _ = load_pos_invoice_module(
			session_user="cajero@correo.com",
			roles=["RT Cajero"],
			invoice_row=inv_ok,
			user_row=target,
		)
		with self.assertRaises(PermissionError):
			mod_unauth.transfer_pos_invoice_owner("ACC-PSINV-4", "ligia@correo.com")
		self.assertEqual(updates_unauth, [])

	def test_hooks_registers_pos_invoice_doctype_js(self):
		from retail_tools import hooks

		self.assertEqual(hooks.doctype_js.get("POS Invoice"), "public/js/pos_invoice.js")


if __name__ == "__main__":
	unittest.main()
