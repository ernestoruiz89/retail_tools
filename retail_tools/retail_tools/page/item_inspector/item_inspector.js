/* global frappe */

frappe.pages["item-inspector"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Consulta de Producto"),
    single_column: true,
  });

  wrapper.item_inspector = new retail_tools.ItemInspector(page, wrapper);
};

frappe.provide("retail_tools");

retail_tools.ItemInspector = class ItemInspector {
  constructor(page, wrapper) {
    this.page = page;
    this.wrapper = wrapper;
    this.state = { item_code: null, snapshot: null };

    this.make_filters();
    this.make_layout();
	
	this._onResize = frappe.utils.debounce(() => {
	  // si ya hay snapshot, re-render solo el chart
	  if (!this.state.snapshot) return;

	  const prices = this.state.snapshot.price_history || [];
	  const pls = [...new Set(prices.map(p => p.price_list).filter(Boolean))];
	  const current = this.$priceControls?.find("[data-pl]")?.val() || pls[0];

	  if (current) this.render_price_section(prices, current);
	}, 250);

	$(window).on("resize", this._onResize);
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
      <div class="item-inspector">
        <div class="ii-grid">
          <div class="ii-card ii-overview">
            <div class="ii-header">
              <div class="ii-image"></div>
              <div class="ii-main">
                <div class="ii-title"></div>
                <div class="ii-meta"></div>
                <div class="ii-tags"></div>
                <div class="ii-actions mt-2"></div>
              </div>
            </div>
            <div class="ii-kpis mt-3"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title">${__("Existencia por almacén")}</div>
            <div class="ii-table ii-stock-table"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title">${__("Histórico de precios por lista")}</div>
            <div class="ii-price-controls mb-2"></div>
            <div class="ii-chart" id="ii-price-chart"></div>
            <div class="ii-table ii-price-table mt-3"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title">${__("Últimas ventas")}</div>
            <div class="ii-table ii-sales-table"></div>
          </div>

          <div class="ii-card">
            <div class="ii-card-title">${__("Últimas compras")}</div>
            <div class="ii-table ii-purchase-table"></div>
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
    // Frappe Scanner API (Html5-QRCode) :contentReference[oaicite:2]{index=2}
    new frappe.ui.Scanner({
      dialog: true,
      multiple: false,
      on_scan: (data) => {
        const code = (data && data.decodedText) ? data.decodedText : "";
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

  resolve_barcode(barcode) {
    frappe.call({
      method: "retail_tools.retail_tools.page.item_inspector.item_inspector.resolve_item_from_barcode",
      args: { barcode },
      callback: (r) => {
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
          const d = new frappe.ui.Dialog({
            title: __("Selecciona un producto"),
            fields: [
              {
                fieldtype: "Select",
                fieldname: "item_code",
                label: __("Producto"),
                options: res.matches.map(x => `${x.item_code} - ${x.item_name || ""}`),
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
      },
    });
  }

  load_snapshot(item_code) {
    this.state.item_code = item_code;

    frappe.call({
      method: "retail_tools.retail_tools.page.item_inspector.item_inspector.get_item_snapshot",
      args: { item_code },
      freeze: true,
      callback: (r) => {
        const res = r.message;
        if (!res || !res.ok) return;

        this.state.snapshot = res;
        this.render(res);
      },
    });
  }

  render(res) {
    const item = res.item || {};
    const bins = res.bins || [];
    const barcodes = res.barcodes || [];
    const prices = res.price_history || [];
    const sales = res.recent_sales || [];
    const purchases = res.recent_purchases || [];

    // Header
    const img = item.image
      ? `<img src="${encodeURI(item.image)}" style="width:72px;height:72px;object-fit:cover;border-radius:12px;" />`
      : `<div class="ii-img-fallback">${(item.item_name || item.item_code || "?").slice(0,1)}</div>`;

    this.$image.html(img);
    this.$title.html(`<div class="h4 mb-1">${frappe.utils.escape_html(item.item_name || "")}</div>
                      <div class="text-muted">${frappe.utils.escape_html(item.item_code || "")}</div>`);

    this.$meta.html(`
      <div class="text-muted">
        ${__("Grupo")}: <b>${frappe.utils.escape_html(item.item_group || "-")}</b>
        &nbsp;•&nbsp;
        ${__("Marca")}: <b>${frappe.utils.escape_html(item.brand || "-")}</b>
        &nbsp;•&nbsp;
        ${__("UoM")}: <b>${frappe.utils.escape_html(item.stock_uom || "-")}</b>
      </div>
      <div class="mt-1">${frappe.utils.escape_html((item.description || "").slice(0, 160))}</div>
    `);

    const tags = [];
    if (barcodes.length) tags.push(`${__("Barcodes")}: ${barcodes.map(frappe.utils.escape_html).join(", ")}`);
    if (item.disabled) tags.push(__("DESHABILITADO"));
    if (!item.is_stock_item) tags.push(__("No es stock item"));
    this.$tags.html(tags.map(t => `<span class="badge badge-light mr-1">${t}</span>`).join(""));

    this.$actions.html(`
	  <div class="ii-actions-grid">
		<button class="btn btn-sm btn-primary" data-open-item>${__("Abrir Item")}</button>
		<button class="btn btn-sm btn-default" data-open-stock>${__("Stock Balance")}</button>
	  </div>
	`);

	this.$actions.find("[data-open-item]").on("click", () => frappe.set_route("Form", "Item", item.item_code));
	this.$actions.find("[data-open-stock]").on("click", () => {
	  const item_code = this.state?.item_code || this.item_field.get_value();
	  frappe.set_route("query-report", "Stock Balance", { item_code });
	});

    // KPIs
    const total_qty = bins.reduce((acc, b) => acc + (flt(b.actual_qty) || 0), 0);
    const total_value = bins.reduce((acc, b) => acc + (flt(b.stock_value_est) || 0), 0);

    const last_sale = sales[0];
    const last_purchase = purchases[0];

    this.$kpis.html(`
      <div class="ii-kpi"><div class="ii-kpi-label">${__("Existencia total")}</div><div class="ii-kpi-value">${frappe.format(total_qty, {fieldtype:"Float"})}</div></div>
      <div class="ii-kpi"><div class="ii-kpi-label">${__("Valor estimado (stock)")}</div><div class="ii-kpi-value">${frappe.format(total_value, {fieldtype:"Currency"})}</div></div>
      <div class="ii-kpi"><div class="ii-kpi-label">${__("Última venta")}</div><div class="ii-kpi-value">${last_sale ? `${last_sale.posting_date} • ${frappe.format(last_sale.rate, {fieldtype:"Currency"})}` : "-"}</div></div>
      <div class="ii-kpi"><div class="ii-kpi-label">${__("Última compra")}</div><div class="ii-kpi-value">${last_purchase ? `${last_purchase.posting_date} • ${frappe.format(last_purchase.rate, {fieldtype:"Currency"})}` : "-"}</div></div>
    `);

    // Stock table
    this.$stockTable.html(this.render_table(
      ["warehouse", "actual_qty", "reserved_qty", "projected_qty", "valuation_rate", "stock_value_est"],
      bins,
      {
        warehouse: __("Almacén"),
        actual_qty: __("Qty"),
        reserved_qty: __("Reservado"),
        projected_qty: __("Proyectado"),
        valuation_rate: __("Costo (Valuation)"),
        stock_value_est: __("Valor Est."),
      }
    ));

    // Price controls + chart
    const priceLists = [...new Set(prices.map(p => p.price_list).filter(Boolean))];
    const selected = priceLists[0] || null;

    this.$priceControls.html(priceLists.length
      ? `<div class="form-inline">
           <label class="mr-2">${__("Lista de precios")}</label>
           <select class="form-control form-control-sm" data-pl></select>
         </div>`
      : `<div class="text-muted">${__("No hay Item Price para este producto.")}</div>`
    );

    if (priceLists.length) {
      const $pl = this.$priceControls.find("[data-pl]");
      priceLists.forEach(pl => $pl.append(`<option value="${frappe.utils.escape_html(pl)}">${frappe.utils.escape_html(pl)}</option>`));
      $pl.val(selected);
      $pl.on("change", () => this.render_price_section(prices, $pl.val()));
      this.render_price_section(prices, selected);
    } else {
      this.$priceChart.empty();
      this.$priceTable.empty();
    }

    // Sales + Purchases tables
    this.$salesTable.html(this.render_table(
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
    ));

    this.$purchaseTable.html(this.render_table(
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
    ));
  }

  render_price_section(prices, price_list) {
	  const rows = (prices || []).filter(p => p.price_list === price_list);

	  const toFloat = (x) => {
		if (x === null || x === undefined) return 0;
		const s = String(x).replace(/,/g, "").trim();
		const n = Number(s);
		return Number.isFinite(n) ? n : 0;
	  };

	  const pickDate = (r) => (r.valid_from || r.creation || r.modified || "");
	  let labels = rows.map(r => String(pickDate(r)).slice(0, 10)).map(x => x || __("Sin fecha"));
	  let values = rows.map(r => toFloat(r.price_list_rate));

	  // Si solo hay 1 punto, duplica para que el "line chart" sea visible
	  if (labels.length === 1) {
		const d0 = labels[0];
		let d1 = d0;

		// intenta sumar 1 día si es fecha válida YYYY-MM-DD
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
		// recrear chart
		this._price_chart = new frappe.Chart(this.$priceChart[0], {
		  title: `${__("Histórico")} • ${price_list}`,
		  data: { labels, datasets: [{ name: price_list, values }] },
		  type: "line",
		  height: 260,
		  // trucos para que se vea mejor en móvil
		  truncateLegends: true,
		  lineOptions: {
			regionFill: 0,
			hideDots: 0,
		  },
		});
	  }

	  // Tabla
	  this.$priceTable.html(this.render_table(
		["valid_from", "price_list_rate", "currency", "modified"],
		rows,
		{
		  valid_from: __("Desde"),
		  price_list_rate: __("Precio"),
		  currency: __("Moneda"),
		  modified: __("Modificado"),
		}
	  ));
	}

  render_table(columns, rows, labels) {
    rows = rows || [];
    const ths = columns.map(c => `<th>${frappe.utils.escape_html(labels[c] || c)}</th>`).join("");
    const trs = rows.map(r => {
      const tds = columns.map(c => `<td>${this.format_cell(c, r[c])}</td>`).join("");
      return `<tr>${tds}</tr>`;
    }).join("");

    return `
      <div class="table-responsive">
        <table class="table table-bordered table-sm">
          <thead><tr>${ths}</tr></thead>
          <tbody>${trs || `<tr><td colspan="${columns.length}" class="text-muted">${__("Sin datos")}</td></tr>`}</tbody>
        </table>
      </div>
    `;
  }

  format_cell(col, val) {
    if (val === null || val === undefined) return "-";

    const numCols = ["actual_qty", "reserved_qty", "projected_qty", "qty", "rate", "amount", "valuation_rate", "stock_value_est", "price_list_rate"];
    if (numCols.includes(col)) {
      const isCurrency = ["rate", "amount", "valuation_rate", "stock_value_est", "price_list_rate"].includes(col);
      return frappe.format(flt(val) || 0, { fieldtype: isCurrency ? "Currency" : "Float" });
    }
    return frappe.utils.escape_html(String(val));
  }
};