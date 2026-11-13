const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
	path.join(__dirname, "../retail_tools/public/js/purchase_invoice.js"),
	"utf8"
);

function setup({ documentSupplier = "", inputSupplier = "", response = { name: inputSupplier } } = {}) {
	let validate;
	const calls = [];
	const field = {
		get_status: () => "Write",
		get_input_value: () => inputSupplier,
	};
	const frm = {
		doc: { supplier: documentSupplier },
		get_field: () => field,
		set_value: async (name, value) => {
			calls.push(["set_value", name, value]);
			frm.doc[name] = value;
		},
	};
	const frappe = {
		ui: { form: { on: (_doctype, handlers) => (validate = handlers.validate) } },
		xcall: async (method, args) => {
			calls.push(["xcall", method, args]);
			return response;
		},
	};
	vm.runInNewContext(source, { frappe });
	return { validate, frm, field, calls };
}

test("keeps an already stored supplier without another lookup", async () => {
	const { validate, frm, calls } = setup({ documentSupplier: "Other Supplier", inputSupplier: "Bebe Feliz" });
	await validate(frm);
	assert.equal(frm.doc.supplier, "Other Supplier");
	assert.equal(calls.length, 0);
});

test("recovers a visible supplier only after server link validation", async () => {
	const { validate, frm, calls } = setup({ inputSupplier: "Bebe Feliz" });
	await validate(frm);
	assert.equal(frm.doc.supplier, "Bebe Feliz");
	assert.deepEqual(calls[0][0], "xcall");
	assert.equal(calls[0][1], "frappe.client.validate_link");
	assert.equal(calls[0][2].doctype, "Supplier");
	assert.equal(calls[0][2].docname, "Bebe Feliz");
	assert.deepEqual(calls[1], ["set_value", "supplier", "Bebe Feliz"]);
});

test("does not accept an invalid supplier or an empty input", async () => {
	const invalid = setup({ inputSupplier: "Unknown", response: {} });
	await invalid.validate(invalid.frm);
	assert.equal(invalid.frm.doc.supplier, "");
	assert.equal(invalid.calls.length, 1);

	const empty = setup();
	await empty.validate(empty.frm);
	assert.equal(empty.calls.length, 0);
});

test("does not overwrite a supplier selected during validation", async () => {
	let resolveLookup;
	const lookup = new Promise((resolve) => (resolveLookup = resolve));
	const setupData = setup({ inputSupplier: "Bebe Feliz", response: lookup });
	const pendingValidation = setupData.validate(setupData.frm);
	setupData.frm.doc.supplier = "New Supplier";
	resolveLookup({ name: "Bebe Feliz" });
	await pendingValidation;
	assert.equal(setupData.frm.doc.supplier, "New Supplier");
	assert.equal(setupData.calls.length, 1);
});

test("does not restore a supplier after the input changes", async () => {
	let resolveLookup;
	const lookup = new Promise((resolve) => (resolveLookup = resolve));
	const setupData = setup({ inputSupplier: "Bebe Feliz", response: lookup });
	const pendingValidation = setupData.validate(setupData.frm);
	setupData.field.get_input_value = () => "Another Supplier";
	resolveLookup({ name: "Bebe Feliz" });
	await pendingValidation;
	assert.equal(setupData.frm.doc.supplier, "");
	assert.equal(setupData.calls.length, 1);
});
