frappe.ui.form.on("Retail Indicator Settings", {
	setup(frm) {
		frm.set_query("account", "expenses", () => ({
			filters: { company: frm.doc.company, root_type: "Expense" }
		}));
	},
	refresh(frm) {
		if (!frm.doc.company || !frm.perm.some(p => p.write || p.create)) return;
		frm.add_custom_button(__("Cargar cuentas de mayor"), () => rt_load_indicator_expense_accounts(frm, true));
		frm.add_custom_button(__("Cargar cuentas de detalle"), () => rt_load_indicator_expense_accounts(frm, false), __("Cargar cuentas"));
	}
});

async function rt_load_indicator_expense_accounts(frm, groups) {
	let accounts = await frappe.db.get_list("Account", {
		filters: { company: frm.doc.company, root_type: "Expense", is_group: groups ? 1 : 0, disabled: 0 },
		fields: ["name", "account_type", "parent_account"], order_by: "name", limit: 0
	});
	if (groups) {
		const names = new Set(accounts.map(account => account.name));
		const roots = new Set(accounts.filter(account => !names.has(account.parent_account)).map(account => account.name));
		const parents = new Set(accounts.map(account => account.parent_account));
		accounts = accounts.filter(account => roots.has(account.parent_account) || (roots.has(account.name) && !parents.has(account.name)));
	}
	const existing = new Set((frm.doc.expenses || []).map(row => row.account));
	let added = 0;
	for (const account of accounts) {
		if (existing.has(account.name)) continue;
		frm.add_child("expenses", {
			account: account.name,
			behavior: !groups && account.account_type === "Cost of Goods Sold" ? "Costo de ventas" : ""
		});
		added++;
	}
	if (added) {
		frm.refresh_field("expenses");
		frm.dirty();
	}
	frappe.show_alert({ message: __("{0} cuentas agregadas.", [added]), indicator: "green" });
}

frappe.ui.form.on("Retail Indicator Target", {
	indicator(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const lower = ["Peso de gastos operativos (%)", "Endeudamiento (%)", "Capital estancado (%)", "Agotados con demanda (%)", "Descuentos (%)", "Devoluciones (%)", "Ciclo de efectivo (días)"];
		const annual = ["ROA anual (%)", "ROE anual (%)", "Rotación de inventario anual (veces)", "GMROI"];
		const rule = row.indicator === "Días de inventario (DIO)" ? "Rango de días" : lower.includes(row.indicator) ? "Máximo" : "Mínimo";
		frappe.model.set_value(cdt, cdn, "target_rule", rule + (annual.includes(row.indicator) ? " anual" : ""));
	}
});
