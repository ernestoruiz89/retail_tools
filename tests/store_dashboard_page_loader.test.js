const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const pageDir = path.join(
	__dirname,
	"../retail_tools/retail_tools/page/store_dashboard"
);

test("store dashboard compiles through Frappe's Page HTML loader", () => {
	const templates = fs.readdirSync(pageDir)
		.filter((name) => name.endsWith(".html"))
		.map((name) => {
			const html = fs.readFileSync(path.join(pageDir, name), "utf8")
				.replace(/\s+/g, " ")
				.replace(/<!--.*?-->/g, "");
			return `frappe.templates["${name.slice(0, -5)}"] = '${html}';\n`;
		});
	const pageScript = fs.readFileSync(path.join(pageDir, "store_dashboard.js"), "utf8");

	assert.doesNotThrow(() => new vm.Script(templates.join("") + pageScript));
});
