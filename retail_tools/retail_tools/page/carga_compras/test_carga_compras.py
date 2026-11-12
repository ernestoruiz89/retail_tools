# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

from __future__ import annotations

import base64
import io
import os
from unittest.mock import patch

import frappe
import openpyxl
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from retail_tools.retail_tools.page.carga_compras.carga_compras import (
	TEMPLATE_HEADERS,
	build_template_xlsx_bytes,
	confirm_purchase_upload,
	download_template,
	get_initial_data,
	preview_purchase_upload,
)


def _make_xlsx_b64(headers: list[str], rows: list[list], sheet_title: str = "Hoja1") -> str:
	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = sheet_title
	ws.append(headers)
	for r in rows:
		ws.append(r)
	buf = io.BytesIO()
	wb.save(buf)
	wb.close()
	return base64.b64encode(buf.getvalue()).decode("ascii")


class TestCargaCompras(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls._setup_test_fixtures()

	@classmethod
	def _setup_test_fixtures(cls):
		# Ensure Stock Settings defaults
		frappe.db.set_single_value("Stock Settings", "item_naming_by", "Item Code")
		frappe.db.set_single_value("Buying Settings", "po_required", "No")
		frappe.db.set_single_value("Buying Settings", "pr_required", "No")

		cls.company = (
			frappe.defaults.get_user_default("Company")
			or frappe.db.get_single_value("Global Defaults", "default_company")
			or frappe.get_all("Company", pluck="name", limit=1)[0]
		)
		cls.currency = frappe.db.get_value("Company", cls.company, "default_currency") or "NIO"

		# Ensure UOMs exist
		for uom_name in ("Nos", "Unit", "Box", "Pair"):
			if not frappe.db.exists("UOM", uom_name):
				frappe.get_doc(
					{"doctype": "UOM", "uom_name": uom_name, "enabled": 1, "must_be_whole_number": 0}
				).insert(ignore_permissions=True)

		cls.default_uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos"
		if not frappe.db.exists("UOM", cls.default_uom):
			cls.default_uom = "Nos"
			frappe.db.set_single_value("Stock Settings", "stock_uom", cls.default_uom)

		# Ensure Item Groups exist
		root_group = (
			"All Item Groups"
			if frappe.db.exists("Item Group", "All Item Groups")
			else (
				frappe.db.get_value(
					"Item Group", {"is_group": 1, "parent_item_group": ["in", ["", None]]}, "name"
				)
				or frappe.get_all("Item Group", pluck="name", limit=1)[0]
			)
		)
		for ig_name in ("Productos Test RT", "Joyeria Test RT"):
			if not frappe.db.exists("Item Group", ig_name):
				frappe.get_doc(
					{
						"doctype": "Item Group",
						"item_group_name": ig_name,
						"parent_item_group": root_group,
						"is_group": 0,
					}
				).insert(ignore_permissions=True)

		cls.default_group = "Productos Test RT"
		cls.alt_group = "Joyeria Test RT"
		frappe.db.set_single_value("Stock Settings", "item_group", cls.default_group)

		# Ensure Supplier exists
		cls.supplier = "Proveedor PACC Test RT"
		if not frappe.db.exists("Supplier", cls.supplier):
			sup_group = (
				frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
				or frappe.get_all("Supplier Group", pluck="name", limit=1)[0]
			)
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": cls.supplier,
					"supplier_group": sup_group,
				}
			).insert(ignore_permissions=True)

		# Ensure leaf Warehouse exists for company
		cls.warehouse = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 0, "disabled": 0}, "name"
		)
		if not cls.warehouse:
			parent_wh = frappe.db.get_value(
				"Warehouse", {"company": cls.company, "is_group": 1}, "name"
			)
			wh_doc = frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "Almacen Compras RT",
					"company": cls.company,
					"parent_warehouse": parent_wh,
					"is_group": 0,
				}
			).insert(ignore_permissions=True)
			cls.warehouse = wh_doc.name

		# Ensure Selling Price Lists 1 & 2 and a Buying/Disabled Price List for tests
		for pl_name, selling, buying, enabled in (
			("Lista Venta 1 RT", 1, 0, 1),
			("Lista Venta 2 RT", 1, 0, 1),
			("Lista Compra RT", 0, 1, 1),
			("Lista Deshabilitada RT", 1, 0, 0),
		):
			if not frappe.db.exists("Price List", pl_name):
				frappe.get_doc(
					{
						"doctype": "Price List",
						"price_list_name": pl_name,
						"currency": cls.currency,
						"selling": selling,
						"buying": buying,
						"enabled": enabled,
					}
				).insert(ignore_permissions=True)
			else:
				frappe.db.set_value(
					"Price List",
					pl_name,
					{"selling": selling, "buying": buying, "enabled": enabled, "currency": cls.currency},
				)

		cls.pl_1 = "Lista Venta 1 RT"
		cls.pl_2 = "Lista Venta 2 RT"
		cls.pl_buying = "Lista Compra RT"
		cls.pl_disabled = "Lista Deshabilitada RT"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Stock Settings", "item_naming_by", "Item Code")
		frappe.db.set_single_value("Stock Settings", "stock_uom", self.default_uom)
		frappe.db.set_single_value("Stock Settings", "item_group", self.default_group)
		frappe.db.set_single_value("Buying Settings", "po_required", "No")
		frappe.db.set_single_value("Buying Settings", "pr_required", "No")

	def _base_header(self, **overrides) -> dict:
		hdr = {
			"company": self.company,
			"supplier": self.supplier,
			"posting_date": today(),
			"warehouse": self.warehouse,
			"bill_no": "",
			"price_list_1": self.pl_1,
			"price_list_2": self.pl_2,
		}
		hdr.update(overrides)
		return hdr

	def test_01_download_template_and_initial_data(self):
		init_res = get_initial_data(company=self.company)
		self.assertTrue(init_res["ok"])
		self.assertEqual(init_res["defaults"]["company"], self.company)
		self.assertEqual(tuple(init_res["template_headers"]), TEMPLATE_HEADERS)

		dl_res = download_template()
		self.assertTrue(dl_res["ok"])
		content = frappe.local.response.filecontent
		wb = openpyxl.load_workbook(io.BytesIO(content))
		ws = wb["Hoja1"]
		row_1 = [ws.cell(row=1, column=i).value for i in range(1, 8)]
		self.assertEqual(tuple(row_1), TEMPLATE_HEADERS)
		self.assertEqual(ws.cell(row=2, column=1).number_format, "@")
		self.assertEqual(ws.cell(row=2, column=3).number_format, "@")
		wb.close()

	def test_02_headers_text_preservation_and_price_list_rules(self):
		# Test accented headers, leading zeros in codes/barcodes, 1 vs 2 price columns, empty vs 0
		headers = [
			"Código de Producto",
			"Nombre del Producto",
			"Código de Barras",
			"Cantidad",
			"Costo Unitario",
			"Precio de Venta 1",
			"Precio de Venta 2",
		]
		rows = [
			["0074301", "Articulo Cero Inicial", "00998877", 10, 25.5, 0, None],
		]
		b64 = _make_xlsx_b64(headers, rows)

		# Price 1 has value 0 -> requires price_list_1; Price 2 is empty -> does NOT require price_list_2
		res_missing_pl1 = preview_purchase_upload(
			file_content=b64,
			header=self._base_header(price_list_1="", price_list_2=""),
		)
		self.assertFalse(res_missing_pl1["can_confirm"])
		self.assertTrue(
			any("Lista de Precios 1" in e for e in res_missing_pl1["global_errors"])
		)

		# Providing only price_list_1 succeeds when column 2 is empty
		res_ok = preview_purchase_upload(
			file_content=b64,
			header=self._base_header(price_list_1=self.pl_1, price_list_2=""),
		)
		self.assertTrue(res_ok["can_confirm"], msg=str(res_ok["global_errors"]))
		row0 = res_ok["rows"][0]
		self.assertEqual(row0["item_code"], "0074301")
		self.assertEqual(row0["barcode"], "00998877")
		self.assertEqual(row0["price_1"], 0.0)
		self.assertEqual(row0["price_1_info"]["action"], "create")
		self.assertIsNone(row0["price_2"])
		self.assertEqual(row0["price_2_info"]["action"], "none")

		# When both columns have values, require distinct enabled selling price lists
		rows_both = [["0074301", "Articulo Cero Inicial", "00998877", 10, 25.5, 50, 100]]
		b64_both = _make_xlsx_b64(list(TEMPLATE_HEADERS), rows_both)

		res_same_pl = preview_purchase_upload(
			file_content=b64_both,
			header=self._base_header(price_list_1=self.pl_1, price_list_2=self.pl_1),
		)
		self.assertFalse(res_same_pl["can_confirm"])
		self.assertTrue(any("distintas" in e for e in res_same_pl["global_errors"]))

		res_buying_pl = preview_purchase_upload(
			file_content=b64_both,
			header=self._base_header(price_list_1=self.pl_1, price_list_2=self.pl_buying),
		)
		self.assertFalse(res_buying_pl["can_confirm"])
		self.assertTrue(any("venta" in e for e in res_buying_pl["global_errors"]))

		res_disabled_pl = preview_purchase_upload(
			file_content=b64_both,
			header=self._base_header(price_list_1=self.pl_disabled, price_list_2=self.pl_2),
		)
		self.assertFalse(res_disabled_pl["can_confirm"])
		self.assertTrue(any("deshabilitada" in e for e in res_disabled_pl["global_errors"]))

	def test_03_duplicate_codes_conflicting_barcodes_and_invalid_numbers(self):
		# Create an existing item with a known barcode
		if not frappe.db.exists("Item", "RT-EXIST-BC"):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": "RT-EXIST-BC",
					"item_name": "Producto Existente Con Barra",
					"item_group": self.default_group,
					"stock_uom": self.default_uom,
					"is_stock_item": 1,
					"barcodes": [{"barcode": "BC-TAKEN-999"}],
				}
			).insert(ignore_permissions=True)

		rows = [
			["RT-DUP-1", "Dup 1", "BC-DUP-FILE", 5, 10, 20, 30],
			["RT-DUP-1", "Dup 2", "BC-DUP-FILE", 0, -5, "abc", -10],
			["RT-NEW-BC-ERR", "Conflicto Barra BD", "BC-TAKEN-999", 2, 15, 25, 35],
		]
		b64 = _make_xlsx_b64(list(TEMPLATE_HEADERS), rows)
		res = preview_purchase_upload(file_content=b64, header=self._base_header())
		self.assertFalse(res["can_confirm"])

		r0_errs = " | ".join(res["rows"][0]["errors"])
		r1_errs = " | ".join(res["rows"][1]["errors"])
		r2_errs = " | ".join(res["rows"][2]["errors"])

		self.assertIn("repetido", r0_errs)
		self.assertIn("Cantidad debe ser mayor que cero", r1_errs)
		self.assertIn("Costo no puede ser negativo", r1_errs)
		self.assertIn("Precio Venta 1 no es un número válido", r1_errs)
		self.assertIn("Precio Venta 2 no puede ser negativo", r1_errs)
		self.assertIn("RT-EXIST-BC", r2_errs)

	def test_04_existing_items_uom_lock_and_metadata_preservation(self):
		# 1. Existing item WITHOUT stock movements -> UOM is editable, group is editable, name & barcode preserved
		code_no_sle = "RT-EX-NOSLE"
		if not frappe.db.exists("Item", code_no_sle):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code_no_sle,
					"item_name": "Nombre Original Intacto",
					"item_group": self.default_group,
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"barcodes": [{"barcode": "BC-ORIG-NOSLE"}],
				}
			).insert(ignore_permissions=True)

		rows = [[code_no_sle, "Nombre Excel Ignorado", "BC-EXCEL-IGNORED", 4, 20.0, 40.0, 80.0]]
		b64 = _make_xlsx_b64(list(TEMPLATE_HEADERS), rows)
		overrides = {"2": {"item_group": self.alt_group, "stock_uom": "Pair"}}

		prev = preview_purchase_upload(
			file_content=b64,
			header=self._base_header(),
			row_overrides=overrides,
		)
		self.assertTrue(prev["can_confirm"], msg=str(prev["global_errors"]))
		self.assertFalse(prev["rows"][0]["uom_locked"])
		self.assertEqual(prev["rows"][0]["item_group"], self.alt_group)
		self.assertEqual(prev["rows"][0]["stock_uom"], "Pair")

		conf = confirm_purchase_upload(
			file_content=b64,
			header=self._base_header(),
			row_overrides=overrides,
			preview_token=prev["preview_token"],
			upload_id="upl-test-04-nosle",
		)
		self.assertTrue(conf["ok"], msg=str(conf))

		updated_doc = frappe.get_doc("Item", code_no_sle)
		self.assertEqual(updated_doc.item_name, "Nombre Original Intacto")
		self.assertEqual(updated_doc.item_group, self.alt_group)
		self.assertEqual(updated_doc.stock_uom, "Pair")
		self.assertEqual([b.barcode for b in updated_doc.barcodes], ["BC-ORIG-NOSLE"])

		# 2. Now code_no_sle HAS stock movements from the submitted Purchase Invoice -> UOM must be locked!
		prev_after_sle = preview_purchase_upload(
			file_content=b64,
			header=self._base_header(),
			row_overrides={"2": {"item_group": self.default_group, "stock_uom": "Box"}},
		)
		self.assertFalse(prev_after_sle["can_confirm"])
		self.assertTrue(prev_after_sle["rows"][0]["uom_locked"])
		self.assertTrue(
			any("movimientos de inventario" in e for e in prev_after_sle["rows"][0]["errors"])
		)

	def test_05_same_day_two_uploads_and_price_updates(self):
		code = "RT-PRICE-2X"
		rows_1 = [[code, "Producto Doble Carga", "BC-PRICE-2X", 5, 10.0, 25.0, 50.0]]
		b64_1 = _make_xlsx_b64(list(TEMPLATE_HEADERS), rows_1)

		prev_1 = preview_purchase_upload(file_content=b64_1, header=self._base_header())
		self.assertTrue(prev_1["can_confirm"])
		conf_1 = confirm_purchase_upload(
			file_content=b64_1,
			header=self._base_header(),
			preview_token=prev_1["preview_token"],
			upload_id="upl-test-05-first",
		)
		self.assertTrue(conf_1["ok"])
		self.assertEqual(conf_1["summary"]["created_items"], 1)
		self.assertEqual(conf_1["summary"]["created_prices"], 2)

		# Second upload on the SAME day: Price 1 unchanged (25.0), Price 2 changed (50.0 -> 65.0)
		rows_2 = [[code, "Producto Doble Carga", "BC-PRICE-2X", 3, 12.0, 25.0, 65.0]]
		b64_2 = _make_xlsx_b64(list(TEMPLATE_HEADERS), rows_2)

		prev_2 = preview_purchase_upload(file_content=b64_2, header=self._base_header())
		self.assertTrue(prev_2["can_confirm"], msg=str(prev_2["global_errors"]))
		self.assertEqual(prev_2["rows"][0]["price_1_info"]["action"], "unchanged")
		self.assertEqual(prev_2["rows"][0]["price_2_info"]["action"], "update")

		conf_2 = confirm_purchase_upload(
			file_content=b64_2,
			header=self._base_header(),
			preview_token=prev_2["preview_token"],
			upload_id="upl-test-05-second",
		)
		self.assertTrue(conf_2["ok"], msg=str(conf_2))
		self.assertEqual(conf_2["summary"]["created_items"], 0)
		self.assertEqual(conf_2["summary"]["created_prices"], 0)
		self.assertEqual(conf_2["summary"]["updated_prices"], 1)
		self.assertEqual(conf_2["summary"]["unchanged_prices"], 1)

		# Verify only ONE Item Price record exists per list for this item
		p1_docs = frappe.get_all(
			"Item Price",
			filters={"item_code": code, "price_list": self.pl_1},
			fields=["name", "price_list_rate", "valid_from"],
		)
		p2_docs = frappe.get_all(
			"Item Price",
			filters={"item_code": code, "price_list": self.pl_2},
			fields=["name", "price_list_rate", "valid_from"],
		)
		self.assertEqual(len(p1_docs), 1)
		self.assertEqual(flt(p1_docs[0].price_list_rate), 25.0)
		self.assertEqual(str(p1_docs[0].valid_from), today())
		self.assertEqual(len(p2_docs), 1)
		self.assertEqual(flt(p2_docs[0].price_list_rate), 65.0)
		self.assertEqual(str(p2_docs[0].valid_from), today())

	def test_06_stale_preview_double_confirm_permissions_and_rollback(self):
		code = "RT-TX-GUARD"
		rows = [[code, "Producto Guardas", "BC-TX-GUARD", 2, 15.0, 30.0, 60.0]]
		b64 = _make_xlsx_b64(list(TEMPLATE_HEADERS), rows)

		prev = preview_purchase_upload(file_content=b64, header=self._base_header())
		self.assertTrue(prev["can_confirm"])

		# 1. Stale preview detection when token is outdated
		stale_res = confirm_purchase_upload(
			file_content=b64,
			header=self._base_header(),
			preview_token="invalid-or-outdated-token",
			upload_id="upl-test-06-stale",
		)
		self.assertFalse(stale_res["ok"])
		self.assertEqual(stale_res["error_code"], "STALE_PREVIEW")
		self.assertFalse(frappe.db.exists("Item", code))

		# 2. Insufficient permissions check
		with patch("frappe.has_permission", side_effect=lambda doctype, ptype="read", *a, **kw: False if ptype == "submit" else True):
			perm_res = confirm_purchase_upload(
				file_content=b64,
				header=self._base_header(),
				preview_token=prev["preview_token"],
				upload_id="upl-test-06-perm",
			)
			self.assertFalse(perm_res["ok"])
			self.assertEqual(perm_res["error_code"], "VALIDATION_ERROR")
			self.assertFalse(frappe.db.exists("Item", code))

		# 3. Full rollback when Purchase Invoice submit fails
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

		with patch.object(PurchaseInvoice, "submit", side_effect=frappe.ValidationError("Fallo simulado al enviar factura")):
			fail_res = confirm_purchase_upload(
				file_content=b64,
				header=self._base_header(),
				preview_token=prev["preview_token"],
				upload_id="upl-test-06-rollback",
			)
			self.assertFalse(fail_res["ok"])
			self.assertEqual(fail_res["error_code"], "TRANSACTION_FAILED")

		# Verify item and prices were completely rolled back
		self.assertFalse(frappe.db.exists("Item", code))
		self.assertEqual(frappe.db.count("Item Price", {"item_code": code}), 0)

		# 4. Successful confirm followed by double confirmation with same upload_id
		ok_res = confirm_purchase_upload(
			file_content=b64,
			header=self._base_header(),
			preview_token=prev["preview_token"],
			upload_id="upl-test-06-idempotent",
		)
		self.assertTrue(ok_res["ok"])
		first_pi = ok_res["invoice_name"]

		dup_res = confirm_purchase_upload(
			file_content=b64,
			header=self._base_header(),
			preview_token=prev["preview_token"],
			upload_id="upl-test-06-idempotent",
		)
		self.assertFalse(dup_res["ok"])
		self.assertTrue(dup_res.get("already_processed"))
		self.assertEqual(dup_res["error_code"], "DUPLICATE_UPLOAD")
		self.assertEqual(dup_res["invoice_name"], first_pi)

	def test_07_import_123_row_pacc_sample_workbook(self):
		sample_candidates = [
			"/mnt/c/Users/Ernesto/Downloads/Plantilla Producto PACC (para importar).xlsx",
			r"C:\Users\Ernesto\Downloads\Plantilla Producto PACC (para importar).xlsx",
		]
		sample_path = next((p for p in sample_candidates if os.path.exists(p)), None)
		if sample_path:
			with open(sample_path, "rb") as f:
				sample_bytes = f.read()
			b64 = base64.b64encode(sample_bytes).decode("ascii")
		else:
			headers = [
				"Codigo Producto",
				"Producto",
				"Codigo de Barra",
				"Cantidad",
				"Costo",
				"Precio Venta 1",
				"Precio Venta 2",
			]
			rows = [
				["74300013", "Pulsera CM", "74300013", 87, 25.5, 52, 104],
			]
			for idx in range(2, 123):
				code = f"743{idx:05d}"
				rows.append([code, f"Producto PACC {idx}", code, 5, 20.0, 40.0, 80.0])
			rows.append(["74301232", "Arete CM", "74301232", 12, 95.0, 180.0, 360.0])
			b64 = _make_xlsx_b64(headers, rows)
		header = self._base_header(bill_no="FAC-PACC-123")

		prev = preview_purchase_upload(
			file_content=b64,
			filename="Plantilla Producto PACC (para importar).xlsx",
			header=header,
		)
		self.assertTrue(prev["can_confirm"], msg=str(prev["global_errors"]))
		self.assertEqual(prev["summary"]["total_rows"], 123)
		self.assertEqual(prev["summary"]["rows_with_errors"], 0)

		conf = confirm_purchase_upload(
			file_content=b64,
			filename="Plantilla Producto PACC (para importar).xlsx",
			header=header,
			preview_token=prev["preview_token"],
			upload_id="upl-pacc-123-rows",
		)
		self.assertTrue(conf["ok"], msg=str(conf))
		pi_name = conf["invoice_name"]

		pi_doc = frappe.get_doc("Purchase Invoice", pi_name)
		self.assertEqual(pi_doc.docstatus, 1)
		self.assertEqual(pi_doc.update_stock, 1)
		self.assertEqual(pi_doc.is_paid, 0)
		self.assertEqual(len(pi_doc.items), 123)

		# Check attached XLSX file
		attached = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Purchase Invoice",
				"attached_to_name": pi_name,
			},
			fields=["name", "file_name"],
		)
		self.assertEqual(len(attached), 1)

		# Check Stock Ledger Entries created for the Purchase Invoice
		sle_count = frappe.db.count(
			"Stock Ledger Entry",
			{"voucher_type": "Purchase Invoice", "voucher_no": pi_name, "is_cancelled": 0},
		)
		self.assertEqual(sle_count, 123)

		# Check spot items and their prices in both lists
		self.assertTrue(frappe.db.exists("Item", "74300013"))
		self.assertTrue(frappe.db.exists("Item", "74301232"))
		p1_rate = frappe.db.get_value(
			"Item Price", {"item_code": "74300013", "price_list": self.pl_1}, "price_list_rate"
		)
		p2_rate = frappe.db.get_value(
			"Item Price", {"item_code": "74300013", "price_list": self.pl_2}, "price_list_rate"
		)
		self.assertEqual(flt(p1_rate), 52.0)
		self.assertEqual(flt(p2_rate), 104.0)

	def test_08_page_roles_and_navigation_registration(self):
		self.assertTrue(frappe.db.exists("Page", "carga-compras"))
		page_doc = frappe.get_doc("Page", "carga-compras")
		roles = {r.role for r in page_doc.roles}
		for expected_role in (
			"System Manager",
			"Purchase Manager",
			"Purchase User",
			"Stock Manager",
			"Accounts Manager",
		):
			self.assertIn(expected_role, roles)

		ws_doc = frappe.get_doc("Workspace", "Retail Tools")
		shortcut_links = {s.link_to for s in ws_doc.shortcuts}
		self.assertIn("carga-compras", shortcut_links)

	def test_09_import_pacc_barcode_as_item_code_workbook(self):
		sample_candidates = [
			"/mnt/c/Users/Ernesto/Downloads/Plantilla Producto PACC.xlsx",
			r"C:\Users\Ernesto\Downloads\Plantilla Producto PACC.xlsx",
		]
		sample_path = next((p for p in sample_candidates if os.path.exists(p)), None)
		if sample_path:
			with open(sample_path, "rb") as f:
				sample_bytes = f.read()
			b64 = base64.b64encode(sample_bytes).decode("ascii")
		else:
			headers = [
				"Concecutivo",
				"Codigo de Barra",
				"Producto",
				"Cantidad",
				"Costo +envio",
				"PrecioMayorista",
				"PrecioDetalle",
				None,
				None,
				None,
			]
			rows = [
				[7430001, "74300013", "Pulsera CM ", 87, 25.5, 52, 104, None, None, 2.039],
				[7430123, "74301232", "Arete CM", 12, 95, 180, 360, None, None, 1.894],
				[7430124, "74301249", None, None, None, None, 0, None, None, None],
				[7430178, "74301782", None, None, None, None, None, None, None, None],
			]
			b64 = _make_xlsx_b64(headers, rows)

		header = self._base_header(bill_no="FAC-PACC-ORIGINAL")
		prev = preview_purchase_upload(
			file_content=b64,
			filename="Plantilla Producto PACC.xlsx",
			header=header,
		)
		self.assertTrue(prev["can_confirm"], msg=str(prev["global_errors"]))
		self.assertTrue(prev["column_info"].get("barcode_as_item_code"))
		if sample_path:
			self.assertEqual(prev["summary"]["total_rows"], 123)
		self.assertEqual(prev["summary"]["rows_with_errors"], 0)
		self.assertEqual(prev["rows"][0]["item_code"], "74300013")
		self.assertEqual(prev["rows"][0]["barcode"], "74300013")

		conf = confirm_purchase_upload(
			file_content=b64,
			filename="Plantilla Producto PACC.xlsx",
			header=header,
			preview_token=prev["preview_token"],
			upload_id="upl-pacc-barcode-as-code",
		)
		self.assertTrue(conf["ok"], msg=str(conf))
		pi_doc = frappe.get_doc("Purchase Invoice", conf["invoice_name"])
		self.assertEqual(pi_doc.docstatus, 1)
		if sample_path:
			self.assertEqual(len(pi_doc.items), 123)

	def test_10_item_inspector_v16_compatibility(self):
		from frappe.utils import add_days
		from retail_tools.retail_tools.page.item_inspector.item_inspector import (
			get_item_snapshot,
			resolve_item_from_barcode,
		)

		code = "RT-II-V16-001"
		headers = [
			"Codigo Producto",
			"Producto",
			"Codigo de Barra",
			"Cantidad",
			"Costo",
			"Precio Venta 1",
			"Precio Venta 2",
		]
		rows = [[code, "Producto Inspector V16", f"BC-{code}", 4, 25.0, 50.0, 60.0]]
		b64 = _make_xlsx_b64(headers, rows)

		# 1. Invalid due_date (< posting_date) must fail preview
		bad_due = add_days(today(), -5)
		bad_prev = preview_purchase_upload(
			file_content=b64,
			header=self._base_header(due_date=bad_due),
		)
		self.assertFalse(bad_prev["can_confirm"])

		# 2. Empty remarks -> pi_doc.remarks must be empty (not [RT-UPLOAD:...] or auto-remarks),
		#    and default due_date == posting_date
		header = self._base_header(bill_no="FAC-II-V16")
		prev = preview_purchase_upload(file_content=b64, header=header)
		self.assertEqual(str(prev["header"]["due_date"]), str(today()))
		conf = confirm_purchase_upload(
			file_content=b64,
			header=header,
			preview_token=prev["preview_token"],
			upload_id="upl-ii-v16",
		)
		self.assertTrue(conf["ok"])
		pi_empty_rem = frappe.get_doc("Purchase Invoice", conf["invoice_name"])
		self.assertFalse(bool(pi_empty_rem.remarks))
		self.assertEqual(str(pi_empty_rem.due_date), str(today()))

		# 3. Custom remarks and custom due_date -> preserved on Purchase Invoice
		custom_due = add_days(today(), 15)
		header_custom = self._base_header(
			bill_no="FAC-II-V16-2",
			due_date=custom_due,
			remarks="Compra quincenal PACC",
		)
		prev_custom = preview_purchase_upload(file_content=b64, header=header_custom)
		conf_custom = confirm_purchase_upload(
			file_content=b64,
			header=header_custom,
			preview_token=prev_custom["preview_token"],
			upload_id="upl-ii-v16-custom",
		)
		self.assertTrue(conf_custom["ok"])
		pi_custom = frappe.get_doc("Purchase Invoice", conf_custom["invoice_name"])
		self.assertEqual(pi_custom.remarks, "Compra quincenal PACC")
		self.assertEqual(str(pi_custom.due_date), str(custom_due))

		resolved = resolve_item_from_barcode(f"BC-{code}")
		self.assertTrue(resolved["ok"])
		self.assertEqual(resolved["item_code"], code)

		snap = get_item_snapshot(code)
		self.assertTrue(snap["ok"])
		self.assertEqual(snap["item"]["item_code"], code)
		self.assertEqual(len(snap["price_history"]), 2)
		self.assertEqual(len(snap["recent_purchases"]), 2)

	def _create_single_role_user(self, email: str, first_name: str, role_name: str) -> str:
		if not frappe.db.exists("User", email):
			user_doc = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first_name,
					"enabled": 1,
					"user_type": "System User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		else:
			user_doc = frappe.get_doc("User", email)
		user_doc.set("roles", [{"role": role_name}])
		user_doc.save(ignore_permissions=True)
		return email

	def test_11_rt_roles_fixtures_and_user_permissions(self):
		import json
		from retail_tools.retail_tools.page.catalog_generator.catalog_generator import (
			generate_catalog_html,
			get_items_for_catalog,
		)
		from retail_tools.retail_tools.page.customer_lookup.customer_lookup import (
			get_customer_snapshot,
			search_customer,
		)
		from retail_tools.retail_tools.page.item_inspector.item_inspector import (
			get_item_snapshot,
			resolve_item_from_barcode,
		)
		from retail_tools.retail_tools.page.label_generator.label_generator import (
			generate_labels_html,
			get_item_for_label,
			get_items_with_stock,
		)
		from retail_tools.setup import RT_ROLES, setup_roles_and_permissions

		setup_roles_and_permissions()

		for r_name in RT_ROLES:
			self.assertTrue(frappe.db.exists("Role", r_name), f"Falta rol {r_name}")

		# Prepare a baseline item and customer as Administrator
		base_code = "RT-ROLE-TEST-ITEM"
		b64_base = _make_xlsx_b64(
			list(TEMPLATE_HEADERS),
			[[base_code, "Producto Base Roles", "BC-ROLE-BASE", 10, 20.0, 40.0, 50.0]],
		)
		prev_base = preview_purchase_upload(file_content=b64_base, header=self._base_header())
		conf_base = confirm_purchase_upload(
			file_content=b64_base,
			header=self._base_header(),
			preview_token=prev_base["preview_token"],
			upload_id="upl-role-base",
		)
		self.assertTrue(conf_base["ok"])

		cajero_user = self._create_single_role_user("rt_cajero@example.com", "Cajero RT", "RT Cajero")
		tienda_user = self._create_single_role_user(
			"rt_tienda@example.com", "Tienda RT", "RT Responsable de Tienda"
		)
		contador_user = self._create_single_role_user(
			"rt_contador@example.com", "Contador RT", "RT Contador"
		)
		socio_user = self._create_single_role_user("rt_socio@example.com", "Socio RT", "RT Socio")
		admin_user = self._create_single_role_user(
			"rt_admin@example.com", "Admin RT", "RT Administrador de Sistema"
		)

		try:
			# 1. Validate RT Cajero
			frappe.set_user(cajero_user)
			for dt in ("POS Invoice", "Sales Invoice", "POS Opening Entry", "POS Closing Entry"):
				for ptype in ("read", "write", "create", "submit", "print"):
					self.assertTrue(
						frappe.has_permission(dt, ptype),
						f"RT Cajero debe tener permiso {ptype} en {dt}",
					)
			self.assertTrue(frappe.has_permission("Customer", "create"))
			self.assertTrue(frappe.has_permission("Customer", "write"))
			self.assertFalse(frappe.has_permission("Purchase Invoice", "submit"))

			# Create and modify a Customer as RT Cajero (without ignore_permissions!)
			cust_group = (
				frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
				or frappe.get_all("Customer Group", pluck="name", limit=1)[0]
			)
			territory = (
				frappe.db.get_value("Territory", {"is_group": 0}, "name")
				or frappe.get_all("Territory", pluck="name", limit=1)[0]
			)
			cust_doc = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": "Cliente Creado Por Cajero RT",
					"customer_group": cust_group,
					"territory": territory,
				}
			).insert()
			cust_doc.mobile_no = "88887777"
			cust_doc.save()

			# Access item-inspector and customer-lookup as RT Cajero
			self.assertTrue(resolve_item_from_barcode("BC-ROLE-BASE")["ok"])
			self.assertTrue(get_item_snapshot(base_code)["ok"])
			self.assertTrue(search_customer("Cliente Creado")["ok"])
			self.assertTrue(get_customer_snapshot(cust_doc.name)["ok"])
			self.assertTrue(len(frappe.get_list("Item", limit=5)) >= 1)
			with self.assertRaises(frappe.PermissionError):
				get_initial_data()

			# 2. Validate RT Responsable de Tienda
			frappe.set_user(tienda_user)
			init_tienda = get_initial_data(company=self.company)
			self.assertTrue(init_tienda["ok"])
			self.assertTrue(len(frappe.get_list("UOM", limit=5)) >= 1)
			self.assertTrue(len(frappe.get_list("Item Group", limit=5)) >= 1)

			tienda_item = "RT-TIENDA-ITEM-01"
			b64_tienda = _make_xlsx_b64(
				list(TEMPLATE_HEADERS),
				[[tienda_item, "Producto Tienda RT", "BC-TIENDA-01", 6, 30.0, 60.0, 75.0]],
			)
			prev_tienda = preview_purchase_upload(file_content=b64_tienda, header=self._base_header())
			self.assertTrue(prev_tienda["can_confirm"], msg=str(prev_tienda["global_errors"]))
			conf_tienda = confirm_purchase_upload(
				file_content=b64_tienda,
				header=self._base_header(),
				preview_token=prev_tienda["preview_token"],
				upload_id="upl-role-tienda",
			)
			self.assertTrue(conf_tienda["ok"], msg=str(conf_tienda))
			self.assertTrue(get_items_for_catalog()["ok"])
			self.assertTrue(generate_catalog_html()["ok"])
			self.assertTrue(get_items_with_stock()["ok"])
			self.assertTrue(get_item_for_label(tienda_item)["ok"])
			self.assertTrue(
				generate_labels_html(
					items=json.dumps([{"item_code": tienda_item, "qty": 2}]), label_format="2x1"
				)["ok"]
			)

			# 3. Validate RT Contador
			frappe.set_user(contador_user)
			for dt in ("Account", "Journal Entry", "Payment Entry", "Sales Invoice", "Purchase Invoice"):
				self.assertTrue(frappe.has_permission(dt, "read"))
				self.assertTrue(frappe.has_permission(dt, "create"))
			self.assertTrue(get_initial_data(company=self.company)["ok"])
			self.assertTrue(get_item_snapshot(base_code)["ok"])
			self.assertTrue(get_customer_snapshot(cust_doc.name)["ok"])
			self.assertTrue(len(frappe.get_list("Purchase Invoice", limit=5)) >= 1)
			self.assertTrue(len(frappe.get_list("GL Entry", limit=5)) >= 1)

			# 4. Validate RT Socio (Read-Only + Print + Report + Export)
			frappe.set_user(socio_user)
			for dt in (
				"Sales Invoice",
				"POS Invoice",
				"Purchase Invoice",
				"Item",
				"Customer",
				"GL Entry",
				"Account",
			):
				self.assertTrue(frappe.has_permission(dt, "read"), f"RT Socio debe leer {dt}")
				self.assertTrue(frappe.has_permission(dt, "print"), f"RT Socio debe imprimir {dt}")
				self.assertTrue(frappe.has_permission(dt, "report"), f"RT Socio debe ver reportes {dt}")
				self.assertFalse(
					frappe.has_permission(dt, "create"), f"RT Socio NO debe crear {dt}"
				)
				self.assertFalse(
					frappe.has_permission(dt, "write"), f"RT Socio NO debe escribir {dt}"
				)
			self.assertTrue(get_item_snapshot(base_code)["ok"])
			self.assertTrue(get_customer_snapshot(cust_doc.name)["ok"])
			self.assertTrue(generate_catalog_html()["ok"])

			# 5. Validate RT Administrador de Sistema (Full Access)
			frappe.set_user(admin_user)
			self.assertTrue(get_initial_data(company=self.company)["ok"])
			admin_item = "RT-ADMIN-ITEM-01"
			b64_admin = _make_xlsx_b64(
				list(TEMPLATE_HEADERS),
				[[admin_item, "Producto Admin RT", "BC-ADMIN-01", 3, 40.0, 80.0, 95.0]],
			)
			prev_admin = preview_purchase_upload(file_content=b64_admin, header=self._base_header())
			self.assertTrue(prev_admin["can_confirm"], msg=str(prev_admin["global_errors"]))
			conf_admin = confirm_purchase_upload(
				file_content=b64_admin,
				header=self._base_header(),
				preview_token=prev_admin["preview_token"],
				upload_id="upl-role-admin",
			)
			self.assertTrue(conf_admin["ok"], msg=str(conf_admin))
		finally:
			frappe.set_user("Administrator")



