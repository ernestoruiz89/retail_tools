/* global frappe, __ */
/* eslint-disable no-undef */

/**
 * Item Inspector Page
 *
 * A dashboard-style page for quickly looking up item information including:
 * - Stock levels by warehouse
 * - Price history with charts
 * - Recent sales and purchases
 *
 * Features:
 * - Barcode scanning support
 * - Responsive mobile-first design
 * - Price history visualization
 */

frappe.pages["item-inspector"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Consulta de Producto"),
    single_column: true,
  });

  wrapper.item_inspector = new retail_tools.ItemInspector(page, wrapper);
};

frappe.pages["item-inspector"].on_page_hide = function (wrapper) {
  if (wrapper.item_inspector && wrapper.item_inspector.destroy) {
    wrapper.item_inspector.destroy();
  }
};

frappe.provide("retail_tools");

retail_tools.ItemInspector = class ItemInspector {
  /**
   * Initialize the Item Inspector component
   * @param {Object} page - Frappe page object
   * @param {HTMLElement} wrapper - Page wrapper element
   */
  constructor(page, wrapper) {
    this.page = page;
    this.wrapper = wrapper;
    this.state = { item_code: null, snapshot: null };
    this._destroyed = false;

    this.make_filters();
    this.make_layout();
    this._bind_events();
  }

  /**
   * Bind global event handlers
   */
  _bind_events() {
    this._onResize = frappe.utils.debounce(() => {
      if (this._destroyed || !this.state.snapshot) return;

      const prices = this.state.snapshot.price_history || [];
      const pls = [...new Set(prices.map((p) => p.price_list).filter(Boolean))];
      const current = this.$priceControls?.find("[data-pl]")?.val() || pls[0];

      if (current) this.render_price_section(prices, current);
    }, 250);

    $(window).on("resize.item_inspector", this._onResize);
  }

  /**
   * Clean up event handlers and resources
   */
  destroy() {
    this._destroyed = true;

    // Remove resize handler
    $(window).off("resize.item_inspector");

    // Clean up chart instance
    if (this._price_chart) {
      this._price_chart = null;
    }

    // Remove action button handlers
    if (this.$actions) {
      this.$actions.find("[data-open-item]").off("click");
      this.$actions.find("[data-open-stock]").off("click");
    }

    // Clear state
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
      <div class="item-inspector" role="main" aria-label="${__("Consulta de Producto")}">
        <div class="ii-grid">
          <div class="ii-card ii-overview">
            <div class="ii-header">
              <div class="ii-image" aria-hidden="true"></div>
              <div class="ii-main">
                <div class="ii-title"></div>
                <div class="ii-meta"></div>
                <div class="ii-tags" role="list" aria-label="${__("Etiquetas")}"></div>
                <div class="ii-actions mt-2"></div>
              </div>
            </div>
            <div class="ii-kpis mt-3" role="list" aria-label="${__("Indicadores clave")}"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title" id="stock-table-heading">${__("Existencia por almacén")}</div>
            <div class="ii-table ii-stock-table" role="region" aria-labelledby="stock-table-heading"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title" id="price-chart-heading">${__("Histórico de precios por lista")}</div>
            <div class="ii-price-controls mb-2"></div>
            <div class="ii-chart" id="ii-price-chart" role="img" aria-labelledby="price-chart-heading"></div>
            <div class="ii-table ii-price-table mt-3" role="region" aria-label="${__("Tabla de precios")}"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title" id="sales-table-heading">${__("Últimas ventas")}</div>
            <div class="ii-table ii-sales-table" role="region" aria-labelledby="sales-table-heading"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title" id="purchase-table-heading">${__("Últimas compras")}</div>
            <div class="ii-table ii-purchase-table" role="region" aria-labelledby="purchase-table-heading"></div>
          </div>
        </div>
      </div>
    `);

    this.$image = $body.find(".ii-image");
    this.$title = $body.find(".ii-title");
    this.$meta = $body.find(".ii-meta");
    this.$tags = $body.find(".ii-tags");
    this.$actions = $body.find(".ii-actions");
    this.$kpis = $body.find(".ii-kpis");

    this.$stockTable = $body.find(".ii-stock-table");
    this.$priceControls = $body.find(".ii-price-controls");
    this.$priceChart = $body.find("#ii-price-chart");
    this.$priceTable = $body.find(".ii-price-table");
    this.$salesTable = $body.find(".ii-sales-table");
    this.$purchaseTable = $body.find(".ii-purchase-table");
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

  /**
   * Handle API error responses
   * @param {Object} error - Error object from frappe.call
   * @param {string} context - Description of what failed
   */
  _handle_error(error, context) {
    console.error(`Item Inspector - ${context}:`, error);
    frappe.msgprint({
      title: __("Error"),
      indicator: "red",
      message: __("Error al {0}. Por favor intente nuevamente.", [context]),
    });
  }

  resolve_barcode(barcode) {
    frappe.call({
      method:
        "retail_tools.retail_tools.page.item_inspector.item_inspector.resolve_item_from_barcode",
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

  /**
   * Show dialog to select from multiple matching items
   * @param {Array} matches - List of matching item objects
   */
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
    const sales = res.recent_sales || [];
    const purchases = res.recent_purchases || [];
    const salesLast30 = res.sales_last_30_days || { qty: 0, count: 0 };
    const sellingPrice = res.selling_price || { price: 0 };
    const daysSinceLastSale = res.days_since_last_sale;

    this._render_header(item, barcodes, bins, daysSinceLastSale);
    this._render_kpis(bins, sales, purchases, salesLast30, sellingPrice, daysSinceLastSale);
    this._render_stock_table(bins);
    this._render_price_section(prices);
    this._render_transaction_tables(sales, purchases);
  }

  /**
   * Render the header section with item info
   */
  _render_header(item, barcodes, bins, daysSinceLastSale) {
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
        ${__("Grupo")}: <b>${frappe.utils.escape_html(item.item_group || "-")}</b>
        &nbsp;•&nbsp;
        ${__("Marca")}: <b>${frappe.utils.escape_html(item.brand || "-")}</b>
        &nbsp;•&nbsp;
        ${__("UoM")}: <b>${frappe.utils.escape_html(item.stock_uom || "-")}</b>
      </div>
      <div class="mt-1">${frappe.utils.escape_html(frappe.utils.html2text(item.description || "").slice(0, 160))}</div>
    `);

    const tags = [];
    if (barcodes.length)
      tags.push({ text: `${__("Barcodes")}: ${barcodes.map(frappe.utils.escape_html).join(", ")}`, color: "light" });
    if (item.disabled) tags.push({ text: __("DESHABILITADO"), color: "danger" });
    if (!item.is_stock_item) tags.push({ text: __("No es stock item"), color: "warning" });

    // Alert: Low stock (below reorder level)
    const total_qty = bins.reduce((acc, b) => acc + (flt(b.actual_qty) || 0), 0);
    const reorder_level = flt(item.reorder_level) || 0;
    if (reorder_level > 0 && total_qty < reorder_level) {
      tags.push({ text: `⚠️ ${__("Stock bajo")}`, color: "danger" });
    }

    // Alert: No sales in 60+ days
    if (daysSinceLastSale !== null && daysSinceLastSale >= 60) {
      tags.push({ text: `⏰ ${__("Sin ventas 60+ días")}`, color: "warning" });
    }

    this.$tags.html(
      tags
        .map((t) => `<span class="badge badge-${t.color} mr-1" role="listitem">${t.text}</span>`)
        .join("")
    );

    this._render_actions(item);
  }

  /**
   * Render action buttons
   */
  _render_actions(item) {
    // Remove old handlers first
    this.$actions.find("[data-open-item]").off("click");
    this.$actions.find("[data-open-stock]").off("click");
    this.$actions.find("[data-open-ledger]").off("click");

    this.$actions.html(`
      <div class="ii-actions-grid">
        <button class="btn btn-sm btn-primary" data-open-item aria-label="${__("Abrir formulario de Item")}">${__("Abrir Item")}</button>
        <button class="btn btn-sm btn-default" data-open-stock aria-label="${__("Ver reporte de Stock Balance")}">${__("Saldos")}</button>
        <button class="btn btn-sm btn-default" data-open-ledger aria-label="${__("Ver movimientos de inventario")}">${__("Movimientos")}</button>
      </div>
    `);

    this.$actions
      .find("[data-open-item]")
      .on("click", () => frappe.set_route("Form", "Item", item.item_code));

    this.$actions.find("[data-open-stock]").on("click", () => {
      const item_code = this.state?.item_code || this.item_field.get_value();
      frappe.set_route("query-report", "Stock Balance", { item_code });
    });

    this.$actions.find("[data-open-ledger]").on("click", () => {
      const item_code = this.state?.item_code || this.item_field.get_value();
      frappe.set_route("query-report", "Stock Ledger", { item_code });
    });
  }

  /**
   * Render KPI cards
   */
  _render_kpis(bins, sales, purchases, salesLast30, sellingPrice, daysSinceLastSale) {
    const total_qty = bins.reduce((acc, b) => acc + (flt(b.actual_qty) || 0), 0);
    const total_value = bins.reduce((acc, b) => acc + (flt(b.stock_value_est) || 0), 0);

    const last_sale = sales[0];
    const last_purchase = purchases[0];

    // Calculate profit margin: (selling_price - avg_valuation_rate) / selling_price * 100
    const avg_valuation = total_qty > 0 ? total_value / total_qty : 0;
    const sell_price = flt(sellingPrice.price) || 0;
    let margin_pct = 0;
    let margin_class = "";
    if (sell_price > 0 && avg_valuation > 0) {
      margin_pct = ((sell_price - avg_valuation) / sell_price) * 100;
      margin_class = margin_pct >= 20 ? "text-success" : margin_pct >= 10 ? "text-warning" : "text-danger";
    }

    // Days without movement color coding
    let days_class = "";
    if (daysSinceLastSale !== null) {
      days_class = daysSinceLastSale >= 60 ? "text-danger" : daysSinceLastSale >= 30 ? "text-warning" : "text-success";
    }

    this.$kpis.html(`
      <div class="ii-kpi" role="listitem">
        <div class="ii-kpi-label">${__("Existencia total")}</div>
        <div class="ii-kpi-value">${frappe.format(total_qty, { fieldtype: "Float" })}</div>
      </div>
      <div class="ii-kpi" role="listitem">
        <div class="ii-kpi-label">${__("Costo estimado (stock)")}</div>
        <div class="ii-kpi-value">${frappe.format(total_value, { fieldtype: "Currency" })}</div>
      </div>
      <div class="ii-kpi" role="listitem" id="ii-kpi-price">
        <div class="ii-kpi-label">${__("Precio actual")}${sellingPrice.price_list ? ` <small class="text-muted">(${frappe.utils.escape_html(sellingPrice.price_list)})</small>` : ""}</div>
        <div class="ii-kpi-value">${sell_price > 0 ? frappe.format(sell_price, { fieldtype: "Currency" }) : "-"}</div>
      </div>
      <div class="ii-kpi" role="listitem">
        <div class="ii-kpi-label">${__("Ventas 30 días")} <small class="text-muted" style="white-space:nowrap">(${flt(salesLast30.qty)} ${__("unidades")} / ${salesLast30.count} ${__("facturas")})</small></div>
        <div class="ii-kpi-value">${frappe.format(salesLast30.amount, { fieldtype: "Currency" })}</div>
      </div>
      <div class="ii-kpi" role="listitem" id="ii-kpi-margin">
        <div class="ii-kpi-label">${__("Margen de utilidad")}</div>
        <div class="ii-kpi-value ${margin_class}">${sell_price > 0 ? margin_pct.toFixed(1) + "%" : "-"}</div>
      </div>
      <div class="ii-kpi" role="listitem">
        <div class="ii-kpi-label">${__("Días sin movimiento")}</div>
        <div class="ii-kpi-value ${days_class}">${daysSinceLastSale !== null ? daysSinceLastSale : "-"}</div>
      </div>
      <div class="ii-kpi" role="listitem">
        <div class="ii-kpi-label">${__("Última venta")}${last_sale ? ` (${last_sale.posting_date})` : ""}</div>
        <div class="ii-kpi-value">${last_sale ? frappe.format(last_sale.amount, { fieldtype: "Currency" }) : "-"}</div>
        ${last_sale ? `<div class="ii-kpi-detail text-muted" style="font-size:11px;margin-top:2px;white-space:nowrap">${flt(last_sale.qty)} ${__("unidades")} a ${frappe.format(last_sale.rate, { fieldtype: "Currency" })}</div>` : ""}
      </div>
      <div class="ii-kpi" role="listitem">
        <div class="ii-kpi-label">${__("Última compra")}${last_purchase ? ` (${last_purchase.posting_date})` : ""}</div>
        <div class="ii-kpi-value">${last_purchase ? frappe.format(last_purchase.amount, { fieldtype: "Currency" }) : "-"}</div>
        ${last_purchase ? `<div class="ii-kpi-detail text-muted" style="font-size:11px;margin-top:2px;white-space:nowrap">${flt(last_purchase.qty)} ${__("unidades")} a ${frappe.format(last_purchase.rate, { fieldtype: "Currency" })}</div>` : ""}
      </div>
    `);

    // Store bins data for margin recalculation when price list changes
    this.state.bins = bins;
    this.state.avg_valuation = avg_valuation;
  }

  /**
   * Render stock by warehouse table
   */
  _render_stock_table(bins) {
    this.$stockTable.html(
      this.render_table(
        ["warehouse", "actual_qty", "reserved_qty", "projected_qty", "valuation_rate", "stock_value_est"],
        bins,
        {
          warehouse: __("Almacén"),
          actual_qty: __("Qty"),
          reserved_qty: __("Reservado"),
          projected_qty: __("Proyectado"),
          valuation_rate: __("Costo"),
          stock_value_est: __("Valor Est."),
        }
      )
    );
  }

  /**
   * Render price list controls and chart
   */
  _render_price_section(prices) {
    const priceLists = [...new Set(prices.map((p) => p.price_list).filter(Boolean))];
    const selected = priceLists[0] || null;

    this.$priceControls.html(
      priceLists.length
        ? `<div class="form-inline">
             <label class="mr-2" for="price-list-select">${__("Lista de precios")}</label>
             <select class="form-control form-control-sm" id="price-list-select" data-pl aria-label="${__("Seleccionar lista de precios")}"></select>
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

  /**
   * Render transaction tables (sales and purchases)
   */
  _render_transaction_tables(sales, purchases) {
    this.$salesTable.html(
      this.render_table(
        ["posting_date", "customer", "qty", "rate", "amount", "sales_invoice"],
        sales,
        {
          posting_date: __("Fecha"),
          customer: __("Cliente"),
          qty: __("Qty"),
          rate: __("Precio"),
          amount: __("Total"),
          sales_invoice: __("Documento"),
        }
      )
    );

    this.$purchaseTable.html(
      this.render_table(
        ["posting_date", "supplier", "qty", "rate", "amount", "purchase_invoice"],
        purchases,
        {
          posting_date: __("Fecha"),
          supplier: __("Proveedor"),
          qty: __("Qty"),
          rate: __("Costo"),
          amount: __("Total"),
          purchase_invoice: __("Documento"),
        }
      )
    );
  }

  /**
   * Update price and margin KPIs based on selected price list
   */
  _update_price_kpi(priceRows, price_list) {
    const $priceKpi = $("#ii-kpi-price");
    const $marginKpi = $("#ii-kpi-margin");

    if (!$priceKpi.length) return;

    // Get the most recent price for this price list
    const latestPrice = priceRows.length > 0 ? priceRows[priceRows.length - 1] : null;
    const sell_price = latestPrice ? flt(latestPrice.price_list_rate) : 0;

    // Update price KPI
    $priceKpi.html(`
      <div class="ii-kpi-label">${__("Precio actual")}${price_list ? ` <small class="text-muted">(${frappe.utils.escape_html(price_list)})</small>` : ""}</div>
      <div class="ii-kpi-value">${sell_price > 0 ? frappe.format(sell_price, { fieldtype: "Currency" }) : "-"}</div>
    `);

    // Update margin KPI
    const avg_valuation = this.state.avg_valuation || 0;
    let margin_pct = 0;
    let margin_class = "";
    if (sell_price > 0 && avg_valuation > 0) {
      margin_pct = ((sell_price - avg_valuation) / sell_price) * 100;
      margin_class = margin_pct >= 20 ? "text-success" : margin_pct >= 10 ? "text-warning" : "text-danger";
    }

    $marginKpi.html(`
      <div class="ii-kpi-label">${__("Margen de utilidad")}</div>
      <div class="ii-kpi-value ${margin_class}">${sell_price > 0 ? margin_pct.toFixed(1) + "%" : "-"}</div>
    `);
  }

  render_price_section(prices, price_list) {
    const rows = (prices || []).filter((p) => p.price_list === price_list);

    // Update the price and margin KPIs based on selected price list
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

    // Duplicate single point for visible line chart
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
      this.$priceChart.html(
        `<div class="text-muted">${__("No se encontró frappe.Chart (assets).")}</div>`
      );
    } else {
      this._price_chart = new frappe.Chart(this.$priceChart[0], {
        title: `${__("Histórico")} • ${price_list}`,
        data: { labels, datasets: [{ name: price_list, values }] },
        type: "line",
        height: 260,
        truncateLegends: true,
        lineOptions: {
          regionFill: 0,
          hideDots: 0,
        },
      });
    }

    // Price table (limited to 10 most recent)
    this.$priceTable.html(
      this.render_table(["valid_from", "price_list_rate", "currency", "modified"], rows.slice(-10).reverse(), {
        valid_from: __("Desde"),
        price_list_rate: __("Precio"),
        currency: __("Moneda"),
        modified: __("Modificado"),
      })
    );
  }

  /**
   * Render an HTML table
   * @param {Array} columns - Column keys
   * @param {Array} rows - Data rows
   * @param {Object} labels - Column labels map
   * @returns {string} HTML table string
   */
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

  /**
   * Format a cell value based on column type
   * @param {string} col - Column name
   * @param {*} val - Cell value
   * @returns {string} Formatted HTML string
   */
  format_cell(col, val) {
    if (val === null || val === undefined) return "-";

    const numCols = [
      "actual_qty",
      "reserved_qty",
      "projected_qty",
      "qty",
      "rate",
      "amount",
      "valuation_rate",
      "stock_value_est",
      "price_list_rate",
    ];

    // Document link columns - map column name to DocType
    const docLinkCols = {
      sales_invoice: "Sales Invoice",
      purchase_invoice: "Purchase Invoice",
    };

    if (numCols.includes(col)) {
      const isCurrency = ["rate", "amount", "valuation_rate", "stock_value_est", "price_list_rate"].includes(col);
      return frappe.format(flt(val) || 0, { fieldtype: isCurrency ? "Currency" : "Float" });
    }

    // Render document links as clickable anchors
    if (docLinkCols[col] && val) {
      const doctype = docLinkCols[col];
      const escaped = frappe.utils.escape_html(String(val));
      return `<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(val)}" class="ii-doc-link">${escaped}</a>`;
    }

    return frappe.utils.escape_html(String(val));
  }
};