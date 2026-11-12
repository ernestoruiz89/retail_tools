"""Validate Desk navigation links and roles for retail_tools metadata."""

import json
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "retail_tools"


def read_json(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8"))


def navigation_links():
	for path in (
		APP / "retail_tools/sidebar/retail_tools/retail_tools.json",
		APP / "workspace_sidebar/retail_tools.json",
		APP / "retail_tools/workspace/retail_tools/retail_tools.json",
	):
		doc = read_json(path)
		for item in doc.get("items", doc.get("links", [])):
			if item.get("type") == "Link":
				yield path.name, item["link_type"], item["link_to"]
		for item in doc.get("shortcuts", []):
			yield path.name, item["type"], item["link_to"]


class NavigationTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.metadata = {}
		for kind in ("page", "workspace"):
			cls.metadata[kind] = {
				doc["name"]: doc
				for path in (APP / "retail_tools" / kind).glob("*/*.json")
				for doc in [read_json(path)]
			}

	def test_links_resolve_to_existing_entities(self):
		for source, kind, target in navigation_links():
			with self.subTest(source=source, kind=kind, target=target):
				self.assertIn(target, self.metadata[kind.lower()])

	def test_carga_compras_is_in_all_navigation_manifests(self):
		for path in (
			APP / "retail_tools/sidebar/retail_tools/retail_tools.json",
			APP / "workspace_sidebar/retail_tools.json",
			APP / "retail_tools/workspace/retail_tools/retail_tools.json",
		):
			doc = read_json(path)
			targets = {
				item["link_to"]
				for item in doc.get("items", doc.get("links", []))
				if item.get("type") == "Link"
			} | {item["link_to"] for item in doc.get("shortcuts", [])}
			self.assertIn("carga-compras", targets, f"Missing carga-compras in {path.name}")


if __name__ == "__main__":
	unittest.main()
