"""Tests for resumable server-side Carga de Compras background jobs and progress updates."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


class FakeCache:
	def __init__(self):
		self.store = {}

	def set_value(self, key, val, expires_in_sec=None):
		self.store[key] = val

	def get_value(self, key):
		return self.store.get(key)


def load_carga_compras_module():
	cache = FakeCache()
	realtime_events = []
	enqueued = []
	commits = []
	rollbacks = []

	frappe = types.ModuleType("frappe")
	frappe.__path__ = []
	frappe._ = lambda msg: msg
	frappe.PermissionError = PermissionError
	frappe.whitelist = lambda *a, **kw: (lambda fn: fn)
	frappe.session = types.SimpleNamespace(user="test@example.com")
	frappe.set_user = lambda user: setattr(frappe.session, "user", user)
	frappe.get_roles = lambda user=None: ["RT Responsable de Tienda"]
	frappe.has_permission = lambda dt, ptype="read": True
	frappe.cache = lambda: cache
	frappe.publish_realtime = lambda event, msg, user=None: realtime_events.append((event, dict(msg), user))
	frappe.enqueue = lambda method, **kw: enqueued.append((method, kw))
	frappe.db = types.SimpleNamespace(
		commit=lambda: commits.append(1),
		rollback=lambda **kw: rollbacks.append(1),
		has_column=lambda dt, col: True,
		get_value=lambda *a, **kw: None,
		sql=lambda *a, **kw: [],
	)

	def _throw(msg, exc=Exception):
		raise exc(msg)

	frappe.throw = _throw

	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda v: int(v or 0)
	utils.cstr = lambda v: "" if v is None else str(v)
	utils.flt = lambda v: float(v or 0.0)
	utils.getdate = lambda v: v
	utils.today = lambda: "2026-11-20"

	modules = {"frappe": frappe, "frappe.utils": utils}
	path = (
		Path(__file__).resolve().parents[1]
		/ "retail_tools"
		/ "retail_tools"
		/ "page"
		/ "carga_compras"
		/ "carga_compras.py"
	)
	with mock.patch.dict(sys.modules, modules):
		spec = importlib.util.spec_from_file_location("carga_compras_job_test", path)
		mod = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(mod)
	return mod, frappe, cache, realtime_events, enqueued, commits, rollbacks


class CargaComprasJobsTest(unittest.TestCase):
	def _sample_analysis(self):
		return {
			"ok": True,
			"can_confirm": True,
			"upload_date": "2026-11-20",
			"preview_token": "tok-123",
			"header": {
				"company": "Punto Accesorios",
				"supplier": "Prov A",
				"posting_date": "2026-11-20",
				"due_date": "2026-11-20",
				"warehouse": "Almacen - PA",
				"price_list_1": "Venta Detalle",
				"price_list_2": "Venta Mayorista",
			},
			"rows": [
				{
					"row_num": 2,
					"item_code": "ITEM-01",
					"excel_item_name": "Aretes 1",
					"item_group": "Bisuteria",
					"stock_uom": "Nos",
					"qty": 5,
					"rate": 10,
					"price_1": 25,
					"price_2": 20,
				},
				{
					"row_num": 3,
					"item_code": "ITEM-02",
					"excel_item_name": "Aretes 2",
					"item_group": "Bisuteria",
					"stock_uom": "Nos",
					"qty": 3,
					"rate": 15,
					"price_1": 35,
					"price_2": 30,
				},
			],
			"summary": {"existing_items": 0},
		}

	def test_start_fail_and_resume_from_item_checkpoint(self):
		mod, frappe, cache, events, enqueued, commits, rollbacks = load_carga_compras_module()
		analysis = self._sample_analysis()

		with (
			mock.patch.object(mod, "_extract_file_bytes", return_value=(b"xlsx-bytes", "compra.xlsx", None)),
			mock.patch.object(mod, "_analyze_upload", return_value=analysis),
			mock.patch.object(mod, "_find_existing_invoice_by_upload_id", return_value=None),
		):
			start_res = mod.start_purchase_upload_job(
				file_content="ZmFrZQ==",
				filename="compra.xlsx",
				header="{}",
				row_overrides="{}",
				preview_token="tok-123",
				upload_id="upl-001",
			)

		self.assertTrue(start_res["ok"])
		self.assertEqual(start_res["job"]["status"], "queued")
		self.assertEqual(len(enqueued), 1)
		self.assertEqual(enqueued[0][1]["queue"], "long")

		# First worker run: row 2 succeeds, row 3 fails
		processed_items = []

		def flaky_item_processor(row):
			processed_items.append(row["item_code"])
			if row["item_code"] == "ITEM-02" and len(processed_items) == 2:
				raise RuntimeError("Lock wait timeout")
			return "created"

		processed_prices = []

		def price_processor(row, pl1, pl2, upload_date):
			processed_prices.append(row["item_code"])
			return (2, 0, 0)

		invoice_calls = []

		def build_invoice(**kw):
			invoice_calls.append(kw["upload_id"])
			return {
				"invoice_name": "ACC-PINV-2026-0001",
				"currency": "NIO",
				"net_total": 95.0,
				"total_taxes_and_charges": 0.0,
				"grand_total": 95.0,
			}

		with (
			mock.patch.object(mod, "_find_existing_invoice_by_upload_id", return_value=None),
			mock.patch.object(mod, "_process_single_item_row", side_effect=flaky_item_processor),
			mock.patch.object(mod, "_process_single_price_row", side_effect=price_processor),
			mock.patch.object(mod, "_build_purchase_invoice_from_rows", side_effect=build_invoice),
		):
			first_state = mod._run_purchase_upload_job("upl-001", user="test@example.com")
			self.assertEqual(first_state["status"], "failed")
			self.assertEqual(first_state["failed_phase"], "items")
			self.assertEqual(first_state["failed_row_num"], 3)
			self.assertEqual(first_state["done_item_rows"], [2])
			self.assertEqual(len(rollbacks), 1)

			# Resume job
			resume_res = mod.resume_purchase_upload_job("upl-001")
			self.assertTrue(resume_res["ok"])
			self.assertEqual(resume_res["job"]["status"], "queued")
			self.assertEqual(resume_res["job"]["attempt"], 2)
			self.assertEqual(len(enqueued), 2)

			# Second worker run skips ITEM-01 (already in done_item_rows) and finishes everything
			final_state = mod._run_purchase_upload_job("upl-001", user="test@example.com")
			self.assertEqual(final_state["status"], "completed")
			self.assertEqual(final_state["percent"], 100)
			self.assertEqual(final_state["invoice_name"], "ACC-PINV-2026-0001")
			# ITEM-01 was only processed ONCE across both attempts!
			self.assertEqual(processed_items, ["ITEM-01", "ITEM-02", "ITEM-02"])
			self.assertEqual(processed_prices, ["ITEM-01", "ITEM-02"])
			self.assertEqual(invoice_calls, ["upl-001"])
			self.assertEqual(final_state["summary"]["created_items"], 2)
			self.assertEqual(final_state["summary"]["created_prices"], 4)

			# Resuming an already-completed job does NOT re-enqueue
			res_after = mod.resume_purchase_upload_job("upl-001")
			self.assertEqual(res_after["job"]["status"], "completed")
			self.assertEqual(len(enqueued), 2)

	def test_resume_after_invoice_failure_skips_items_and_prices(self):
		mod, frappe, cache, events, enqueued, commits, rollbacks = load_carga_compras_module()
		analysis = self._sample_analysis()

		with (
			mock.patch.object(mod, "_extract_file_bytes", return_value=(b"xlsx-bytes", "compra.xlsx", None)),
			mock.patch.object(mod, "_analyze_upload", return_value=analysis),
			mock.patch.object(mod, "_find_existing_invoice_by_upload_id", return_value=None),
		):
			mod.start_purchase_upload_job(
				file_content="ZmFrZQ==",
				filename="compra.xlsx",
				header="{}",
				row_overrides="{}",
				preview_token="tok-123",
				upload_id="upl-002",
			)

		item_calls = []
		price_calls = []
		inv_attempt = {"count": 0}

		def build_invoice(**kw):
			inv_attempt["count"] += 1
			if inv_attempt["count"] == 1:
				raise RuntimeError("Account period closed")
			return {
				"invoice_name": "ACC-PINV-2026-0002",
				"currency": "NIO",
				"net_total": 95.0,
				"total_taxes_and_charges": 0.0,
				"grand_total": 95.0,
			}

		with (
			mock.patch.object(mod, "_find_existing_invoice_by_upload_id", return_value=None),
			mock.patch.object(
				mod, "_process_single_item_row", side_effect=lambda r: (item_calls.append(r["item_code"]) or "created")
			),
			mock.patch.object(
				mod,
				"_process_single_price_row",
				side_effect=lambda r, *a: (price_calls.append(r["item_code"]) or (2, 0, 0)),
			),
			mock.patch.object(mod, "_build_purchase_invoice_from_rows", side_effect=build_invoice),
		):
			failed = mod._run_purchase_upload_job("upl-002", user="test@example.com")
			self.assertEqual(failed["status"], "failed")
			self.assertEqual(failed["failed_phase"], "invoice")
			self.assertEqual(len(item_calls), 2)
			self.assertEqual(len(price_calls), 2)

			mod.resume_purchase_upload_job("upl-002")
			done = mod._run_purchase_upload_job("upl-002", user="test@example.com")
			self.assertEqual(done["status"], "completed")
			self.assertEqual(done["invoice_name"], "ACC-PINV-2026-0002")
			# Items and prices were NOT re-run on resume!
			self.assertEqual(len(item_calls), 2)
			self.assertEqual(len(price_calls), 2)


if __name__ == "__main__":
	unittest.main()
