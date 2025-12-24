/* global frappe, __ */
/* eslint-disable no-undef */

/**
 * Item Inspector Light Page
 *
 * A simplified dashboard for quick product lookup showing only:
 * - Stock levels (total and value)
 * - Current price with price list selector
 * - Price history chart and table
 */

frappe.pages["item-inspector-light"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Consulta Rápida"),
        single_column: true,
    });

    wrapper.item_inspector_light = new retail_tools.ItemInspectorLight(page, wrapper);
};

frappe.pages["item-inspector-light"].on_page_hide = function (wrapper) {
    if (wrapper.item_inspector_light && wrapper.item_inspector_light.destroy) {
        wrapper.item_inspector_light.destroy();
    }
};

frappe.provide("retail_tools");

retail_tools.ItemInspectorLight = class ItemInspectorLight {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.state = { item_code: null, snapshot: null };
        this._destroyed = false;

        this.make_filters();
        this.make_layout();
        this._bind_events();
    }

    _bind_events() {
        this._onResize = frappe.utils.debounce(() => {
            if (this._destroyed || !this.state.snapshot) return;

            const prices = this.state.snapshot.price_history || [];
            const pls = [...new Set(prices.map((p) => p.price_list).filter(Boolean))];
            const current = this.$priceControls?.find("[data-pl]")?.val() || pls[0];

            if (current) this.render_price_section(prices, current);
        }, 250);

        $(window).on("resize.item_inspector_light", this._onResize);
    }

    destroy() {
        this._destroyed = true;
        $(window).off("resize.item_inspector_light");
        if (this._price_chart) {
            this._price_chart = null;
        }
        this.state = { item_code: null, snapshot: null };
    }

    make_filters() {
        this.page.set_primary_action(__("Buscar"), () => this.load_selected_item());

        this.item_field = this.page.add_field({
            label: __("Producto"),
            fieldtype: "Link",
            options: "Item",
            fieldname: "item_code",
            change: () => this.load_selected_item(),
        });

        this.barcode_field = this.page.add_field({
            label: __("Código de barras"),
            fieldtype: "Data",
            fieldname: "barcode",
        });

        this.page.add_action_item(__("Escanear con cámara"), () => this.open_scanner());
    }

    make_layout() {
        const $body = $(this.page.body);

        $body.append(`
      <div class="item-inspector-light" role="main" aria-label="${__("Consulta Rápida")}">
        <div class="ii-grid">
          <div class="ii-card ii-overview">
            <div class="ii-header">
              <div class="ii-image" aria-hidden="true"></div>
              <div class="ii-main">
                <div class="ii-title"></div>
                <div class="ii-meta"></div>
                <div class="ii-tags" role="list" aria-label="${__("Etiquetas")}"></div>
              </div>
            </div>
            <div class="ii-kpis mt-3" role="list" aria-label="${__("Indicadores clave")}"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title" id="price-chart-heading">${__("Histórico de precios por lista")}</div>
            <div class="ii-price-controls mb-2"></div>
            <div class="ii-chart" id="ii-price-chart-light" role="img" aria-labelledby="price-chart-heading"></div>
            <div class="ii-table ii-price-table mt-3" role="region" aria-label="${__("Tabla de precios")}"></div>
          </div>
        </div>
      </div>
    `);

        this.$image = $body.find(".ii-image");
        this.$title = $body.find(".ii-title");
        this.$meta = $body.find(".ii-meta");
        this.$tags = $body.find(".ii-tags");
        this.$kpis = $body.find(".ii-kpis");
        this.$priceControls = $body.find(".ii-price-controls");
        this.$priceChart = $body.find("#ii-price-chart-light");
        this.$priceTable = $body.find(".ii-price-table");
    }

    open_scanner() {
        new frappe.ui.Scanner({
            dialog: true,
            multiple: false,
            on_scan: (data) => {
                const code = data && data.decodedText ? data.decodedText : "";
                if (!code) return;
                this.barcode_field.set_value(code);
                this.resolve_barcode(code);
            },
        });
    }

    load_selected_item() {
        const item_code = this.item_field.get_value();
        if (!item_code) return;
        this.load_snapshot(item_code);
    }

    _handle_error(error, context) {
        console.error(`Item Inspector Light - ${context}:`, error);
        frappe.msgprint({
            title: __("Error"),
            indicator: "red",
            message: __("Error al {0}. Por favor intente nuevamente.", [context]),
        });
    }

    resolve_barcode(barcode) {
        frappe.call({
            method: "retail_tools.retail_tools.page.item_inspector.item_inspector.resolve_item_from_barcode",
            args: { barcode },
            callback: (r) => {
                if (this._destroyed) return;

                const res = r.message;
                if (!res || !res.ok) {
                    frappe.msgprint(res?.message || __("No se encontró producto."));
                    return;
                }

                if (res.item_code) {
                    this.item_field.set_value(res.item_code);
                    this.load_snapshot(res.item_code);
                    return;
                }

                if (res.matches && res.matches.length) {
                    this._show_item_selector(res.matches);
                }
            },
            error: (err) => this._handle_error(err, __("buscar código de barras")),
        });
    }

    _show_item_selector(matches) {
        const d = new frappe.ui.Dialog({
            title: __("Selecciona un producto"),
            fields: [
                {
                    fieldtype: "Select",
                    fieldname: "item_code",
                    label: __("Producto"),
                    options: matches.map((x) => `${x.item_code} - ${x.item_name || ""}`),
                    reqd: 1,
                },
            ],
            primary_action_label: __("Abrir"),
            primary_action: () => {
                const val = d.get_value("item_code");
                const code = val.split(" - ")[0].trim();
                d.hide();
                this.item_field.set_value(code);
                this.load_snapshot(code);
            },
        });
        d.show();
    }

    load_snapshot(item_code) {
        this.state.item_code = item_code;

        frappe.call({
            method: "retail_tools.retail_tools.page.item_inspector.item_inspector.get_item_snapshot",
            args: { item_code },
            freeze: true,
            callback: (r) => {
                if (this._destroyed) return;

                const res = r.message;
                if (!res || !res.ok) return;

                this.state.snapshot = res;
                this.render(res);
            },
            error: (err) => this._handle_error(err, __("cargar información del producto")),
        });
    }

    render(res) {
        const item = res.item || {};
        const bins = res.bins || [];
        const barcodes = res.barcodes || [];
        const prices = res.price_history || [];
        const sellingPrice = res.selling_price || { price: 0 };

        this._render_header(item, barcodes, bins);
        this._render_kpis(bins, sellingPrice);
        this._render_price_section(prices);
    }

    _render_header(item, barcodes, bins) {
        const img = item.image
            ? `<img src="${encodeURI(item.image)}" alt="${frappe.utils.escape_html(item.item_name || "Item")}" style="width:72px;height:72px;object-fit:cover;border-radius:12px;" />`
            : `<div class="ii-img-fallback" aria-label="${__("Sin imagen")}">${(item.item_name || item.item_code || "?").slice(0, 1)}</div>`;

        this.$image.html(img);
        this.$title.html(`
      <div class="h4 mb-1">${frappe.utils.escape_html(item.item_name || "")}</div>
      <div class="text-muted">${frappe.utils.escape_html(item.item_code || "")}</div>
    `);

        this.$meta.html(`
      <div class="text-muted">
        ${__("UoM")}: <b>${frappe.utils.escape_html(item.stock_uom || "-")}</b>
      </div>
    `);

        const tags = [];
        if (barcodes.length)
            tags.push({ text: `${__("Barcodes")}: ${barcodes.map(frappe.utils.escape_html).join(", ")}`, color: "light" });
        if (item.disabled) tags.push({ text: __("DESHABILITADO"), color: "danger" });
        if (!item.is_stock_item) tags.push({ text: __("No es stock item"), color: "warning" });

        // Alert: Low stock
        const total_qty = bins.reduce((acc, b) => acc + (flt(b.actual_qty) || 0), 0);
        const reorder_level = flt(item.reorder_level) || 0;
        if (reorder_level > 0 && total_qty < reorder_level) {
            tags.push({ text: `⚠️ ${__("Stock bajo")}`, color: "danger" });
        }

        this.$tags.html(
            tags
                .map((t) => `<span class="badge badge-${t.color} mr-1" role="listitem">${t.text}</span>`)
                .join("")
        );
    }

    _render_kpis(bins, sellingPrice) {
        const total_qty = bins.reduce((acc, b) => acc + (flt(b.actual_qty) || 0), 0);
        const total_value = bins.reduce((acc, b) => acc + (flt(b.stock_value_est) || 0), 0);
        const sell_price = flt(sellingPrice.price) || 0;

        // Store for margin recalculation
        this.state.avg_valuation = total_qty > 0 ? total_value / total_qty : 0;

        this.$kpis.html(`
      <div class="ii-kpi" role="listitem">
        <div class="ii-kpi-label">${__("Existencia total")}</div>
        <div class="ii-kpi-value">${frappe.format(total_qty, { fieldtype: "Float" })}</div>
      </div>
      <div class="ii-kpi" role="listitem">
        <div class="ii-kpi-label">${__("Costo estimado")}</div>
        <div class="ii-kpi-value">${frappe.format(total_value, { fieldtype: "Currency" })}</div>
      </div>
      <div class="ii-kpi" role="listitem" id="ii-kpi-price-light">
        <div class="ii-kpi-label">${__("Precio actual")}${sellingPrice.price_list ? ` <small class="text-muted">(${frappe.utils.escape_html(sellingPrice.price_list)})</small>` : ""}</div>
        <div class="ii-kpi-value">${sell_price > 0 ? frappe.format(sell_price, { fieldtype: "Currency" }) : "-"}</div>
      </div>
    `);
    }

    _render_price_section(prices) {
        const priceLists = [...new Set(prices.map((p) => p.price_list).filter(Boolean))];
        const selected = priceLists[0] || null;

        this.$priceControls.html(
            priceLists.length
                ? `<div class="form-inline">
             <label class="mr-2" for="price-list-select-light">${__("Lista de precios")}</label>
             <select class="form-control form-control-sm" id="price-list-select-light" data-pl aria-label="${__("Seleccionar lista de precios")}"></select>
           </div>`
                : `<div class="text-muted">${__("No hay Item Price para este producto.")}</div>`
        );

        if (priceLists.length) {
            const $pl = this.$priceControls.find("[data-pl]");
            priceLists.forEach((pl) =>
                $pl.append(`<option value="${frappe.utils.escape_html(pl)}">${frappe.utils.escape_html(pl)}</option>`)
            );
            $pl.val(selected);
            $pl.on("change", () => this.render_price_section(prices, $pl.val()));
            this.render_price_section(prices, selected);
        } else {
            this.$priceChart.empty();
            this.$priceTable.empty();
        }
    }

    _update_price_kpi(priceRows, price_list) {
        const $priceKpi = $("#ii-kpi-price-light");
        if (!$priceKpi.length) return;

        const latestPrice = priceRows.length > 0 ? priceRows[priceRows.length - 1] : null;
        const sell_price = latestPrice ? flt(latestPrice.price_list_rate) : 0;

        $priceKpi.html(`
      <div class="ii-kpi-label">${__("Precio actual")}${price_list ? ` <small class="text-muted">(${frappe.utils.escape_html(price_list)})</small>` : ""}</div>
      <div class="ii-kpi-value">${sell_price > 0 ? frappe.format(sell_price, { fieldtype: "Currency" }) : "-"}</div>
    `);
    }

    render_price_section(prices, price_list) {
        const rows = (prices || []).filter((p) => p.price_list === price_list);

        this._update_price_kpi(rows, price_list);

        const toFloat = (x) => {
            if (x === null || x === undefined) return 0;
            const s = String(x).replace(/,/g, "").trim();
            const n = Number(s);
            return Number.isFinite(n) ? n : 0;
        };

        const pickDate = (r) => r.valid_from || r.creation || r.modified || "";
        let labels = rows.map((r) => String(pickDate(r)).slice(0, 10)).map((x) => x || __("Sin fecha"));
        let values = rows.map((r) => toFloat(r.price_list_rate));

        if (labels.length === 1) {
            const d0 = labels[0];
            let d1 = d0;
            if (/^\d{4}-\d{2}-\d{2}$/.test(d0)) {
                d1 = frappe.datetime.add_days(d0, 1);
            } else {
                d1 = `${d0} `;
            }
            labels = [d0, d1];
            values = [values[0], values[0]];
        }

        this.$priceChart.empty();
        this.$priceChart.css("min-height", "260px");

        if (!labels.length) {
            this.$priceChart.html(`<div class="text-muted">${__("No hay puntos para graficar.")}</div>`);
        } else if (!frappe.Chart) {
            this.$priceChart.html(`<div class="text-muted">${__("No se encontró frappe.Chart (assets).")}</div>`);
        } else {
            this._price_chart = new frappe.Chart(this.$priceChart[0], {
                title: `${__("Histórico")} • ${price_list}`,
                data: { labels, datasets: [{ name: price_list, values }] },
                type: "line",
                height: 260,
                truncateLegends: true,
                lineOptions: { regionFill: 0, hideDots: 0 },
            });
        }

        this.$priceTable.html(
            this.render_table(["valid_from", "price_list_rate", "currency", "modified"], rows.slice(-10).reverse(), {
                valid_from: __("Desde"),
                price_list_rate: __("Precio"),
                currency: __("Moneda"),
                modified: __("Modificado"),
            })
        );
    }

    render_table(columns, rows, labels) {
        rows = rows || [];
        const ths = columns
            .map((c) => `<th scope="col">${frappe.utils.escape_html(labels[c] || c)}</th>`)
            .join("");
        const trs = rows
            .map((r) => {
                const tds = columns.map((c) => `<td>${this.format_cell(c, r[c])}</td>`).join("");
                return `<tr>${tds}</tr>`;
            })
            .join("");

        return `
      <div class="table-responsive">
        <table class="table table-bordered table-sm" role="table">
          <thead><tr>${ths}</tr></thead>
          <tbody>${trs || `<tr><td colspan="${columns.length}" class="text-muted">${__("Sin datos")}</td></tr>`}</tbody>
        </table>
      </div>
    `;
    }

    format_cell(col, val) {
        if (val === null || val === undefined) return "-";

        const numCols = ["price_list_rate"];
        if (numCols.includes(col)) {
            return frappe.format(flt(val) || 0, { fieldtype: "Currency" });
        }

        return frappe.utils.escape_html(String(val));
    }
};
