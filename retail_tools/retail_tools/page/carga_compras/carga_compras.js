/* global frappe, __ */
/* eslint-disable no-undef */

/**
 * Página de Carga de Compras desde Excel (carga-compras)
 *
 * Permite revisar una plantilla Excel, previsualizar y ajustar unidad de medida
 * y grupo por fila, actualizar precios de venta en hasta dos listas y registrar
 * una factura de compra enviada (update_stock=1) en una sola transacción.
 */

frappe.pages["carga-compras"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Carga de Compras"),
		single_column: true,
	});

	page.carga_compras = new retail_tools.CargaCompras(page, wrapper);
};

frappe.provide("retail_tools");

retail_tools.CargaCompras = class CargaCompras {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.$body = $(this.page.body);

		this.file_content = null;
		this.filename = "";
		this.row_overrides = {};
		this.preview_data = null;
		this.preview_token = null;
		this.preview_stale = false;
		this.current_upload_id = null;
		this.is_submitting = false;
		this.uom_list = [];
		this.item_group_list = [];

		this.make_actions();
		this.make_layout();
		this.load_initial_data();
	}

	generate_upload_id() {
		if (window.crypto && typeof window.crypto.randomUUID === "function") {
			return window.crypto.randomUUID();
		}
		return (
			"upl-" +
			Date.now().toString(36) +
			"-" +
			Math.random().toString(36).substring(2, 11)
		);
	}

	make_actions() {
		this.page.set_primary_action(__("Analizar Vista Previa"), () => {
			this.run_preview();
		});

		this.page.add_inner_button(__("Descargar Plantilla"), () => {
			this.download_template();
		});

		this.page.add_inner_button(__("Limpiar"), () => {
			this.reset_all();
		});
	}

	make_layout() {
		this.$body.html(`
			<div class="cc-wrapper">
				<div class="cc-card cc-header-card">
					<div class="cc-card-header">
						<div>
							<h4 class="cc-section-title">${__("Datos de la Compra y Listas de Precios")}</h4>
							<p class="text-muted cc-subtitle">
								${__("Complete los datos de cabecera antes de analizar el archivo Excel (.xlsx).")}
							</p>
						</div>
						<div class="cc-header-actions">
							<button type="button" class="btn btn-default btn-sm cc-download-template-btn">
								<i class="fa fa-download"></i> ${__("Descargar Plantilla Excel")}
							</button>
						</div>
					</div>
					<div class="cc-header-grid">
						<div class="cc-field" id="cc-company-field"></div>
						<div class="cc-field" id="cc-supplier-field"></div>
						<div class="cc-field" id="cc-posting-date-field"></div>
						<div class="cc-field" id="cc-due-date-field"></div>
						<div class="cc-field" id="cc-warehouse-field"></div>
						<div class="cc-field" id="cc-bill-no-field"></div>
						<div class="cc-field" id="cc-price-list-1-field"></div>
						<div class="cc-field" id="cc-price-list-2-field"></div>
						<div class="cc-field cc-field-remarks" id="cc-remarks-field"></div>
					</div>
					<div class="cc-file-bar">
						<div class="cc-file-input-wrap">
							<label class="cc-file-label" for="cc-xlsx-input">
								<i class="fa fa-file-excel-o"></i>
								<span class="cc-file-label-text">${__("Seleccionar archivo Excel (.xlsx)...")}</span>
							</label>
							<input type="file" id="cc-xlsx-input" accept=".xlsx" class="cc-file-input" />
						</div>
						<div class="cc-file-buttons">
							<button type="button" class="btn btn-default cc-preview-btn">
								<i class="fa fa-search"></i> ${__("Analizar Archivo")}
							</button>
							<button type="button" class="btn btn-primary cc-confirm-btn" disabled>
								<i class="fa fa-check"></i> ${__("Confirmar y Registrar Compra")}
							</button>
						</div>
					</div>
				</div>

				<div class="cc-result-banner" style="display: none;"></div>
				<div class="cc-alerts-container" style="display: none;"></div>
				<div class="cc-summary-container" style="display: none;"></div>

				<div class="cc-card cc-table-card" style="display: none;">
					<div class="cc-card-header">
						<h4 class="cc-section-title">${__("Vista Previa de Líneas")}</h4>
						<span class="text-muted cc-table-hint">
							${__("Puede ajustar Grupo y Unidad de Medida por fila; después de editar, revalide la vista previa.")}
						</span>
					</div>
					<div class="cc-table-responsive">
						<table class="table table-bordered cc-preview-table">
							<thead>
								<tr>
									<th class="cc-col-num">#</th>
									<th class="cc-col-code">${__("Código")}</th>
									<th class="cc-col-name">${__("Producto")}</th>
									<th class="cc-col-barcode">${__("Código de Barra")}</th>
									<th class="cc-col-status">${__("Estado")}</th>
									<th class="cc-col-uom">${__("Unidad")}</th>
									<th class="cc-col-group">${__("Grupo")}</th>
									<th class="cc-col-qty text-right">${__("Cantidad")}</th>
									<th class="cc-col-rate text-right">${__("Costo Unit.")}</th>
									<th class="cc-col-amount text-right">${__("Importe")}</th>
									<th class="cc-col-p1 text-right">${__("Precio Venta 1")}</th>
									<th class="cc-col-p2 text-right">${__("Precio Venta 2")}</th>
									<th class="cc-col-errors">${__("Validación")}</th>
								</tr>
							</thead>
							<tbody class="cc-preview-tbody"></tbody>
						</table>
					</div>
				</div>

				<datalist id="cc-uom-datalist"></datalist>
				<datalist id="cc-item-group-datalist"></datalist>
			</div>
		`);

		this.create_controls();
		this.bind_events();
	}

	create_controls() {
		this.company_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "company",
				label: __("Empresa"),
				options: "Company",
				reqd: 1,
				change: () => {
					this.on_company_change();
					this.mark_preview_stale();
				},
			},
			parent: this.$body.find("#cc-company-field"),
			render_input: true,
		});
		this.company_field.refresh();

		this.supplier_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "supplier",
				label: __("Proveedor"),
				options: "Supplier",
				reqd: 1,
				change: () => this.mark_preview_stale(),
			},
			parent: this.$body.find("#cc-supplier-field"),
			render_input: true,
		});
		this.supplier_field.refresh();

		const todayStr = frappe.datetime.get_today();
		this.last_synced_posting_date = todayStr;

		this.posting_date_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Date",
				fieldname: "posting_date",
				label: __("Fecha de Compra"),
				reqd: 1,
				default: todayStr,
				change: () => {
					const newPostingDate = this.posting_date_field.get_value();
					const currentDueDate = this.due_date_field ? this.due_date_field.get_value() : "";
					if (
						newPostingDate &&
						this.due_date_field &&
						(!currentDueDate || currentDueDate === this.last_synced_posting_date)
					) {
						this.last_synced_posting_date = newPostingDate;
						this.due_date_field.set_value(newPostingDate);
					} else if (newPostingDate) {
						this.last_synced_posting_date = newPostingDate;
					}
					this.mark_preview_stale();
				},
			},
			parent: this.$body.find("#cc-posting-date-field"),
			render_input: true,
		});
		this.posting_date_field.set_value(todayStr);
		this.posting_date_field.refresh();

		this.due_date_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Date",
				fieldname: "due_date",
				label: __("Fecha de Vencimiento"),
				reqd: 1,
				default: todayStr,
				change: () => this.mark_preview_stale(),
			},
			parent: this.$body.find("#cc-due-date-field"),
			render_input: true,
		});
		this.due_date_field.set_value(todayStr);
		this.due_date_field.refresh();

		this.warehouse_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "warehouse",
				label: __("Almacén"),
				options: "Warehouse",
				reqd: 1,
				get_query: () => {
					const company = this.company_field.get_value();
					const filters = { is_group: 0, disabled: 0 };
					if (company) {
						filters.company = company;
					}
					return { filters };
				},
				change: () => this.mark_preview_stale(),
			},
			parent: this.$body.find("#cc-warehouse-field"),
			render_input: true,
		});
		this.warehouse_field.refresh();

		this.bill_no_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Data",
				fieldname: "bill_no",
				label: __("N.º Factura Proveedor"),
				placeholder: __("Opcional"),
				change: () => this.mark_preview_stale(),
			},
			parent: this.$body.find("#cc-bill-no-field"),
			render_input: true,
		});
		this.bill_no_field.refresh();

		this.price_list_1_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "price_list_1",
				label: __("Lista de Precios 1"),
				options: "Price List",
				get_query: () => ({ filters: { selling: 1, enabled: 1 } }),
				change: () => this.mark_preview_stale(),
			},
			parent: this.$body.find("#cc-price-list-1-field"),
			render_input: true,
		});
		this.price_list_1_field.refresh();

		this.price_list_2_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "price_list_2",
				label: __("Lista de Precios 2"),
				options: "Price List",
				get_query: () => ({ filters: { selling: 1, enabled: 1 } }),
				change: () => this.mark_preview_stale(),
			},
			parent: this.$body.find("#cc-price-list-2-field"),
			render_input: true,
		});
		this.price_list_2_field.refresh();

		this.remarks_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Data",
				fieldname: "remarks",
				label: __("Observaciones (Remarks)"),
				placeholder: __("Opcional"),
				change: () => this.mark_preview_stale(),
			},
			parent: this.$body.find("#cc-remarks-field"),
			render_input: true,
		});
		this.remarks_field.refresh();
	}

	bind_events() {
		this.$body
			.find(".cc-download-template-btn")
			.on("click", () => this.download_template());

		this.$body.find("#cc-xlsx-input").on("change", (e) => {
			const file = e.target.files && e.target.files[0];
			if (!file) {
				return;
			}
			this.filename = file.name;
			this.$body.find(".cc-file-label-text").text(file.name);
			this.row_overrides = {};
			this.current_upload_id = this.generate_upload_id();

			const reader = new FileReader();
			reader.onload = (evt) => {
				this.file_content = evt.target.result;
				this.run_preview();
			};
			reader.readAsDataURL(file);
		});

		this.$body.find(".cc-preview-btn").on("click", () => this.run_preview());
		this.$body.find(".cc-confirm-btn").on("click", () => this.confirm_upload());
	}

	load_initial_data() {
		frappe.call({
			method:
				"retail_tools.retail_tools.page.carga_compras.carga_compras.get_initial_data",
			callback: (r) => {
				if (!r.message || !r.message.ok) {
					return;
				}
				const defaults = r.message.defaults || {};
				const settings = r.message.settings || {};

				if (defaults.company) {
					this.company_field.set_value(defaults.company);
				}
				if (defaults.posting_date) {
					this.last_synced_posting_date = defaults.posting_date;
					this.posting_date_field.set_value(defaults.posting_date);
				}
				if (defaults.due_date || defaults.posting_date) {
					this.due_date_field.set_value(defaults.due_date || defaults.posting_date);
				}
				if (defaults.warehouse) {
					this.warehouse_field.set_value(defaults.warehouse);
				}
				if (defaults.price_list_1) {
					this.price_list_1_field.set_value(defaults.price_list_1);
				}
				if (settings.bill_no_mandatory) {
					this.bill_no_field.df.reqd = 1;
					this.bill_no_field.df.placeholder = __("Obligatorio");
					this.bill_no_field.refresh();
				}
				this.load_catalog_suggestions();
			},
		});
	}

	load_catalog_suggestions() {
		frappe.db
			.get_list("UOM", {
				fields: ["name"],
				filters: { enabled: 1 },
				limit: 500,
				order_by: "name asc",
			})
			.then((rows) => {
				this.uom_list = (rows || []).map((r) => r.name);
				const optionsHtml = this.uom_list
					.map((u) => `<option value="${frappe.utils.escape_html(u)}"></option>`)
					.join("");
				this.$body.find("#cc-uom-datalist").html(optionsHtml);
			})
			.catch(() => {});

		frappe.db
			.get_list("Item Group", {
				fields: ["name"],
				filters: { is_group: 0 },
				limit: 500,
				order_by: "name asc",
			})
			.then((rows) => {
				this.item_group_list = (rows || []).map((r) => r.name);
				const optionsHtml = this.item_group_list
					.map((g) => `<option value="${frappe.utils.escape_html(g)}"></option>`)
					.join("");
				this.$body.find("#cc-item-group-datalist").html(optionsHtml);
			})
			.catch(() => {});
	}

	on_company_change() {
		const company = this.company_field.get_value();
		if (!company) {
			return;
		}
		frappe.call({
			method:
				"retail_tools.retail_tools.page.carga_compras.carga_compras.get_initial_data",
			args: { company },
			callback: (r) => {
				const wh = r.message?.defaults?.warehouse;
				if (wh) {
					this.warehouse_field.set_value(wh);
				}
			},
		});
	}

	download_template() {
		const url =
			"/api/method/retail_tools.retail_tools.page.carga_compras.carga_compras.download_template";
		window.open(url, "_blank");
	}

	get_header_values() {
		const postingDate = this.posting_date_field.get_value() || "";
		const dueDate =
			(this.due_date_field && this.due_date_field.get_value()) || postingDate;
		return {
			company: this.company_field.get_value() || "",
			supplier: this.supplier_field.get_value() || "",
			posting_date: postingDate,
			due_date: dueDate,
			warehouse: this.warehouse_field.get_value() || "",
			bill_no: this.bill_no_field.get_value() || "",
			price_list_1: this.price_list_1_field.get_value() || "",
			price_list_2: this.price_list_2_field.get_value() || "",
			remarks: (this.remarks_field && this.remarks_field.get_value() || "").trim(),
		};
	}

	mark_preview_stale() {
		if (!this.preview_data) {
			return;
		}
		this.preview_stale = true;
		this.update_confirm_button_state();
		this.render_alerts();
	}

	update_confirm_button_state() {
		const canConfirm =
			Boolean(this.preview_data) &&
			Boolean(this.preview_data.can_confirm) &&
			Boolean(this.preview_token) &&
			!this.preview_stale &&
			!this.is_submitting;

		this.$body.find(".cc-confirm-btn").prop("disabled", !canConfirm);
	}

	run_preview() {
		if (!this.file_content) {
			frappe.show_alert({
				message: __("Seleccione un archivo Excel (.xlsx) primero."),
				indicator: "orange",
			});
			return;
		}

		this.$body.find(".cc-result-banner").hide().empty();

		frappe.call({
			method:
				"retail_tools.retail_tools.page.carga_compras.carga_compras.preview_purchase_upload",
			args: {
				file_content: this.file_content,
				filename: this.filename,
				header: JSON.stringify(this.get_header_values()),
				row_overrides: JSON.stringify(this.row_overrides),
			},
			freeze: true,
			freeze_message: __("Analizando archivo y validando reglas de ERPNext..."),
			callback: (r) => {
				if (!r.message) {
					return;
				}
				this.preview_data = r.message;
				this.preview_token = r.message.preview_token || null;
				this.preview_stale = false;
				if (!this.current_upload_id) {
					this.current_upload_id = this.generate_upload_id();
				}

				this.render_alerts();
				this.render_summary();
				this.render_table();
				this.update_confirm_button_state();
			},
		});
	}

	render_alerts() {
		const $alerts = this.$body.find(".cc-alerts-container");
		if (!this.preview_data) {
			$alerts.hide().empty();
			return;
		}

		const globalErrors = this.preview_data.global_errors || [];
		const rowErrorsCount = this.preview_data.summary?.rows_with_errors || 0;
		const blocks = [];

		if (this.preview_stale) {
			blocks.push(`
				<div class="cc-alert cc-alert-warning">
					<div>
						<strong><i class="fa fa-refresh"></i> ${__("Vista previa pendiente de actualizar:")}</strong>
						${__("Se modificaron datos de cabecera o filas. Haga clic en «Analizar Archivo» para revalidar antes de confirmar.")}
					</div>
					<button type="button" class="btn btn-xs btn-warning cc-repreview-inline-btn">
						${__("Revalidar ahora")}
					</button>
				</div>
			`);
		}

		if (globalErrors.length > 0 || rowErrorsCount > 0) {
			const errorItems = globalErrors
				.map((err) => `<li>${frappe.utils.escape_html(err)}</li>`)
				.join("");
			const rowErrNote =
				rowErrorsCount > 0
					? `<li>${__("{0} fila(s) presentan errores en la tabla inferior. Corríjalos para poder confirmar.", [rowErrorsCount])}</li>`
					: "";

			blocks.push(`
				<div class="cc-alert cc-alert-danger">
					<strong><i class="fa fa-exclamation-triangle"></i> ${__("La carga está bloqueada por errores de validación:")}</strong>
					<ul class="cc-error-list">${errorItems}${rowErrNote}</ul>
				</div>
			`);
		} else if (!this.preview_stale && this.preview_data.can_confirm) {
			blocks.push(`
				<div class="cc-alert cc-alert-success">
					<i class="fa fa-check-circle"></i>
					<strong>${__("Validación exitosa:")}</strong>
					${__("Todas las filas y reglas de ERPNext fueron verificadas. Puede confirmar el registro de la compra.")}
				</div>
			`);
		}

		if (blocks.length > 0) {
			$alerts.html(blocks.join("")).show();
			$alerts
				.find(".cc-repreview-inline-btn")
				.on("click", () => this.run_preview());
		} else {
			$alerts.hide().empty();
		}
	}

	render_summary() {
		const $summary = this.$body.find(".cc-summary-container");
		const s = this.preview_data?.summary;
		if (!s || !s.total_rows) {
			$summary.hide().empty();
			return;
		}

		const currency = s.currency || "";
		const fmtMoney = (val) =>
			frappe.format(val || 0, { fieldtype: "Currency", currency });

		$summary
			.html(`
				<div class="cc-summary-grid">
					<div class="cc-kpi-card">
						<div class="cc-kpi-label">${__("Filas Analizadas")}</div>
						<div class="cc-kpi-value">${s.total_rows}</div>
						<div class="cc-kpi-sub">${__("Cant. total")}: ${flt(s.total_qty, 2)}</div>
					</div>
					<div class="cc-kpi-card">
						<div class="cc-kpi-label">${__("Productos")}</div>
						<div class="cc-kpi-value">${s.new_items} ${__("nuevos")} / ${s.existing_items} ${__("existentes")}</div>
						<div class="cc-kpi-sub">${__("A actualizar")}: ${s.updated_items || 0}</div>
					</div>
					<div class="cc-kpi-card">
						<div class="cc-kpi-label">${__("Precios de Venta")}</div>
						<div class="cc-kpi-value">${s.prices_to_create} ${__("nuevos")} / ${s.prices_to_update} ${__("cambios")}</div>
						<div class="cc-kpi-sub">${__("Sin cambio")}: ${s.prices_unchanged}</div>
					</div>
					<div class="cc-kpi-card">
						<div class="cc-kpi-label">${__("Subtotal / Impuestos")}</div>
						<div class="cc-kpi-value">${fmtMoney(s.net_total)}</div>
						<div class="cc-kpi-sub">${__("Impuestos")}: ${fmtMoney(s.total_taxes_and_charges)}</div>
					</div>
					<div class="cc-kpi-card cc-kpi-highlight">
						<div class="cc-kpi-label">${__("Total Factura")}</div>
						<div class="cc-kpi-value">${fmtMoney(s.grand_total)}</div>
						<div class="cc-kpi-sub">
							${s.due_date ? `${__("Vence")}: ${frappe.datetime.str_to_user(s.due_date)}` : ""}
						</div>
					</div>
				</div>
			`)
			.show();
	}

	format_price_cell(priceVal, priceInfo, currency) {
		if (priceVal === null || priceVal === undefined) {
			return `<span class="text-muted">-</span>`;
		}
		const formatted = frappe.format(priceVal, {
			fieldtype: "Currency",
			currency: currency || "",
		});
		const action = priceInfo?.action || "none";
		let badge = "";
		if (action === "create") {
			badge = `<span class="cc-badge cc-badge-new">${__("Nuevo")}</span>`;
		} else if (action === "update") {
			const prev =
				priceInfo.current_rate !== null && priceInfo.current_rate !== undefined
					? ` (${frappe.format(priceInfo.current_rate, { fieldtype: "Currency", currency: currency || "" })})`
					: "";
			badge = `<span class="cc-badge cc-badge-update" title="${__("Precio anterior")}${prev}">${__("Cambio")}</span>`;
		} else if (action === "unchanged") {
			badge = `<span class="cc-badge cc-badge-same">${__("Igual")}</span>`;
		}
		return `<div class="cc-price-cell"><span>${formatted}</span>${badge}</div>`;
	}

	render_table() {
		const $card = this.$body.find(".cc-table-card");
		const $tbody = this.$body.find(".cc-preview-tbody");
		const rows = this.preview_data?.rows || [];

		if (!rows.length) {
			$card.hide();
			$tbody.empty();
			return;
		}

		const invCurrency = this.preview_data?.summary?.currency || "";
		const pl1Currency =
			this.preview_data?.price_lists?.price_list_1?.currency || invCurrency;
		const pl2Currency =
			this.preview_data?.price_lists?.price_list_2?.currency || invCurrency;

		const html = rows
			.map((row) => {
				const hasErrors = row.errors && row.errors.length > 0;
				const rowClass = hasErrors ? "cc-row-error" : "";
				const statusBadge =
					row.status === "new"
						? `<span class="cc-badge cc-badge-status-new">${__("Nuevo")}</span>`
						: `<span class="cc-badge cc-badge-status-existing">${__("Existente")}</span>`;

				let nameHtml = `<div class="cc-item-name">${frappe.utils.escape_html(row.excel_item_name || row.item_name || "")}</div>`;
				if (
					row.status === "existing" &&
					row.db_item_name &&
					row.excel_item_name &&
					row.db_item_name.trim() !== row.excel_item_name.trim()
				) {
					nameHtml += `<div class="cc-item-subnote" title="${__("En productos existentes se conserva el nombre actual")}">
						${__("Actual")}: ${frappe.utils.escape_html(row.db_item_name)}
					</div>`;
				}

				let barcodeHtml = `<span class="cc-mono">${frappe.utils.escape_html(row.barcode || "-")}</span>`;
				if (
					row.status === "existing" &&
					row.db_barcodes &&
					row.db_barcodes.length > 0 &&
					(!row.barcode || !row.db_barcodes.includes(row.barcode))
				) {
					barcodeHtml += `<div class="cc-item-subnote">
						${__("Actual")}: ${frappe.utils.escape_html(row.db_barcodes.join(", "))}
					</div>`;
				}

				const uomInput = row.uom_locked
					? `<div class="cc-uom-locked" title="${__("Bloqueado: el producto ya tiene movimientos de inventario")}">
							<i class="fa fa-lock text-muted"></i>
							<span>${frappe.utils.escape_html(row.stock_uom || "")}</span>
					   </div>`
					: `<input type="text" class="form-control input-xs cc-row-uom-input"
							list="cc-uom-datalist"
							data-row-num="${row.row_num}"
							value="${frappe.utils.escape_html(row.stock_uom || "")}" />`;

				const groupInput = `<input type="text" class="form-control input-xs cc-row-group-input"
					list="cc-item-group-datalist"
					data-row-num="${row.row_num}"
					value="${frappe.utils.escape_html(row.item_group || "")}" />`;

				const qtyText =
					row.qty !== null && row.qty !== undefined ? flt(row.qty, 2) : "-";
				const rateText =
					row.rate !== null && row.rate !== undefined
						? frappe.format(row.rate, {
								fieldtype: "Currency",
								currency: invCurrency,
						  })
						: "-";
				const amountText = frappe.format(row.amount || 0, {
					fieldtype: "Currency",
					currency: invCurrency,
				});

				const p1Html = this.format_price_cell(
					row.price_1,
					row.price_1_info,
					pl1Currency
				);
				const p2Html = this.format_price_cell(
					row.price_2,
					row.price_2_info,
					pl2Currency
				);

				const errorsHtml = hasErrors
					? `<ul class="cc-row-error-list">${row.errors
							.map((e) => `<li>${frappe.utils.escape_html(e)}</li>`)
							.join("")}</ul>`
					: `<span class="cc-row-ok"><i class="fa fa-check"></i> ${__("OK")}</span>`;

				return `
					<tr class="${rowClass}" data-row-num="${row.row_num}">
						<td class="cc-col-num text-muted">${row.row_num}</td>
						<td class="cc-col-code cc-mono">${frappe.utils.escape_html(row.item_code || "")}</td>
						<td class="cc-col-name">${nameHtml}</td>
						<td class="cc-col-barcode">${barcodeHtml}</td>
						<td class="cc-col-status">${statusBadge}</td>
						<td class="cc-col-uom">${uomInput}</td>
						<td class="cc-col-group">${groupInput}</td>
						<td class="cc-col-qty text-right">${qtyText}</td>
						<td class="cc-col-rate text-right">${rateText}</td>
						<td class="cc-col-amount text-right">${amountText}</td>
						<td class="cc-col-p1 text-right">${p1Html}</td>
						<td class="cc-col-p2 text-right">${p2Html}</td>
						<td class="cc-col-errors">${errorsHtml}</td>
					</tr>
				`;
			})
			.join("");

		$tbody.html(html);
		$card.show();

		$tbody.find(".cc-row-uom-input").on("change", (e) => {
			const rowNum = String($(e.currentTarget).data("row-num"));
			const val = $(e.currentTarget).val().trim();
			this.row_overrides[rowNum] = this.row_overrides[rowNum] || {};
			this.row_overrides[rowNum].stock_uom = val;
			this.mark_preview_stale();
		});

		$tbody.find(".cc-row-group-input").on("change", (e) => {
			const rowNum = String($(e.currentTarget).data("row-num"));
			const val = $(e.currentTarget).val().trim();
			this.row_overrides[rowNum] = this.row_overrides[rowNum] || {};
			this.row_overrides[rowNum].item_group = val;
			this.mark_preview_stale();
		});
	}

	confirm_upload() {
		if (
			!this.preview_data ||
			!this.preview_data.can_confirm ||
			!this.preview_token ||
			this.preview_stale ||
			this.is_submitting
		) {
			return;
		}

		if (!this.current_upload_id) {
			this.current_upload_id = this.generate_upload_id();
		}

		this.is_submitting = true;
		this.update_confirm_button_state();

		frappe.call({
			method:
				"retail_tools.retail_tools.page.carga_compras.carga_compras.confirm_purchase_upload",
			args: {
				file_content: this.file_content,
				filename: this.filename,
				header: JSON.stringify(this.get_header_values()),
				row_overrides: JSON.stringify(this.row_overrides),
				preview_token: this.preview_token,
				upload_id: this.current_upload_id,
			},
			freeze: true,
			freeze_message: __(
				"Registrando productos, precios y enviando Factura de Compra..."
			),
			callback: (r) => {
				this.is_submitting = false;
				const res = r.message || {};

				if (res.ok) {
					this.preview_token = null;
					this.update_confirm_button_state();
					this.render_confirmation_success(res);
					frappe.show_alert({
						message: __("Factura de Compra {0} enviada exitosamente.", [
							res.invoice_name,
						]),
						indicator: "green",
					});
					return;
				}

				if (res.analysis) {
					this.preview_data = res.analysis;
					this.preview_token = res.analysis.preview_token || null;
					this.preview_stale = false;
					this.render_alerts();
					this.render_summary();
					this.render_table();
				}

				this.update_confirm_button_state();
				frappe.msgprint({
					title: __("No se pudo registrar la compra"),
					indicator: "red",
					message: frappe.utils.escape_html(
						res.message || __("Ocurrió un error al procesar la confirmación.")
					),
				});
			},
			error: () => {
				this.is_submitting = false;
				this.update_confirm_button_state();
			},
		});
	}

	render_confirmation_success(res) {
		const s = res.summary || {};
		const currency = s.currency || "";
		const totalFmt = frappe.format(s.grand_total || 0, {
			fieldtype: "Currency",
			currency,
		});
		const invoiceLink = `<a href="${frappe.utils.escape_html(res.invoice_url || `/app/purchase-invoice/${res.invoice_name}`)}" class="cc-invoice-link">${frappe.utils.escape_html(res.invoice_name)}</a>`;

		this.$body
			.find(".cc-result-banner")
			.html(`
				<div class="cc-success-card">
					<div class="cc-success-title">
						<i class="fa fa-check-circle"></i>
						${__("Factura de Compra registrada y enviada:")} ${invoiceLink}
					</div>
					<div class="cc-success-details">
						<span><strong>${__("Total Factura")}:</strong> ${totalFmt}</span>
						<span><strong>${__("Productos creados")}:</strong> ${s.created_items || 0}</span>
						<span><strong>${__("Productos actualizados")}:</strong> ${s.updated_items || 0}</span>
						<span><strong>${__("Precios creados")}:</strong> ${s.created_prices || 0}</span>
						<span><strong>${__("Precios actualizados")}:</strong> ${s.updated_prices || 0}</span>
						<span><strong>${__("Precios sin cambio")}:</strong> ${s.unchanged_prices || 0}</span>
					</div>
				</div>
			`)
			.show();
	}

	reset_all() {
		this.file_content = null;
		this.filename = "";
		this.row_overrides = {};
		this.preview_data = null;
		this.preview_token = null;
		this.preview_stale = false;
		this.current_upload_id = null;

		this.$body.find("#cc-xlsx-input").val("");
		this.$body
			.find(".cc-file-label-text")
			.text(__("Seleccionar archivo Excel (.xlsx)..."));
		this.$body.find(".cc-result-banner").hide().empty();
		this.$body.find(".cc-alerts-container").hide().empty();
		this.$body.find(".cc-summary-container").hide().empty();
		this.$body.find(".cc-table-card").hide();
		this.$body.find(".cc-preview-tbody").empty();
		this.update_confirm_button_state();
	}
};
