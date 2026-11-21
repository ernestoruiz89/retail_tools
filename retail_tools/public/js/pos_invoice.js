/* global frappe, __ */

const RT_POS_TRANSFER_ROLES = [
	"Administrator",
	"System Manager",
	"Accounts Manager",
	"RT Responsable de Tienda",
	"RT Administrador de Sistema",
];

function rt_can_transfer_pos_invoice() {
	if (frappe.session.user === "Administrator") {
		return true;
	}
	const userRoles = frappe.user_roles || [];
	return RT_POS_TRANSFER_ROLES.some((role) => userRoles.includes(role));
}

frappe.ui.form.on("POS Invoice", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.docstatus === 2) return;
		if (frm.doc.consolidated_invoice || frm.doc.status === "Consolidated") return;
		if (!rt_can_transfer_pos_invoice()) return;

		frm.add_custom_button(
			__("Trasladar a otro usuario"),
			() => {
				const d = new frappe.ui.Dialog({
					title: __("Trasladar Factura POS"),
					fields: [
						{
							fieldtype: "HTML",
							fieldname: "current_owner_info",
							options: `<p class="text-muted" style="margin-bottom: 10px;">
								${__("Usuario actual")}: <strong>${frappe.utils.escape_html(frm.doc.owner || "")}</strong>
							</p>`,
						},
						{
							label: __("Nuevo usuario"),
							fieldname: "new_owner",
							fieldtype: "Link",
							options: "User",
							reqd: 1,
							get_query: () => ({
								filters: {
									enabled: 1,
									name: ["not in", ["Guest", frm.doc.owner || ""]],
								},
							}),
						},
					],
					primary_action_label: __("Trasladar"),
					primary_action(values) {
						frappe.call({
							method: "retail_tools.utils.pos_invoice.transfer_pos_invoice_owner",
							args: {
								invoice_name: frm.doc.name,
								new_owner: values.new_owner,
							},
							freeze: true,
							freeze_message: __("Trasladando factura POS..."),
							callback(r) {
								if (r.message && r.message.ok) {
									d.hide();
									frappe.show_alert({
										message: __("Factura trasladada a {0}.", [r.message.new_owner]),
										indicator: "green",
									});
									frm.reload_doc();
								}
							},
						});
					},
				});
				d.show();
			},
			__("Acciones")
		);
	},
});
