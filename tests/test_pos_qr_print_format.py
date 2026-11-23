"""Tests for Retail Tools Settings, POS QR helper, and editable POS Invoice Print Format."""

import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "retail_tools"


class PosQrPrintFormatTest(unittest.TestCase):
	def test_normalize_qr_url(self):
		from retail_tools.utils.qr import normalize_qr_url

		self.assertEqual(normalize_qr_url(""), "")
		self.assertEqual(normalize_qr_url(None), "")
		self.assertEqual(
			normalize_qr_url("https://www.instagram.com/puntoaccesorios/"),
			"https://www.instagram.com/puntoaccesorios/",
		)
		self.assertEqual(
			normalize_qr_url("www.puntoaccesorios.com"),
			"https://www.puntoaccesorios.com",
		)
		self.assertEqual(
			normalize_qr_url("https://wa.me/50588888888"),
			"https://wa.me/50588888888",
		)
		with self.assertRaises(ValueError):
			normalize_qr_url("not a url")
		with self.assertRaises(ValueError):
			normalize_qr_url("ftp://example.com")

	def test_retail_tools_settings_doctype_schema(self):
		path = APP / "retail_tools/doctype/retail_tools_settings/retail_tools_settings.json"
		doc = json.loads(path.read_text(encoding="utf-8"))
		self.assertEqual(doc["name"], "Retail Tools Settings")
		self.assertEqual(doc["issingle"], 1)
		fieldnames = {f["fieldname"] for f in doc["fields"]}
		self.assertTrue({"qr_url", "qr_subtitle", "qr_label", "pos_footer_message"}.issubset(fieldnames))
		roles = {p["role"] for p in doc["permissions"]}
		self.assertIn("System Manager", roles)
		self.assertIn("RT Cajero", roles)
		self.assertIn("RT Responsable de Tienda", roles)

	def test_get_pos_qr_context_reads_settings(self):
		from retail_tools.utils import qr

		fake_frappe = types.ModuleType("frappe")
		fake_frappe.db = types.SimpleNamespace(
			exists=lambda dt, name: dt == "DocType" and name == "Retail Tools Settings",
			get_singles_dict=lambda dt: {
				"qr_url": "https://www.puntoaccesorios.com",
				"qr_subtitle": "www.puntoaccesorios.com",
				"qr_label": "¡Visítanos!",
				"pos_footer_message": "Gracias",
			},
		)

		with (
			mock.patch.dict(sys.modules, {"frappe": fake_frappe}),
			mock.patch.object(qr, "get_qr_data_uri", return_value="data:image/svg+xml;base64,ABC") as mocked_qr,
		):
			ctx = qr.get_pos_qr_context()

		mocked_qr.assert_called_once_with("https://www.puntoaccesorios.com")
		self.assertEqual(ctx["qr_url"], "https://www.puntoaccesorios.com")
		self.assertEqual(ctx["qr_subtitle"], "www.puntoaccesorios.com")
		self.assertEqual(ctx["qr_label"], "¡Visítanos!")
		self.assertEqual(ctx["pos_footer_message"], "Gracias")
		self.assertEqual(ctx["qr_data_uri"], "data:image/svg+xml;base64,ABC")

	def test_print_format_template_uses_jinja_qr_helper(self):
		from retail_tools.utils.pos_print_format import (
			POS_INVOICE_PRINT_FORMAT_CSS,
			POS_INVOICE_PRINT_FORMAT_HTML,
			POS_INVOICE_PRINT_FORMAT_NAME,
		)

		self.assertEqual(POS_INVOICE_PRINT_FORMAT_NAME, "Factura POS con QR")
		self.assertIn("get_pos_qr_context()", POS_INVOICE_PRINT_FORMAT_HTML)
		self.assertIn("rt.qr_data_uri", POS_INVOICE_PRINT_FORMAT_HTML)
		self.assertIn("Item Barcode", POS_INVOICE_PRINT_FORMAT_HTML)
		self.assertIn("Loyalty Point Entry", POS_INVOICE_PRINT_FORMAT_HTML)
		self.assertIn("Saldo disponible:", POS_INVOICE_PRINT_FORMAT_HTML)
		self.assertNotIn("frappe.utils.get_fullname", POS_INVOICE_PRINT_FORMAT_HTML)
		self.assertIn("rt-pos-qr-img", POS_INVOICE_PRINT_FORMAT_CSS)

	def test_hooks_registers_jinja_methods(self):
		from retail_tools import hooks

		self.assertIn("retail_tools.utils.qr.get_pos_qr_context", hooks.jinja["methods"])
		self.assertIn("retail_tools.utils.qr.get_qr_data_uri", hooks.jinja["methods"])

	def test_setup_pos_invoice_print_format_is_editable_and_idempotent(self):
		inserted = []

		class FakeDoc:
			def __init__(self, payload):
				self.payload = payload

			def insert(self, ignore_permissions=False):
				inserted.append((self.payload, ignore_permissions))

		fake_frappe = types.ModuleType("frappe")
		fake_custom_field = types.ModuleType("frappe.custom.doctype.custom_field.custom_field")
		fake_custom_field.create_custom_fields = lambda *a, **kw: None
		fake_utils = types.ModuleType("frappe.utils")
		fake_utils.cint = int

		exists_state = {"Print Format": False}
		fake_frappe.db = types.SimpleNamespace(
			exists=lambda dt, name: True if dt == "DocType" else exists_state.get(dt, False)
		)
		fake_frappe.get_doc = lambda payload: FakeDoc(payload)

		with mock.patch.dict(
			sys.modules,
			{
				"frappe": fake_frappe,
				"frappe.custom": types.ModuleType("frappe.custom"),
				"frappe.custom.doctype": types.ModuleType("frappe.custom.doctype"),
				"frappe.custom.doctype.custom_field": types.ModuleType("frappe.custom.doctype.custom_field"),
				"frappe.custom.doctype.custom_field.custom_field": fake_custom_field,
				"frappe.utils": fake_utils,
			},
		):
			sys.modules.pop("retail_tools.setup", None)
			from retail_tools import setup

			# First run creates editable (standard='No') Print Format
			setup.setup_pos_invoice_print_format()
			self.assertEqual(len(inserted), 1)
			payload, ignore_perm = inserted[0]
			self.assertTrue(ignore_perm)
			self.assertEqual(payload["doc_type"], "POS Invoice")
			self.assertEqual(payload["standard"], "No")
			self.assertEqual(payload["custom_format"], 1)

			# Second run does NOT overwrite user edits
			exists_state["Print Format"] = True
			setup.setup_pos_invoice_print_format()
			self.assertEqual(len(inserted), 1)


if __name__ == "__main__":
	unittest.main()
