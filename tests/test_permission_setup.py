"""Check that RT permissions do not hide Frappe's existing role controls."""

import importlib.util
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


class Row(dict):
	def __getattr__(self, key):
		return self[key]


def load_setup(custom_perms, standard_perms=None):
	standard_perms = standard_perms or [
		Row(parent="User", role="System Manager", permlevel=0, if_owner=0, read=1, write=1, select=0),
		Row(parent="User", role="System Manager", permlevel=1, if_owner=0, read=1, write=1, select=0),
	]
	cache_clears = []
	frappe = types.ModuleType("frappe")
	frappe.__path__ = []
	frappe.flags = types.SimpleNamespace()
	frappe.get_meta = lambda doctype: (
		types.SimpleNamespace(
			fields=[types.SimpleNamespace(fieldname=flag, fieldtype="Check") for flag in ("read", "write", "select")]
		)
		if doctype == "Custom DocPerm" else types.SimpleNamespace(istable=0)
	)
	frappe.get_all = lambda doctype, filters, fields, limit_page_length: [
		row
		for row in (standard_perms if doctype == "DocPerm" else custom_perms)
		if row.parent == filters["parent"]
	]
	frappe.db = types.SimpleNamespace(
		exists=lambda doctype, identity: (
			doctype == "DocType" and any(row.parent == identity for row in standard_perms)
		)
	)
	frappe.get_doc = lambda data: types.SimpleNamespace(
		insert=lambda ignore_permissions: custom_perms.append(Row(data))
	)
	frappe.clear_cache = lambda doctype=None: cache_clears.append(doctype)

	custom_field = types.ModuleType("frappe.custom.doctype.custom_field.custom_field")
	custom_field.create_custom_fields = lambda *args, **kwargs: None
	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value: int(value or 0)
	modules = {
		"frappe": frappe,
		"frappe.custom": types.ModuleType("frappe.custom"),
		"frappe.custom.doctype": types.ModuleType("frappe.custom.doctype"),
		"frappe.custom.doctype.custom_field": types.ModuleType("frappe.custom.doctype.custom_field"),
		"frappe.custom.doctype.custom_field.custom_field": custom_field,
		"frappe.utils": utils,
	}
	path = Path(__file__).resolve().parents[1] / "retail_tools" / "setup.py"
	with patch.dict(sys.modules, modules):
		spec = importlib.util.spec_from_file_location("retail_tools_setup_test", path)
		setup = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(setup)
	return setup, cache_clears


