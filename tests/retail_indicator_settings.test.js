const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function formHarness(accounts, expenses = []) {
	const handlers = {}, buttons = {}, calls = [], queries = [];
	const frm = {
		doc: { company: "A", expenses }, perm: [{ write: 1 }],
		set_query(field, table, fn) { queries.push(fn()); },
		add_custom_button(label, fn) { buttons[label] = fn; },
		add_child(table, row) { frm.doc[table].push(row); },
		refresh_field() {}, dirty() {}
	};
	vm.runInNewContext(fs.readFileSync(path.join(__dirname,
		"../retail_tools/retail_tools/doctype/retail_indicator_settings/retail_indicator_settings.js"), "utf8"), {
		__: text => text,
		frappe: {
			ui: { form: { on(name, events) { handlers[name] = events; } } },
			db: { async get_list(doctype, options) { calls.push(options); return accounts; } },
			show_alert() {}
		}
	});
	handlers["Retail Indicator Settings"].setup(frm);
	handlers["Retail Indicator Settings"].refresh(frm);
	return { frm, buttons, calls, queries };
}

test("loads main groups without descendants, duplicate rows or overwritten classifications", async () => {
	const accounts = [
		{ name: "Expenses" },
		{ name: "COGS", parent_account: "Expenses", account_type: "Cost of Goods Sold" },
		{ name: "Admin", parent_account: "Expenses" },
		{ name: "Payroll", parent_account: "Admin" },
		{ name: "Salaries", parent_account: "Payroll" }
	];
	const h = formHarness(accounts, [{ account: "Admin", behavior: "Fijo" }]);
	await h.buttons["Cargar cuentas de mayor"]();
	await h.buttons["Cargar cuentas de mayor"]();
	assert.deepEqual(h.frm.doc.expenses.map(r => [r.account, r.behavior]), [["Admin", "Fijo"], ["COGS", ""]]);
	assert.equal(h.calls[0].filters.is_group, 1);
	assert.equal(h.calls[0].filters.company, "A");
	assert.equal(h.queries[0].filters.is_group, undefined);
});

test("a root without child groups can classify its direct detail accounts", async () => {
	const h = formHarness([{ name: "Expenses" }]);
	await h.buttons["Cargar cuentas de mayor"]();
	assert.deepEqual(h.frm.doc.expenses.map(r => r.account), ["Expenses"]);
});

test("optional detail loading retains the automatic COGS treatment", async () => {
	const h = formHarness([{ name: "Goods", account_type: "Cost of Goods Sold" }, { name: "Rent" }]);
	await h.buttons["Cargar cuentas de detalle"]();
	assert.equal(h.calls[0].filters.is_group, 0);
	assert.deepEqual(h.frm.doc.expenses.map(r => [r.account, r.behavior]), [["Goods", "Costo de ventas"], ["Rent", ""]]);
});
