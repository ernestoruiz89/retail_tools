"""
Carga de Compras desde Excel - Backend API

Permite analizar una plantilla Excel de compras, revisar y ajustar unidad de medida
y grupo de artículos por fila, crear o actualizar productos y precios de venta en hasta
dos listas, y registrar y enviar (submit) una única Purchase Invoice con update_stock=1
dentro de una sola transacción atómica.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import unicodedata
import urllib.parse
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, today

TEMPLATE_HEADERS = (
	"Codigo Producto",
	"Producto",
	"Codigo de Barra",
	"Cantidad",
	"Costo",
	"Precio Venta 1",
	"Precio Venta 2",
)

HEADER_ALIASES = {
	"item_code": {
		"codigo_producto",
		"codigo_de_producto",
		"cod_producto",
		"codigo_articulo",
		"codigo_de_articulo",
		"codigo",
		"item_code",
		"code",
	},
	"item_name": {
		"producto",
		"nombre_producto",
		"nombre_del_producto",
		"nombre_articulo",
		"nombre_del_articulo",
		"nombre",
		"descripcion",
		"item_name",
		"name",
	},
	"barcode": {
		"codigo_de_barra",
		"codigo_de_barras",
		"codigo_barra",
		"codigo_barras",
		"cod_barra",
		"cod_barras",
		"barra",
		"barras",
		"barcode",
	},
	"qty": {
		"cantidad",
		"cant",
		"qty",
		"quantity",
		"unidades",
	},
	"rate": {
		"costo",
		"costo_unitario",
		"costo_unit",
		"costo_envio",
		"costo_mas_envio",
		"costo_con_envio",
		"precio_compra",
		"precio_de_compra",
		"rate",
		"cost",
		"unit_cost",
	},
	"price_1": {
		"precio_venta_1",
		"precio_de_venta_1",
		"precio_1",
		"lista_1",
		"precio_lista_1",
		"precio_venta",
		"precio_de_venta",
		"precio",
		"preciomayorista",
		"precio_mayorista",
		"precio_al_por_mayor",
		"mayorista",
		"price_1",
		"selling_price_1",
	},
	"price_2": {
		"precio_venta_2",
		"precio_de_venta_2",
		"precio_2",
		"lista_2",
		"precio_lista_2",
		"preciodetalle",
		"precio_detalle",
		"precio_al_detalle",
		"detalle",
		"price_2",
		"selling_price_2",
	},
}

REQUIRED_COLUMNS = ("item_code", "item_name", "qty", "rate")

ALLOWED_PAGE_ROLES = {
	"System Manager",
	"Purchase Manager",
	"Purchase User",
	"Stock Manager",
	"Accounts Manager",
	"Administrator",
}


def _normalize_header(value: object) -> str:
	normalized = unicodedata.normalize("NFKD", cstr(value or ""))
	ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
	cleaned = re.sub(r"[^a-z0-9]+", "_", ascii_value.strip().lower())
	return cleaned.strip("_")


def _is_empty_cell(value: object) -> bool:
	if value is None:
		return True
	if isinstance(value, str) and value.strip() == "":
		return True
	return False


def _cell_to_text_code(value: object) -> tuple[str, str | None]:
	"""Convert a cell value into an exact text code without scientific notation or .0 suffix."""
	if _is_empty_cell(value):
		return "", None
	if isinstance(value, bool):
		return "", _("Valor booleano inválido para código")
	if isinstance(value, str):
		return value.strip(), None
	if isinstance(value, int):
		return str(value), None
	if isinstance(value, float):
		if math.isnan(value) or math.isinf(value):
			return "", _("Valor numérico inválido para código")
		if value.is_integer():
			return str(int(value)), None
		try:
			dec = Decimal(str(value))
			return format(dec.normalize(), "f"), None
		except InvalidOperation:
			return cstr(value).strip(), None
	if isinstance(value, Decimal):
		if value == value.to_integral_value():
			return str(int(value)), None
		return format(value.normalize(), "f"), None
	return "", _("Formato de celda inválido para código")


def _parse_numeric_cell(
	value: object,
	field_label: str,
	*,
	allow_empty: bool = False,
	allow_zero: bool = True,
) -> tuple[float | None, str | None]:
	"""Parse a numeric Excel cell distinguishing empty vs 0 and rejecting invalid values."""
	if _is_empty_cell(value):
		if allow_empty:
			return None, None
		return None, _("{0} es obligatorio").format(field_label)

	if isinstance(value, bool):
		return None, _("{0} tiene un valor inválido").format(field_label)

	num: float
	if isinstance(value, (int, float, Decimal)):
		num = float(value)
	elif isinstance(value, str):
		raw = value.strip()
		if not raw:
			if allow_empty:
				return None, None
			return None, _("{0} es obligatorio").format(field_label)
		# Reject strings with letters or invalid symbols (allow optional currency/commas/spaces)
		cleaned = raw.replace(",", "")
		if not re.match(r"^[-+]?\d+(\.\d+)?$", cleaned):
			return None, _("{0} no es un número válido ({1})").format(field_label, raw)
		try:
			num = float(cleaned)
		except ValueError:
			return None, _("{0} no es un número válido ({1})").format(field_label, raw)
	else:
		return None, _("{0} tiene un formato inválido").format(field_label)

	if math.isnan(num) or math.isinf(num):
		return None, _("{0} no es un número válido").format(field_label)

	if allow_zero:
		if num < 0:
			return None, _("{0} no puede ser negativo").format(field_label)
	else:
		if num <= 0:
			return None, _("{0} debe ser mayor que cero").format(field_label)

	return flt(num), None


def _parse_json_arg(value: object, default: object) -> object:
	if value is None or value == "":
		return default
	if isinstance(value, (dict, list)):
		return value
	if isinstance(value, str):
		try:
			return json.loads(value)
		except Exception:
			return default
	return default


def _has_page_access() -> bool:
	user = frappe.session.user
	if not user or user == "Guest":
		return False
	user_roles = set(frappe.get_roles(user))
	if user_roles & ALLOWED_PAGE_ROLES:
		return True
	return bool(
		frappe.has_permission("Purchase Invoice", "create")
		or frappe.has_permission("Purchase Invoice", "submit")
	)


def _ensure_page_access() -> None:
	if not _has_page_access():
		frappe.throw(_("No tiene permisos para acceder a la carga de compras."), frappe.PermissionError)


def _is_bill_no_mandatory() -> bool:
	try:
		meta = frappe.get_meta("Purchase Invoice")
		df = meta.get_field("bill_no")
		if df and cint(df.reqd):
			return True
	except Exception:
		pass

	try:
		buying_meta = frappe.get_meta("Buying Settings")
		for fname in ("bill_no_mandatory", "require_supplier_invoice_no"):
			if buying_meta.has_field(fname) and cint(frappe.db.get_single_value("Buying Settings", fname)):
				return True
	except Exception:
		pass

	return False


def _get_user_permissions_summary() -> dict:
	return {
		"pi_create": bool(frappe.has_permission("Purchase Invoice", "create")),
		"pi_submit": bool(frappe.has_permission("Purchase Invoice", "submit")),
		"item_create": bool(frappe.has_permission("Item", "create")),
		"item_write": bool(frappe.has_permission("Item", "write")),
		"item_price_create": bool(frappe.has_permission("Item Price", "create")),
		"item_price_write": bool(frappe.has_permission("Item Price", "write")),
	}


@frappe.whitelist()
def get_initial_data(company: str | None = None) -> dict:
	"""Return initial defaults, settings, and permission flags for the Carga de Compras page."""
	_ensure_page_access()

	default_company = (
		cstr(company or "").strip()
		or frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)
	if not default_company:
		companies = frappe.get_all("Company", pluck="name", order_by="name asc", limit=1)
		default_company = companies[0] if companies else ""

	default_warehouse = ""
	if default_company:
		default_warehouse = (
			frappe.db.get_value(
				"Warehouse",
				{"company": default_company, "is_group": 0, "disabled": 0},
				"name",
			)
			or ""
		)

	default_stock_uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or ""
	default_item_group = frappe.db.get_single_value("Stock Settings", "item_group") or ""
	item_naming_by = frappe.db.get_single_value("Stock Settings", "item_naming_by") or "Item Code"

	default_price_list_1 = frappe.db.get_single_value("Selling Settings", "selling_price_list") or ""
	if default_price_list_1:
		pl_valid = frappe.db.get_value(
			"Price List",
			{"name": default_price_list_1, "enabled": 1, "selling": 1},
			"name",
		)
		if not pl_valid:
			default_price_list_1 = ""

	return {
		"ok": True,
		"defaults": {
			"company": default_company,
			"posting_date": today(),
			"due_date": today(),
			"warehouse": default_warehouse,
			"stock_uom": default_stock_uom,
			"item_group": default_item_group,
			"price_list_1": default_price_list_1,
			"price_list_2": "",
			"remarks": "",
		},
		"settings": {
			"bill_no_mandatory": _is_bill_no_mandatory(),
			"item_naming_by": item_naming_by,
			"po_required": frappe.db.get_single_value("Buying Settings", "po_required") or "No",
			"pr_required": frappe.db.get_single_value("Buying Settings", "pr_required") or "No",
		},
		"permissions": _get_user_permissions_summary(),
		"template_headers": list(TEMPLATE_HEADERS),
	}


def build_template_xlsx_bytes() -> bytes:
	"""Generate the 7-column Excel template bytes."""
	import openpyxl
	from openpyxl.styles import Alignment, Font, PatternFill
	from openpyxl.utils import get_column_letter

	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = "Hoja1"

	header_font = Font(bold=True, color="1F2937")
	header_fill = PatternFill(start_color="E5E7EB", end_color="E5E7EB", fill_type="solid")

	ws.append(list(TEMPLATE_HEADERS))
	for col_idx, header_text in enumerate(TEMPLATE_HEADERS, start=1):
		cell = ws.cell(row=1, column=col_idx)
		cell.font = header_font
		cell.fill = header_fill
		cell.alignment = Alignment(horizontal="center", vertical="center")
		col_letter = get_column_letter(col_idx)
		ws.column_dimensions[col_letter].width = max(len(header_text) + 6, 16)

	# Format code and barcode columns as text (@) for the first 500 rows
	for row_idx in range(2, 502):
		ws.cell(row=row_idx, column=1).number_format = "@"
		ws.cell(row=row_idx, column=3).number_format = "@"

	output = io.BytesIO()
	wb.save(output)
	wb.close()
	return output.getvalue()


@frappe.whitelist()
def download_template() -> dict:
	"""Download the 7-column purchase import Excel template."""
	_ensure_page_access()
	content = build_template_xlsx_bytes()
	filename = "plantilla_carga_compras.xlsx"

	frappe.local.response.filename = filename
	frappe.local.response.filecontent = content
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "attachment"
	frappe.local.response.content_type = (
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
	)
	return {"ok": True, "filename": filename}


def _extract_file_bytes(
	file_content: str | bytes | None = None,
	file_url: str | None = None,
	filename: str | None = None,
) -> tuple[bytes | None, str, str | None]:
	"""Extract raw file bytes and resolved filename from base64 content or a Frappe file_url."""
	resolved_name = cstr(filename or "").strip() or "carga_compras.xlsx"

	if file_content:
		if isinstance(file_content, bytes):
			return file_content, resolved_name, None
		raw_str = cstr(file_content).strip()
		if raw_str.startswith("data:"):
			parts = raw_str.split(",", 1)
			if len(parts) != 2:
				return None, resolved_name, _("El contenido del archivo base64 es inválido.")
			raw_str = parts[1]
		try:
			return base64.b64decode(raw_str), resolved_name, None
		except Exception:
			return None, resolved_name, _("No se pudo decodificar el archivo enviado.")

	if file_url:
		clean_url = cstr(file_url).strip().split("?")[0]
		if not filename and clean_url:
			resolved_name = clean_url.split("/")[-1] or resolved_name

		file_docs = frappe.get_all(
			"File",
			filters={"file_url": clean_url},
			fields=["name", "file_name"],
			limit=1,
		)
		if not file_docs and "%" in clean_url:
			decoded_url = urllib.parse.unquote(clean_url)
			file_docs = frappe.get_all(
				"File",
				filters={"file_url": decoded_url},
				fields=["name", "file_name"],
				limit=1,
			)

		if file_docs:
			fdoc = frappe.get_doc("File", file_docs[0].name)
			fdoc.check_permission("read")
			content = fdoc.get_content()
			if isinstance(content, str):
				content = content.encode("utf-8")
			return content, (fdoc.file_name or resolved_name), None

		site_path = None
		if clean_url.startswith("/files/"):
			site_path = frappe.get_site_path("public", "files", clean_url[len("/files/") :])
		elif clean_url.startswith("/private/files/"):
			site_path = frappe.get_site_path("private", "files", clean_url[len("/private/files/") :])
		elif os.path.isabs(clean_url) and os.path.exists(clean_url):
			site_path = clean_url

		if site_path and os.path.exists(site_path):
			with open(site_path, "rb") as f:
				return f.read(), resolved_name, None

		return None, resolved_name, _("No se encontró el archivo indicado: {0}").format(file_url)

	return None, resolved_name, _("Debe adjuntar un archivo Excel (.xlsx).")


def _parse_xlsx_rows(file_bytes: bytes) -> tuple[list[dict], dict, list[str]]:
	"""
	Parse the uploaded XLSX workbook and return:
	- parsed_rows: list of row dicts with raw and parsed values + row-level parse errors
	- column_info: dict describing detected columns
	- file_errors: list of file-level structural errors
	"""
	import openpyxl

	file_errors: list[str] = []
	column_info = {
		"has_barcode_col": False,
		"has_price_1_col": False,
		"has_price_2_col": False,
		"has_price_1_values": False,
		"has_price_2_values": False,
	}

	if not file_bytes or not file_bytes.startswith(b"PK\x03\x04"):
		return [], column_info, [_("El archivo debe ser un libro de Excel válido en formato .xlsx.")]

	try:
		wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
	except Exception:
		return [], column_info, [_("No se pudo abrir el archivo .xlsx. Verifique que no esté dañado.")]

	try:
		ws = wb["Hoja1"] if "Hoja1" in wb.sheetnames else (wb.active or wb.worksheets[0])
		raw_rows = list(ws.iter_rows(values_only=True))
	finally:
		wb.close()

	if not raw_rows:
		return [], column_info, [_("El archivo Excel está vacío.")]

	# Locate header row
	header_row_idx = None
	header_cells: list = []
	for idx, row in enumerate(raw_rows):
		if any(not _is_empty_cell(c) for c in row):
			header_row_idx = idx
			header_cells = list(row)
			break

	if header_row_idx is None:
		return [], column_info, [_("El archivo Excel no contiene encabezados ni datos.")]

	col_map: dict[str, int] = {}
	duplicate_cols: list[str] = []
	unrecognized_headers: list[str] = []

	for col_idx, cell_val in enumerate(header_cells):
		if _is_empty_cell(cell_val):
			continue
		norm = _normalize_header(cell_val)
		matched_key = None
		for canonical_key, aliases in HEADER_ALIASES.items():
			if norm in aliases:
				matched_key = canonical_key
				break
		if matched_key:
			if matched_key in col_map:
				duplicate_cols.append(cstr(cell_val).strip())
			else:
				col_map[matched_key] = col_idx
		else:
			unrecognized_headers.append(cstr(cell_val).strip())

	if duplicate_cols:
		file_errors.append(
			_("Encabezados duplicados o ambiguos en el archivo: {0}").format(", ".join(duplicate_cols))
		)

	# Si el archivo no tiene columna explícita de Código Producto pero sí Código de Barra,
	# usar el Código de Barra como Código de Producto y como Código de Barra.
	if "item_code" not in col_map and "barcode" in col_map:
		col_map["item_code"] = col_map["barcode"]
		column_info["barcode_as_item_code"] = True
	else:
		column_info["barcode_as_item_code"] = False

	missing_Labels = {
		"item_code": "Codigo Producto (o Codigo de Barra)",
		"item_name": "Producto",
		"qty": "Cantidad",
		"rate": "Costo",
	}
	missing = [label for key, label in missing_Labels.items() if key not in col_map]
	if missing:
		file_errors.append(
			_("Faltan columnas obligatorias en el archivo Excel: {0}").format(", ".join(missing))
		)
		return [], column_info, file_errors

	column_info["has_barcode_col"] = "barcode" in col_map
	column_info["has_price_1_col"] = "price_1" in col_map
	column_info["has_price_2_col"] = "price_2" in col_map

	parsed_rows: list[dict] = []
	for offset, row in enumerate(raw_rows[header_row_idx + 1 :]):
		excel_row_num = header_row_idx + 2 + offset
		if not any(not _is_empty_cell(c) for c in row):
			continue

		def _get_cell(key: str) -> object:
			c_idx = col_map.get(key)
			if c_idx is None or c_idx >= len(row):
				return None
			return row[c_idx]

		# Omitir filas de plantilla pre-numeradas sin datos de producto, cantidad ni costo
		if (
			_is_empty_cell(_get_cell("item_name"))
			and _is_empty_cell(_get_cell("qty"))
			and _is_empty_cell(_get_cell("rate"))
		):
			continue

		row_errors: list[str] = []

		item_code, code_err = _cell_to_text_code(_get_cell("item_code"))
		if code_err:
			row_errors.append(code_err)
		elif not item_code:
			row_errors.append(_("El código de producto es obligatorio."))

		raw_name = _get_cell("item_name")
		item_name = "" if _is_empty_cell(raw_name) else cstr(raw_name).strip()

		barcode = ""
		if column_info["has_barcode_col"]:
			barcode, bc_err = _cell_to_text_code(_get_cell("barcode"))
			if bc_err:
				row_errors.append(_("Código de barra inválido: {0}").format(bc_err))

		qty, qty_err = _parse_numeric_cell(
			_get_cell("qty"), _("Cantidad"), allow_empty=False, allow_zero=False
		)
		if qty_err:
			row_errors.append(qty_err)

		rate, rate_err = _parse_numeric_cell(
			_get_cell("rate"), _("Costo"), allow_empty=False, allow_zero=True
		)
		if rate_err:
			row_errors.append(rate_err)

		price_1 = None
		if column_info["has_price_1_col"]:
			raw_p1 = _get_cell("price_1")
			if not _is_empty_cell(raw_p1):
				column_info["has_price_1_values"] = True
			price_1, p1_err = _parse_numeric_cell(
				raw_p1, _("Precio Venta 1"), allow_empty=True, allow_zero=True
			)
			if p1_err:
				row_errors.append(p1_err)

		price_2 = None
		if column_info["has_price_2_col"]:
			raw_p2 = _get_cell("price_2")
			if not _is_empty_cell(raw_p2):
				column_info["has_price_2_values"] = True
			price_2, p2_err = _parse_numeric_cell(
				raw_p2, _("Precio Venta 2"), allow_empty=True, allow_zero=True
			)
			if p2_err:
				row_errors.append(p2_err)

		amount = flt((qty or 0.0) * (rate or 0.0))

		parsed_rows.append(
			{
				"row_num": excel_row_num,
				"item_code": item_code,
				"excel_item_name": item_name,
				"item_name": item_name,
				"barcode": barcode,
				"qty": qty,
				"rate": rate,
				"amount": amount,
				"price_1": price_1,
				"price_2": price_2,
				"errors": row_errors,
			}
		)

	if not parsed_rows:
		file_errors.append(_("El archivo Excel no contiene filas con datos."))

	return parsed_rows, column_info, file_errors


def _has_stock_movement(item_code: str) -> bool:
	"""Return True if the item has any Stock Ledger Entry or active Bin reservation/order."""
	if frappe.db.exists("Stock Ledger Entry", {"item_code": item_code}):
		return True

	bin_active = frappe.db.sql(
		"""
		SELECT name
		FROM `tabBin`
		WHERE item_code = %s
		  AND (
			IFNULL(actual_qty, 0) != 0
			OR IFNULL(reserved_qty, 0) != 0
			OR IFNULL(ordered_qty, 0) != 0
			OR IFNULL(indented_qty, 0) != 0
			OR IFNULL(planned_qty, 0) != 0
		  )
		LIMIT 1
		""",
		(item_code,),
	)
	return bool(bin_active)


def _get_current_global_selling_price(
	item_code: str, price_list: str, uom: str, as_of_date: str
) -> dict | None:
	"""
	Return the active global selling Item Price for (item_code, price_list, uom) as of as_of_date,
	excluding customer/supplier/batch specific prices.
	"""
	if not item_code or not price_list or not uom:
		return None

	rows = frappe.db.sql(
		"""
		SELECT name, price_list_rate, currency, valid_from, valid_upto, uom
		FROM `tabItem Price`
		WHERE item_code = %(item_code)s
		  AND price_list = %(price_list)s
		  AND selling = 1
		  AND IFNULL(uom, '') = %(uom)s
		  AND IFNULL(customer, '') = ''
		  AND IFNULL(supplier, '') = ''
		  AND IFNULL(batch_no, '') = ''
		  AND IFNULL(packing_unit, 0) = 0
		  AND (valid_from IS NULL OR valid_from <= %(as_of_date)s)
		  AND (valid_upto IS NULL OR valid_upto >= %(as_of_date)s)
		ORDER BY
		  CASE WHEN valid_from IS NULL THEN 1 ELSE 0 END ASC,
		  valid_from DESC,
		  modified DESC,
		  creation DESC
		LIMIT 1
		""",
		{
			"item_code": item_code,
			"price_list": price_list,
			"uom": uom,
			"as_of_date": as_of_date,
		},
		as_dict=True,
	)
	return rows[0] if rows else None


def _get_same_day_global_selling_price(
	item_code: str, price_list: str, uom: str, upload_date: str
) -> dict | None:
	"""
	Return an existing global selling Item Price for the exact tuple
	(item_code, price_list, uom, valid_from=upload_date, valid_upto=None/empty),
	which ERPNext's ItemPrice.check_duplicates considers a duplicate.
	"""
	if not item_code or not price_list or not uom:
		return None

	rows = frappe.db.sql(
		"""
		SELECT name, price_list_rate, currency, valid_from, valid_upto, uom
		FROM `tabItem Price`
		WHERE item_code = %(item_code)s
		  AND price_list = %(price_list)s
		  AND IFNULL(uom, '') = %(uom)s
		  AND valid_from = %(upload_date)s
		  AND (valid_upto IS NULL OR CAST(valid_upto AS CHAR) = '')
		  AND IFNULL(customer, '') = ''
		  AND IFNULL(supplier, '') = ''
		  AND IFNULL(batch_no, '') = ''
		  AND IFNULL(packing_unit, 0) = 0
		LIMIT 1
		""",
		{
			"item_code": item_code,
			"price_list": price_list,
			"uom": uom,
			"upload_date": upload_date,
		},
		as_dict=True,
	)
	return rows[0] if rows else None


def _evaluate_price_change(
	item_code: str,
	item_exists: bool,
	price_value: float | None,
	price_list: str,
	price_list_valid: bool,
	uom: str,
	upload_date: str,
) -> dict:
	"""Determine whether a given price cell will be ignored, unchanged, created, or updated."""
	if price_value is None:
		return {
			"action": "none",
			"new_rate": None,
			"current_rate": None,
			"same_day_docname": None,
		}

	if not price_list or not price_list_valid or not item_exists or not uom:
		return {
			"action": "create",
			"new_rate": flt(price_value),
			"current_rate": None,
			"same_day_docname": None,
		}

	current_doc = _get_current_global_selling_price(item_code, price_list, uom, upload_date)
	same_day_doc = _get_same_day_global_selling_price(item_code, price_list, uom, upload_date)
	current_rate = flt(current_doc.price_list_rate) if current_doc else None

	if current_doc is not None and abs(flt(current_doc.price_list_rate) - flt(price_value)) < 1e-6:
		# Even if current active matches, if a same_day_doc exists with a different rate we'd update it;
		# but since same_day_doc has the highest valid_from <= today, current_doc IS same_day_doc.
		return {
			"action": "unchanged",
			"new_rate": flt(price_value),
			"current_rate": current_rate,
			"same_day_docname": same_day_doc.name if same_day_doc else None,
		}

	if same_day_doc:
		return {
			"action": "update",
			"new_rate": flt(price_value),
			"current_rate": current_rate,
			"same_day_docname": same_day_doc.name,
		}

	return {
		"action": "create",
		"new_rate": flt(price_value),
		"current_rate": current_rate,
		"same_day_docname": None,
	}


def _validate_price_list(price_list_name: str, label: str) -> tuple[bool, str | None, str | None]:
	"""Validate that a price list exists, is enabled, and is a selling price list."""
	if not price_list_name:
		return False, None, _("Debe seleccionar {0}.").format(label)

	pl = frappe.db.get_value(
		"Price List",
		price_list_name,
		["name", "enabled", "selling", "currency"],
		as_dict=True,
	)
	if not pl:
		return False, None, _("{0} ({1}) no existe.").format(label, price_list_name)
	if not cint(pl.enabled):
		return False, pl.currency, _("{0} ({1}) está deshabilitada.").format(label, price_list_name)
	if not cint(pl.selling):
		return False, pl.currency, _("{0} ({1}) no es una lista de precios de venta.").format(
			label, price_list_name
		)
	return True, pl.currency, None


def _compute_preview_token(
	file_bytes: bytes,
	header_data: dict,
	rows: list[dict],
	upload_date: str,
) -> str:
	"""Build a deterministic SHA-256 token representing the file, header, row choices, and DB state."""
	file_hash = hashlib.sha256(file_bytes).hexdigest()
	payload = {
		"file_hash": file_hash,
		"upload_date": upload_date,
		"header": {
			"company": header_data.get("company"),
			"supplier": header_data.get("supplier"),
			"posting_date": header_data.get("posting_date"),
			"due_date": header_data.get("due_date"),
			"warehouse": header_data.get("warehouse"),
			"bill_no": header_data.get("bill_no"),
			"price_list_1": header_data.get("price_list_1"),
			"price_list_2": header_data.get("price_list_2"),
			"remarks": header_data.get("remarks"),
		},
		"rows": [
			{
				"row_num": r["row_num"],
				"item_code": r["item_code"],
				"status": r["status"],
				"item_group": r["item_group"],
				"stock_uom": r["stock_uom"],
				"uom_locked": r["uom_locked"],
				"db_item_group": r.get("db_item_group"),
				"db_stock_uom": r.get("db_stock_uom"),
				"db_modified": r.get("db_modified"),
				"price_1_action": r["price_1_info"]["action"],
				"price_1_current": r["price_1_info"]["current_rate"],
				"price_1_same_day": r["price_1_info"]["same_day_docname"],
				"price_2_action": r["price_2_info"]["action"],
				"price_2_current": r["price_2_info"]["current_rate"],
				"price_2_same_day": r["price_2_info"]["same_day_docname"],
			}
			for r in rows
		],
	}
	serialized = json.dumps(payload, sort_keys=True, default=str)
	return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _execute_transactions(
	header_data: dict,
	rows: list[dict],
	upload_date: str,
	*,
	dry_run: bool = False,
	upload_id: str | None = None,
	file_bytes: bytes | None = None,
	filename: str | None = None,
) -> dict:
	"""
	Execute creation/update of Items, Item Prices, and submission (or dry-run validation)
	of the Purchase Invoice.
	Caller is responsible for wrapping in a savepoint.
	"""
	created_items = 0
	updated_items = 0
	created_prices = 0
	updated_prices = 0
	unchanged_prices = 0

	price_list_1 = header_data.get("price_list_1") or ""
	price_list_2 = header_data.get("price_list_2") or ""

	# 1. Process Items (New & Existing)
	for r in rows:
		item_code = r["item_code"]
		if r["status"] == "new":
			item_doc = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item_code,
					"item_name": r["excel_item_name"],
					"item_group": r["item_group"],
					"stock_uom": r["stock_uom"],
					"is_stock_item": 1,
				}
			)
			if r.get("barcode"):
				item_doc.append("barcodes", {"barcode": r["barcode"]})
			item_doc.insert()
			if cstr(item_doc.name) != cstr(item_code):
				frappe.throw(
					_(
						"La configuración de series de artículos renombró el código '{0}' a '{1}'. Configure Stock Settings para nombrar productos por Código de Artículo."
					).format(item_code, item_doc.name)
				)
			created_items += 1
		else:
			group_changed = cstr(r["item_group"]) != cstr(r.get("db_item_group"))
			uom_changed = cstr(r["stock_uom"]) != cstr(r.get("db_stock_uom"))
			if group_changed or uom_changed:
				if uom_changed and _has_stock_movement(item_code):
					frappe.throw(
						_(
							"No se puede cambiar la unidad de medida del producto {0} porque ya tiene movimientos de inventario."
						).format(item_code)
					)
				item_doc = frappe.get_doc("Item", item_code)
				item_doc.check_permission("write")
				if group_changed:
					item_doc.item_group = r["item_group"]
				if uom_changed:
					item_doc.stock_uom = r["stock_uom"]
				item_doc.save()
				updated_items += 1

	# 2. Process Item Prices (List 1 & List 2)
	for r in rows:
		item_code = r["item_code"]
		uom = r["stock_uom"]

		for pl_name, p_val in ((price_list_1, r["price_1"]), (price_list_2, r["price_2"])):
			if p_val is None or not pl_name:
				continue

			current_doc = _get_current_global_selling_price(item_code, pl_name, uom, upload_date)
			if current_doc is not None and abs(flt(current_doc.price_list_rate) - flt(p_val)) < 1e-6:
				unchanged_prices += 1
				continue

			same_day_doc = _get_same_day_global_selling_price(item_code, pl_name, uom, upload_date)
			if same_day_doc:
				ip_doc = frappe.get_doc("Item Price", same_day_doc.name)
				ip_doc.check_permission("write")
				ip_doc.price_list_rate = flt(p_val)
				ip_doc.save()
				updated_prices += 1
			else:
				ip_doc = frappe.get_doc(
					{
						"doctype": "Item Price",
						"item_code": item_code,
						"price_list": pl_name,
						"uom": uom,
						"selling": 1,
						"price_list_rate": flt(p_val),
						"valid_from": upload_date,
					}
				)
				ip_doc.insert()
				created_prices += 1

	# 3. Build and validate / submit Purchase Invoice
	effective_due_date = cstr(header_data.get("due_date") or "").strip() or header_data["posting_date"]
	user_remarks = cstr(header_data.get("remarks") or "").strip()

	pi_doc = frappe.new_doc("Purchase Invoice")
	pi_doc.company = header_data["company"]
	pi_doc.supplier = header_data["supplier"]
	pi_doc.posting_date = header_data["posting_date"]
	pi_doc.bill_date = header_data["posting_date"]
	pi_doc.due_date = effective_due_date
	pi_doc.set_posting_time = 1
	pi_doc.update_stock = 1
	pi_doc.is_paid = 0
	pi_doc.set_warehouse = header_data["warehouse"]

	if header_data.get("bill_no"):
		pi_doc.bill_no = header_data["bill_no"]

	if user_remarks:
		pi_doc.remarks = user_remarks
	else:
		pi_doc.remarks = None
		# Evitar que ERPNext autogenere remarks ("Against Supplier Invoice..." o "No Remarks")
		pi_doc.create_remarks = lambda: None

	has_upload_id_col = frappe.db.has_column("Purchase Invoice", "retail_tools_upload_id")
	if upload_id and has_upload_id_col:
		pi_doc.retail_tools_upload_id = upload_id

	for r in rows:
		pi_doc.append(
			"items",
			{
				"item_code": r["item_code"],
				"qty": flt(r["qty"]),
				"rate": flt(r["rate"]),
				"price_list_rate": flt(r["rate"]),
				"warehouse": header_data["warehouse"],
				"uom": r["stock_uom"],
				"stock_uom": r["stock_uom"],
				"conversion_factor": 1.0,
			},
		)

	pi_doc.set_missing_values()
	pi_doc.due_date = effective_due_date
	pi_doc.payment_terms_template = None
	pi_doc.payment_schedule = []

	# Ensure Excel unit cost (rate), UOM, and warehouse are preserved after set_missing_values()
	for idx, pi_item in enumerate(pi_doc.items):
		row_data = rows[idx]
		pi_item.warehouse = header_data["warehouse"]
		pi_item.uom = row_data["stock_uom"]
		pi_item.stock_uom = row_data["stock_uom"]
		pi_item.conversion_factor = 1.0
		pi_item.qty = flt(row_data["qty"])
		pi_item.stock_qty = flt(row_data["qty"])
		pi_item.discount_percentage = 0.0
		pi_item.discount_amount = 0.0
		pi_item.price_list_rate = flt(row_data["rate"])
		pi_item.rate = flt(row_data["rate"])

	pi_doc.calculate_taxes_and_totals()
	pi_doc.insert()
	if not user_remarks and pi_doc.remarks:
		pi_doc.db_set("remarks", None, update_modified=False)
		pi_doc.remarks = None

	pi_doc.check_permission("submit")

	if not dry_run:
		pi_doc.submit()
		if not user_remarks and pi_doc.remarks:
			pi_doc.db_set("remarks", None, update_modified=False)
			pi_doc.remarks = None

		if upload_id and not has_upload_id_col:
			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Info",
					"reference_doctype": "Purchase Invoice",
					"reference_name": pi_doc.name,
					"content": f"[RT-UPLOAD:{upload_id}]",
				}
			).insert(ignore_permissions=True)

		if file_bytes:
			file_doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": filename or "carga_compras.xlsx",
					"attached_to_doctype": "Purchase Invoice",
					"attached_to_name": pi_doc.name,
					"content": file_bytes,
					"is_private": 1,
				}
			)
			file_doc.insert()

	return {
		"invoice_name": pi_doc.name if not dry_run else None,
		"currency": pi_doc.currency,
		"net_total": flt(pi_doc.net_total),
		"total_taxes_and_charges": flt(pi_doc.total_taxes_and_charges),
		"grand_total": flt(pi_doc.grand_total),
		"due_date": cstr(pi_doc.due_date or ""),
		"credit_to": cstr(pi_doc.credit_to or ""),
		"created_items": created_items,
		"updated_items": updated_items,
		"created_prices": created_prices,
		"updated_prices": updated_prices,
		"unchanged_prices": unchanged_prices,
	}


def _analyze_upload(
	file_bytes: bytes | None,
	file_error: str | None,
	header_raw: dict,
	row_overrides_raw: dict,
) -> dict:
	"""Core analysis logic shared by preview_purchase_upload and confirm_purchase_upload."""
	upload_date = today()
	global_errors: list[str] = []

	company = cstr(header_raw.get("company") or "").strip()
	supplier = cstr(header_raw.get("supplier") or "").strip()
	posting_date = cstr(header_raw.get("posting_date") or "").strip()
	raw_due_date = cstr(header_raw.get("due_date") or "").strip()
	due_date = raw_due_date or posting_date
	warehouse = cstr(header_raw.get("warehouse") or "").strip()
	bill_no = cstr(header_raw.get("bill_no") or "").strip()
	price_list_1 = cstr(header_raw.get("price_list_1") or "").strip()
	price_list_2 = cstr(header_raw.get("price_list_2") or "").strip()
	remarks = cstr(header_raw.get("remarks") or "").strip()

	header_data = {
		"company": company,
		"supplier": supplier,
		"posting_date": posting_date,
		"due_date": due_date,
		"warehouse": warehouse,
		"bill_no": bill_no,
		"price_list_1": price_list_1,
		"price_list_2": price_list_2,
		"remarks": remarks,
	}

	# Validate Header fields
	if not company:
		global_errors.append(_("La empresa es obligatoria."))
	elif not frappe.db.exists("Company", company):
		global_errors.append(_("La empresa '{0}' no existe.").format(company))

	if not supplier:
		global_errors.append(_("El proveedor es obligatorio."))
	else:
		sup_info = frappe.db.get_value(
			"Supplier", supplier, ["name", "disabled", "on_hold", "hold_type"], as_dict=True
		)
		if not sup_info:
			global_errors.append(_("El proveedor '{0}' no existe.").format(supplier))
		elif cint(sup_info.disabled):
			global_errors.append(_("El proveedor '{0}' está deshabilitado.").format(supplier))
		elif cint(sup_info.on_hold) and sup_info.hold_type in ("All", "Invoices"):
			global_errors.append(_("El proveedor '{0}' está retenido para facturación.").format(supplier))

	parsed_posting_date = None
	if not posting_date:
		global_errors.append(_("La fecha de compra es obligatoria."))
	else:
		try:
			parsed_posting_date = getdate(posting_date)
		except Exception:
			global_errors.append(_("La fecha de compra '{0}' no es válida.").format(posting_date))

	if due_date:
		try:
			parsed_due_date = getdate(due_date)
			if parsed_posting_date and parsed_due_date < parsed_posting_date:
				global_errors.append(
					_(
						"La fecha de vencimiento ({0}) no puede ser anterior a la fecha de compra ({1})."
					).format(due_date, posting_date)
				)
		except Exception:
			global_errors.append(_("La fecha de vencimiento '{0}' no es válida.").format(due_date))

	if not warehouse:
		global_errors.append(_("El almacén es obligatorio."))
	else:
		wh_info = frappe.db.get_value(
			"Warehouse", warehouse, ["name", "company", "is_group", "disabled"], as_dict=True
		)
		if not wh_info:
			global_errors.append(_("El almacén '{0}' no existe.").format(warehouse))
		else:
			if cint(wh_info.disabled):
				global_errors.append(_("El almacén '{0}' está deshabilitado.").format(warehouse))
			if cint(wh_info.is_group):
				global_errors.append(
					_("El almacén '{0}' es un grupo y no permite movimientos directos.").format(warehouse)
				)
			if company and wh_info.company and wh_info.company != company:
				global_errors.append(
					_("El almacén '{0}' no pertenece a la empresa '{1}'.").format(warehouse, company)
				)

	if _is_bill_no_mandatory() and not bill_no:
		global_errors.append(
			_("El número de factura del proveedor es obligatorio según la configuración del sitio.")
		)

	if file_error:
		global_errors.append(file_error)
		return {
			"ok": False,
			"can_confirm": False,
			"header": header_data,
			"global_errors": global_errors,
			"rows": [],
			"summary": {},
			"preview_token": None,
		}

	parsed_rows, column_info, file_errors = _parse_xlsx_rows(file_bytes or b"")
	global_errors.extend(file_errors)
	if not parsed_rows:
		return {
			"ok": False,
			"can_confirm": False,
			"header": header_data,
			"global_errors": global_errors,
			"rows": [],
			"summary": {},
			"preview_token": None,
		}

	# Validate Price Lists based on whether their column has any value
	has_p1 = column_info["has_price_1_values"]
	has_p2 = column_info["has_price_2_values"]

	pl1_valid = False
	pl1_currency = None
	if has_p1 or price_list_1:
		if has_p1 and not price_list_1:
			global_errors.append(
				_("La Lista de Precios 1 es obligatoria porque la columna 'Precio Venta 1' contiene valores.")
			)
		elif price_list_1:
			pl1_valid, pl1_currency, pl1_err = _validate_price_list(price_list_1, _("Lista de Precios 1"))
			if pl1_err and has_p1:
				global_errors.append(pl1_err)
			elif pl1_err and not has_p1:
				pl1_valid = False

	pl2_valid = False
	pl2_currency = None
	if has_p2 or price_list_2:
		if has_p2 and not price_list_2:
			global_errors.append(
				_("La Lista de Precios 2 es obligatoria porque la columna 'Precio Venta 2' contiene valores.")
			)
		elif price_list_2:
			pl2_valid, pl2_currency, pl2_err = _validate_price_list(price_list_2, _("Lista de Precios 2"))
			if pl2_err and has_p2:
				global_errors.append(pl2_err)
			elif pl2_err and not has_p2:
				pl2_valid = False

	if has_p1 and has_p2 and price_list_1 and price_list_2 and price_list_1 == price_list_2:
		global_errors.append(
			_("Las Listas de Precios 1 y 2 deben ser distintas cuando ambas columnas contienen valores.")
		)

	# Detect duplicate item_codes and duplicate barcodes within the uploaded file
	code_to_rows: dict[str, list[int]] = {}
	barcode_to_rows: dict[str, list[int]] = {}
	for r in parsed_rows:
		if r["item_code"]:
			code_to_rows.setdefault(r["item_code"], []).append(r["row_num"])
		if r["barcode"]:
			barcode_to_rows.setdefault(r["barcode"], []).append(r["row_num"])

	for code, r_nums in code_to_rows.items():
		if len(r_nums) > 1:
			rows_str = ", ".join(str(n) for n in r_nums)
			for r in parsed_rows:
				if r["item_code"] == code:
					r["errors"].append(
						_("Código de producto '{0}' repetido en el archivo (filas {1}).").format(
							code, rows_str
						)
					)

	for bc, r_nums in barcode_to_rows.items():
		if len(r_nums) > 1:
			rows_str = ", ".join(str(n) for n in r_nums)
			for r in parsed_rows:
				if r["barcode"] == bc:
					r["errors"].append(
						_("Código de barras '{0}' repetido en el archivo (filas {1}).").format(bc, rows_str)
					)

	# Fetch existing Items and Barcodes from DB
	all_codes = list(code_to_rows.keys())
	existing_items_map: dict[str, dict] = {}
	if all_codes:
		db_items = frappe.get_all(
			"Item",
			filters={"name": ["in", all_codes]},
			fields=[
				"name",
				"item_code",
				"item_name",
				"item_group",
				"stock_uom",
				"disabled",
				"is_stock_item",
				"has_variants",
				"has_batch_no",
				"has_serial_no",
				"inspection_required_before_purchase",
				"modified",
			],
		)
		for d in db_items:
			# Ensure exact case-sensitive match on item code if needed, or map by d.name
			existing_items_map[d.name] = d

	all_barcodes = list(barcode_to_rows.keys())
	barcode_owner_map: dict[str, list[str]] = {}
	if all_barcodes and frappe.db.exists("DocType", "Item Barcode"):
		bc_rows = frappe.get_all(
			"Item Barcode",
			filters={"barcode": ["in", all_barcodes]},
			fields=["barcode", "parent"],
		)
		for b in bc_rows:
			barcode_owner_map.setdefault(b.barcode, []).append(b.parent)

	item_Write_barcodes_map: dict[str, list[str]] = {}
	if existing_items_map and frappe.db.exists("DocType", "Item Barcode"):
		existing_bcs = frappe.get_all(
			"Item Barcode",
			filters={"parent": ["in", list(existing_items_map.keys())]},
			fields=["parent", "barcode"],
			order_by="idx asc",
		)
		for b in existing_bcs:
			item_Write_barcodes_map.setdefault(b.parent, []).append(b.barcode)

	default_stock_uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or ""
	default_item_group = frappe.db.get_single_value("Stock Settings", "item_group") or ""
	item_naming_by = frappe.db.get_single_value("Stock Settings", "item_naming_by") or "Item Code"

	has_new_items = False
	needs_item_write = False
	needs_price_create = False
	needs_price_write = False

	for r in parsed_rows:
		code = r["item_code"]
		row_key = str(r["row_num"])
		override = (
			row_overrides_raw.get(row_key)
			or row_overrides_raw.get(code)
			or {}
		)

		db_item = existing_items_map.get(code)
		if db_item and cstr(db_item.name) != cstr(code):
			r["errors"].append(
				_(
					"Existe el artículo '{0}' con distinta capitalización que '{1}'."
				).format(db_item.name, code)
			)

		if db_item:
			r["status"] = "existing"
			r["db_item_name"] = db_item.item_name
			r["item_name"] = db_item.item_name
			r["db_item_group"] = db_item.item_group
			r["db_stock_uom"] = db_item.stock_uom
			r["db_modified"] = cstr(db_item.modified)
			r["db_barcodes"] = item_Write_barcodes_map.get(db_item.name, [])

			has_movement = _has_stock_movement(db_item.name)
			r["uom_locked"] = has_movement

			chosen_group = cstr(override.get("item_group") or db_item.item_group).strip()
			chosen_uom = cstr(override.get("stock_uom") or db_item.stock_uom).strip()

			if has_movement and chosen_uom != db_item.stock_uom:
				r["errors"].append(
					_(
						"No se puede cambiar la unidad de medida ('{0}' -> '{1}') porque el producto ya tiene movimientos de inventario."
					).format(db_item.stock_uom, chosen_uom)
				)

			r["item_group"] = chosen_group
			r["stock_uom"] = chosen_uom

			if chosen_group != db_item.item_group or chosen_uom != db_item.stock_uom:
				needs_item_write = True

			if cint(db_item.disabled):
				r["errors"].append(_("El producto '{0}' está deshabilitado.").format(code))
			if not cint(db_item.is_stock_item):
				r["errors"].append(_("El producto '{0}' no es inventariable (is_stock_item=0).").format(code))
			if cint(db_item.has_variants):
				r["errors"].append(
					_("El producto '{0}' es una plantilla de variantes y no puede comprarse.").format(code)
				)
			if cint(db_item.has_batch_no):
				r["errors"].append(
					_("El producto '{0}' exige número de lote, dato ausente de la plantilla.").format(code)
				)
			if cint(db_item.has_serial_no):
				r["errors"].append(
					_("El producto '{0}' exige número de serie, dato ausente de la plantilla.").format(code)
				)
			if cint(db_item.inspection_required_before_purchase):
				r["errors"].append(
					_("El producto '{0}' exige inspección de calidad antes de comprar.").format(code)
				)
		else:
			r["status"] = "new"
			has_new_items = True
			r["db_item_name"] = None
			r["db_item_group"] = None
			r["db_stock_uom"] = None
			r["db_modified"] = None
			r["db_barcodes"] = []
			r["uom_locked"] = False

			chosen_group = cstr(override.get("item_group") or default_item_group).strip()
			chosen_uom = cstr(override.get("stock_uom") or default_stock_uom).strip()
			r["item_group"] = chosen_group
			r["stock_uom"] = chosen_uom

			if not r["excel_item_name"]:
				r["errors"].append(_("El nombre del producto es obligatorio para productos nuevos."))

		# Validate barcode conflicts against DB
		if r["barcode"]:
			owners = barcode_owner_map.get(r["barcode"], [])
			other_owners = [o for o in owners if cstr(o) != cstr(code)]
			if other_owners:
				r["errors"].append(
					_("El código de barras '{0}' ya está asignado a otro producto ({1}).").format(
						r["barcode"], ", ".join(other_owners)
					)
				)

		# Validate Item Group and UOM existence
		if not r["item_group"]:
			r["errors"].append(_("El grupo de artículos es obligatorio."))
		elif not frappe.db.exists("Item Group", r["item_group"]):
			r["errors"].append(_("El grupo de artículos '{0}' no existe.").format(r["item_group"]))

		if not r["stock_uom"]:
			r["errors"].append(_("La unidad de medida es obligatoria."))
		else:
			uom_info = frappe.db.get_value(
				"UOM", r["stock_uom"], ["name", "enabled", "must_be_whole_number"], as_dict=True
			)
			if not uom_info:
				r["errors"].append(_("La unidad de medida '{0}' no existe.").format(r["stock_uom"]))
			else:
				if uom_info.get("enabled") is not None and not cint(uom_info.enabled):
					r["errors"].append(
						_("La unidad de medida '{0}' está deshabilitada.").format(r["stock_uom"])
					)
				if (
					cint(uom_info.must_be_whole_number)
					and r["qty"] is not None
					and not float(r["qty"]).is_integer()
				):
					r["errors"].append(
						_("La unidad '{0}' exige cantidades enteras (cantidad informada: {1}).").format(
							r["stock_uom"], r["qty"]
						)
					)

		# Evaluate Price 1 & Price 2
		r["price_1_info"] = _evaluate_price_change(
			item_code=code,
			item_exists=(r["status"] == "existing"),
			price_value=r["price_1"],
			price_list=price_list_1 if has_p1 else "",
			price_list_valid=pl1_valid,
			uom=r["stock_uom"],
			upload_date=upload_date,
		)
		r["price_2_info"] = _evaluate_price_change(
			item_code=code,
			item_exists=(r["status"] == "existing"),
			price_value=r["price_2"],
			price_list=price_list_2 if has_p2 else "",
			price_list_valid=pl2_valid,
			uom=r["stock_uom"],
			upload_date=upload_date,
		)

		for p_info in (r["price_1_info"], r["price_2_info"]):
			if p_info["action"] == "create":
				needs_price_create = True
			elif p_info["action"] == "update":
				needs_price_write = True

	if has_new_items and item_naming_by == "Naming Series":
		global_errors.append(
			_(
				"Stock Settings está configurado para nombrar productos por serie ('Naming Series'), lo que impide conservar el código de producto del Excel."
			)
		)

	# Check effective user permissions for required operations
	if not frappe.has_permission("Purchase Invoice", "create"):
		global_errors.append(_("No tiene permiso para crear Facturas de Compra (Purchase Invoice)."))
	if not frappe.has_permission("Purchase Invoice", "submit"):
		global_errors.append(_("No tiene permiso para enviar Facturas de Compra (Purchase Invoice)."))
	if has_new_items and not frappe.has_permission("Item", "create"):
		global_errors.append(_("No tiene permiso para crear Productos nuevos (Item)."))
	if needs_item_write and not frappe.has_permission("Item", "write"):
		global_errors.append(_("No tiene permiso para modificar Productos existentes (Item)."))
	if needs_price_create and not frappe.has_permission("Item Price", "create"):
		global_errors.append(_("No tiene permiso para crear Precios de Producto (Item Price)."))
	if needs_price_write and not frappe.has_permission("Item Price", "write"):
		global_errors.append(_("No tiene permiso para actualizar Precios de Producto (Item Price)."))

	any_row_errors = any(bool(r["errors"]) for r in parsed_rows)

	# Dry-run simulation inside a rolled-back savepoint to catch any native ERPNext validation error
	sim_result: dict = {}
	if not global_errors and not any_row_errors:
		sp_name = "carga_compras_preview_dryrun"
		frappe.db.savepoint(sp_name)
		try:
			sim_result = _execute_transactions(
				header_data=header_data,
				rows=parsed_rows,
				upload_date=upload_date,
				dry_run=True,
			)
		except Exception as exc:
			err_text = cstr(exc).strip() or _("Error de validación en ERPNext al simular el envío.")
			# Strip HTML tags for clean display while keeping readable text
			clean_err = re.sub(r"<br\s*/?>", " ", err_text)
			clean_err = re.sub(r"<[^>]+>", "", clean_err).strip()
			global_errors.append(clean_err)
		finally:
			frappe.db.rollback(save_point=sp_name)
			if hasattr(frappe.local, "message_log"):
				frappe.local.message_log = []

	total_rows = len(parsed_rows)
	new_items_count = sum(1 for r in parsed_rows if r["status"] == "new")
	existing_items_count = sum(1 for r in parsed_rows if r["status"] == "existing")
	updated_items_count = sum(
		1
		for r in parsed_rows
		if r["status"] == "existing"
		and (
			cstr(r["item_group"]) != cstr(r.get("db_item_group"))
			or cstr(r["stock_uom"]) != cstr(r.get("db_stock_uom"))
		)
	)
	rows_with_errors = sum(1 for r in parsed_rows if r["errors"])
	total_qty = sum(flt(r["qty"] or 0) for r in parsed_rows)
	subtotal = sum(flt(r["amount"] or 0) for r in parsed_rows)

	prices_to_create = sum(
		(1 if r["price_1_info"]["action"] == "create" else 0)
		+ (1 if r["price_2_info"]["action"] == "create" else 0)
		for r in parsed_rows
	)
	prices_to_update = sum(
		(1 if r["price_1_info"]["action"] == "update" else 0)
		+ (1 if r["price_2_info"]["action"] == "update" else 0)
		for r in parsed_rows
	)
	prices_unchanged = sum(
		(1 if r["price_1_info"]["action"] == "unchanged" else 0)
		+ (1 if r["price_2_info"]["action"] == "unchanged" else 0)
		for r in parsed_rows
	)

	can_confirm = not global_errors and rows_with_errors == 0 and total_rows > 0
	preview_token = (
		_compute_preview_token(file_bytes or b"", header_data, parsed_rows, upload_date)
		if can_confirm
		else None
	)

	return {
		"ok": True,
		"can_confirm": can_confirm,
		"upload_date": upload_date,
		"header": header_data,
		"column_info": column_info,
		"price_lists": {
			"price_list_1": {"name": price_list_1, "currency": pl1_currency, "required": has_p1},
			"price_list_2": {"name": price_list_2, "currency": pl2_currency, "required": has_p2},
		},
		"global_errors": global_errors,
		"rows": parsed_rows,
		"summary": {
			"total_rows": total_rows,
			"new_items": new_items_count,
			"existing_items": existing_items_count,
			"updated_items": updated_items_count,
			"rows_with_errors": rows_with_errors,
			"total_qty": flt(total_qty),
			"subtotal": flt(subtotal),
			"net_total": flt(sim_result.get("net_total", subtotal)),
			"total_taxes_and_charges": flt(sim_result.get("total_taxes_and_charges", 0.0)),
			"grand_total": flt(sim_result.get("grand_total", subtotal)),
			"currency": sim_result.get("currency")
			or (
				frappe.db.get_value("Company", company, "default_currency")
				if company
				else None
			),
			"due_date": sim_result.get("due_date"),
			"credit_to": sim_result.get("credit_to"),
			"prices_to_create": prices_to_create,
			"prices_to_update": prices_to_update,
			"prices_unchanged": prices_unchanged,
		},
		"preview_token": preview_token,
	}


@frappe.whitelist()
def preview_purchase_upload(
	file_content: str | bytes | None = None,
	file_url: str | None = None,
	filename: str | None = None,
	header: str | dict | None = None,
	row_overrides: str | dict | None = None,
) -> dict:
	"""Analyze the uploaded Excel file and header inputs and return preview rows, summary, and errors."""
	_ensure_page_access()

	header_dict = _parse_json_arg(header, {})
	overrides_dict = _parse_json_arg(row_overrides, {})

	file_bytes, resolved_name, file_err = _extract_file_bytes(
		file_content=file_content, file_url=file_url, filename=filename
	)

	result = _analyze_upload(
		file_bytes=file_bytes,
		file_error=file_err,
		header_raw=header_dict if isinstance(header_dict, dict) else {},
		row_overrides_raw=overrides_dict if isinstance(overrides_dict, dict) else {},
	)
	result["filename"] = resolved_name
	return result


def _find_existing_invoice_by_upload_id(upload_id: str) -> str | None:
	"""Check if a non-cancelled Purchase Invoice already exists for the given upload_id."""
	if not upload_id:
		return None

	if frappe.db.has_column("Purchase Invoice", "retail_tools_upload_id"):
		existing = frappe.db.get_value(
			"Purchase Invoice",
			{"retail_tools_upload_id": upload_id, "docstatus": ["!=", 2]},
			"name",
		)
		if existing:
			return existing

	marker = f"[RT-UPLOAD:{upload_id}]"
	rows = frappe.db.sql(
		"""
		SELECT pi.name
		FROM `tabComment` c
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = c.reference_name
		WHERE c.reference_doctype = 'Purchase Invoice'
		  AND c.content = %s
		  AND pi.docstatus != 2
		LIMIT 1
		""",
		(marker,),
	)
	return rows[0][0] if rows else None


@frappe.whitelist()
def confirm_purchase_upload(
	file_content: str | bytes | None = None,
	file_url: str | None = None,
	filename: str | None = None,
	header: str | dict | None = None,
	row_overrides: str | dict | None = None,
	preview_token: str | None = None,
	upload_id: str | None = None,
) -> dict:
	"""
	Re-read and re-validate the Excel file and current DB state, then create/update Items,
	Item Prices, and submit a single Purchase Invoice with update_stock=1 in one transaction.
	"""
	_ensure_page_access()

	clean_upload_id = cstr(upload_id or "").strip()
	if not clean_upload_id:
		return {
			"ok": False,
			"error_code": "MISSING_UPLOAD_ID",
			"message": _("Falta el identificador único de carga (upload_id)."),
		}

	# Idempotency check: prevent duplicate invoice creation on retry
	existing_pi = _find_existing_invoice_by_upload_id(clean_upload_id)
	if existing_pi:
		return {
			"ok": False,
			"already_processed": True,
			"error_code": "DUPLICATE_UPLOAD",
			"invoice_name": existing_pi,
			"message": _(
				"Esta confirmación ya fue procesada anteriormente en la Factura de Compra {0}."
			).format(existing_pi),
		}

	header_dict = _parse_json_arg(header, {})
	overrides_dict = _parse_json_arg(row_overrides, {})

	file_bytes, resolved_name, file_err = _extract_file_bytes(
		file_content=file_content, file_url=file_url, filename=filename
	)

	analysis = _analyze_upload(
		file_bytes=file_bytes,
		file_error=file_err,
		header_raw=header_dict if isinstance(header_dict, dict) else {},
		row_overrides_raw=overrides_dict if isinstance(overrides_dict, dict) else {},
	)

	if not analysis.get("can_confirm"):
		all_errors = list(analysis.get("global_errors") or [])
		for r in analysis.get("rows") or []:
			for err in r.get("errors") or []:
				all_errors.append(_("Fila {0} ({1}): {2}").format(r["row_num"], r["item_code"], err))
		return {
			"ok": False,
			"error_code": "VALIDATION_ERROR",
			"message": all_errors[0]
			if all_errors
			else _("Existen errores de validación que impiden registrar la compra."),
			"errors": all_errors,
			"analysis": analysis,
		}

	if not preview_token or cstr(preview_token).strip() != cstr(analysis.get("preview_token")):
		return {
			"ok": False,
			"error_code": "STALE_PREVIEW",
			"message": _(
				"La vista previa está desactualizada porque el archivo o los datos del sistema cambiaron. Actualice la vista previa antes de confirmar."
			),
			"analysis": analysis,
		}

	sp_name = "carga_compras_confirm_tx"
	frappe.db.savepoint(sp_name)
	try:
		tx_result = _execute_transactions(
			header_data=analysis["header"],
			rows=analysis["rows"],
			upload_date=analysis["upload_date"],
			dry_run=False,
			upload_id=clean_upload_id,
			file_bytes=file_bytes,
			filename=resolved_name,
		)
	except Exception as exc:
		frappe.db.rollback(save_point=sp_name)
		err_msg = cstr(exc).strip() or _("Error al registrar la compra. Se revirtieron todos los cambios.")
		return {
			"ok": False,
			"error_code": "TRANSACTION_FAILED",
			"message": err_msg,
		}

	return {
		"ok": True,
		"invoice_name": tx_result["invoice_name"],
		"invoice_url": f"/app/purchase-invoice/{urllib.parse.quote(cstr(tx_result['invoice_name']))}",
		"upload_id": clean_upload_id,
		"summary": {
			"total_rows": len(analysis["rows"]),
			"created_items": tx_result["created_items"],
			"updated_items": tx_result["updated_items"],
			"existing_items": analysis["summary"]["existing_items"],
			"created_prices": tx_result["created_prices"],
			"updated_prices": tx_result["updated_prices"],
			"unchanged_prices": tx_result["unchanged_prices"],
			"currency": tx_result["currency"],
			"net_total": tx_result["net_total"],
			"total_taxes_and_charges": tx_result["total_taxes_and_charges"],
			"grand_total": tx_result["grand_total"],
		},
	}