class PermissionSetupTest(unittest.TestCase):
	def test_restores_system_manager_role_levels_and_is_idempotent(self):
		custom_perms = [
			Row(parent="User", role="RT Administrador de Sistema", permlevel=0, if_owner=0, read=1, write=1)
		]
		setup, cache_clears = load_setup(custom_perms)

		first = setup.restore_standard_permissions_for_rt_doctypes()
		second = setup.restore_standard_permissions_for_rt_doctypes()

		manager_rows = [row for row in custom_perms if row.role == "System Manager"]
		self.assertEqual({row.permlevel for row in manager_rows}, {0, 1})
		self.assertTrue(all(row.read and row.write for row in manager_rows))
		self.assertTrue(all(row.select == 0 for row in manager_rows))
		self.assertEqual(first, (2, ["User"], []))
		self.assertEqual(second, (0, [], []))
		self.assertEqual(cache_clears, ["User"])

	def test_prepares_unmodified_permissions_before_fixture_import(self):
		custom_perms = []
		setup, cache_clears = load_setup(custom_perms)

		result = setup.restore_standard_permissions_for_rt_doctypes()

		self.assertEqual(result, (2, ["User"], []))
		self.assertEqual({row.role for row in custom_perms}, {"System Manager"})
		self.assertEqual(cache_clears, ["User"])

	def test_restores_company_permission_used_by_pos(self):
		custom_perms = [
			Row(parent="Company", role="RT Cajero", permlevel=0, if_owner=0, read=1),
		]
		standard_perms = [
			Row(parent="Company", role="Sales User", permlevel=0, if_owner=0, read=1),
			Row(parent="Company", role="System Manager", permlevel=0, if_owner=0, read=1, write=1),
		]
		setup, cache_clears = load_setup(custom_perms, standard_perms)

		result = setup.restore_standard_permissions_for_rt_doctypes()

		self.assertEqual(result, (2, ["Company"], []))
		self.assertEqual({row.role for row in custom_perms}, {"RT Cajero", "Sales User", "System Manager"})
		self.assertEqual(cache_clears, ["Company"])

	def test_preserves_unrelated_custom_permission_sets(self):
		custom_perms = [
			Row(parent="User", role="RT Administrador de Sistema", permlevel=0, if_owner=0),
			Row(parent="User", role="Custom Auditor", permlevel=0, if_owner=0),
		]
		setup, cache_clears = load_setup(custom_perms)

		result = setup.restore_standard_permissions_for_rt_doctypes()

		self.assertEqual(len(custom_perms), 2)
		self.assertEqual(result, (0, [], ["User"]))
		self.assertEqual(cache_clears, [])

	def test_does_not_regrant_manually_removed_permission(self):
		custom_perms = [
			Row(parent="User", role="RT Administrador de Sistema", permlevel=0, if_owner=0),
			Row(parent="User", role="System Manager", permlevel=0, if_owner=0, read=1, write=0),
		]
		setup, cache_clears = load_setup(custom_perms)

		result = setup.restore_standard_permissions_for_rt_doctypes()

		self.assertEqual(result, (0, [], ["User"]))
		self.assertEqual(len(custom_perms), 2)
		self.assertEqual(custom_perms[1].write, 0)
		self.assertEqual(cache_clears, [])

	def test_patch_rechecks_after_fixture_sync(self):
		custom_perms = [
			Row(parent="User", role="RT Administrador de Sistema", permlevel=0, if_owner=0)
		]
		setup, cache_clears = load_setup(custom_perms)
		patch_module = Path(__file__).resolve().parents[1] / "retail_tools" / "retail_tools" / "patches" / "restore_standard_docperms_v1.py"
		with patch.dict(sys.modules, {"frappe": setup.frappe, "retail_tools.setup": setup}):
			spec = importlib.util.spec_from_file_location("restore_standard_docperms_v1_test", patch_module)
			migration_patch = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(migration_patch)
			with redirect_stdout(io.StringIO()):
				migration_patch.execute()
		self.assertTrue(setup.frappe.flags.retail_tools_restore_permissions_after_migrate)
		self.assertEqual(cache_clears, ["User"])

	def test_after_migrate_repairs_only_during_patch_migration(self):
		custom_perms = [
			Row(parent="User", role="RT Administrador de Sistema", permlevel=0, if_owner=0)
		]
		setup, _ = load_setup(custom_perms)
		setup.setup_custom_fields = lambda: None
		setup.sync_pages_and_workspace = lambda: None
		setup.setup_roles_and_permissions = lambda: None
		setup.frappe.flags.retail_tools_restore_permissions_after_migrate = True

		with redirect_stdout(io.StringIO()):
			setup.after_migrate()
		self.assertEqual(len(custom_perms), 3)
		self.assertFalse(setup.frappe.flags.retail_tools_restore_permissions_after_migrate)

		custom_perms.pop()
		setup.after_migrate()
		self.assertEqual(len(custom_perms), 2)

	def test_patch_is_registered_for_migration(self):
		patches = Path(__file__).resolve().parents[1] / "retail_tools" / "patches.txt"
		self.assertIn(
			"retail_tools.retail_tools.patches.restore_standard_docperms_v1",
			patches.read_text(),
		)

	def test_fixture_only_adds_rt_roles_to_covered_doctypes(self):
		root = Path(__file__).resolve().parents[1] / "retail_tools"
		fixture = json.loads((root / "fixtures" / "rt_custom_docperm.json").read_text())
		setup, _ = load_setup([])
		matrix_doctypes = {
			doctype for role_perms in setup.ROLE_PERMISSIONS_MATRIX.values() for doctype in role_perms
		}
		self.assertTrue(all(row["role"] in setup.RT_ROLES for row in fixture))
		self.assertEqual({row["parent"] for row in fixture}, matrix_doctypes)


if __name__ == "__main__":
	unittest.main()
