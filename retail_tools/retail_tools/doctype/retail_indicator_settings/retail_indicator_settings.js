frappe.ui.form.on("Retail Indicator Settings", {
	setup(frm) {
		frm.set_query("account", "expenses", () => ({
			filters: { company: frm.doc.company, root_type: "Expense", is_group: 0 }
		}));
	},
	refresh(frm) {
		if (!frm.doc.company || !frm.perm.some(p => p.write || p.create)) return;
		frm.add_custom_button(__("Cargar cuentas de gastos"), async () => {
			const accounts = await frappe.db.get_list("Account", {
				filters: { company: frm.doc.company, root_type: "Expense", is_group: 0, disabled: 0 },
				fields: ["name", "account_type"], order_by: "name", limit: 0
			});
			const existing = new Set((frm.doc.expenses || []).map(row => row.account));
			for (const account of accounts) {
				if (!existing.has(account.name)) frm.add_child("expenses", {
					account: account.name,
					behavior: account.account_type === "Cost of Goods Sold" ? "Costo de ventas" : ""
				});
			}
			frm.refresh_field("expenses");
			frm.dirty();
		});
	}
});

frappe.ui.form.on("Retail Indicator Target", {
	indicator(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const lower = ["Peso de gastos operativos (%)", "Endeudamiento (%)", "Capital estancado (%)", "Agotados con demanda (%)", "Descuentos (%)", "Devoluciones (%)", "Ciclo de efectivo (días)"];
		const annual = ["ROA anual (%)", "ROE anual (%)", "Rotación de inventario anual (veces)", "GMROI"];
		const rule = row.indicator === "Días de inventario (DIO)" ? "Rango de días" : lower.includes(row.indicator) ? "Máximo" : "Mínimo";
		frappe.model.set_value(cdt, cdn, "target_rule", rule + (annual.includes(row.indicator) ? " anual" : ""));
	}
});
