frappe.ui.form.on("Purchase Invoice", {
	async validate(frm) {
		if (frm.doc.supplier) return;

		const field = frm.get_field("supplier");
		if (field?.get_status?.() !== "Write") return;

		// A Link input can still display its selection while the document value is empty.
		// Resolve the link through Frappe before the mandatory-field check runs.
		const supplier = field.get_input_value?.();
		if (!supplier?.trim()) return;

		const result = await frappe.xcall("frappe.client.validate_link", {
			doctype: "Supplier",
			docname: supplier,
			fields: [],
		});

		if (!result?.name || frm.doc.supplier || field.get_input_value?.() !== supplier) {
			return;
		}

		await frm.set_value("supplier", result.name);
	},
});
