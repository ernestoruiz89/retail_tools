/* global frappe, __ */
/* eslint-disable no-undef */

/**
 * Catalog Generator Page
 *
 * Generate printable product catalogs with:
 * - Item filtering by group, brand, warehouse
 * - Price list integration
 * - Configurable layout (2-4 columns)
 * - PDF export
 */

frappe.pages["catalog-generator"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Catalog Generator"),
    single_column: true,
  });

  page.catalog_generator = new retail_tools.CatalogGenerator(page, wrapper);
};

frappe.provide("retail_tools");

retail_tools.CatalogGenerator = class CatalogGenerator {
  constructor(page, wrapper) {
    this.page = page;
    this.wrapper = wrapper;
    this.$body = $(this.page.body);

    this.make_filters();
    this.make_layout();
  }

  make_filters() {
    // Filters will be created in make_layout

    // Generate button
    this.page.set_primary_action(__("Generate Preview"), () =>
      this.generate_preview()
    );

    // Print button
    this.page.add_inner_button(__("Print"), () => this.print_catalog());
  }

  make_layout() {
    this.$body.html(`
      <div class="cg-wrapper">
        <div class="cg-filters">
          <div class="cg-filter-row">
            <div class="cg-filter-field" id="cg-item-group"></div>
            <div class="cg-filter-field" id="cg-brand"></div>
            <div class="cg-filter-field" id="cg-warehouse"></div>
            <div class="cg-filter-field" id="cg-price-list"></div>
          </div>
        </div>
        <div class="cg-options">
          <div class="cg-option-group">
            <label>${__("Columns")}</label>
            <div class="btn-group cg-columns-selector">
              <button class="btn btn-default" data-columns="2">2</button>
              <button class="btn btn-default active" data-columns="3">3</button>
              <button class="btn btn-default" data-columns="4">4</button>
            </div>
          </div>
          <div class="cg-option-group">
            <label class="cg-checkbox">
              <input type="checkbox" id="cg-group-by-item-group" checked>
              ${__("Group by Item Group")}
            </label>
          </div>
          <div class="cg-option-group">
            <label class="cg-checkbox">
              <input type="checkbox" id="cg-show-barcode" checked>
              ${__("Show Barcode")}
            </label>
            <label class="cg-checkbox">
              <input type="checkbox" id="cg-show-barcode-image">
              ${__("Show Barcode Image")}
            </label>
            <label class="cg-checkbox">
              <input type="checkbox" id="cg-show-price" checked>
              ${__("Show Price")}
            </label>
            <label class="cg-checkbox">
              <input type="checkbox" id="cg-show-desc">
              ${__("Show Description")}
            </label>
          </div>
        </div>
        <div class="cg-preview-container">
          <div class="cg-empty-state">
            <div class="cg-empty-icon">
              <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
              </svg>
            </div>
            <h3>${__("Generate a Catalog")}</h3>
            <p class="text-muted">${__("Select filters and click Generate Preview")}</p>
          </div>
          <div class="cg-preview" style="display: none;"></div>
        </div>
      </div>
    `);

    // Create filter fields
    this.item_group_field = frappe.ui.form.make_control({
      df: {
        fieldtype: "Link",
        fieldname: "item_group",
        label: __("Item Group"),
        options: "Item Group",
      },
      parent: this.$body.find("#cg-item-group"),
      render_input: true,
    });
    this.item_group_field.refresh();

    this.brand_field = frappe.ui.form.make_control({
      df: {
        fieldtype: "Link",
        fieldname: "brand",
        label: __("Brand"),
        options: "Brand",
      },
      parent: this.$body.find("#cg-brand"),
      render_input: true,
    });
    this.brand_field.refresh();

    this.warehouse_field = frappe.ui.form.make_control({
      df: {
        fieldtype: "Link",
        fieldname: "warehouse",
        label: __("Warehouse"),
        options: "Warehouse",
      },
      parent: this.$body.find("#cg-warehouse"),
      render_input: true,
    });
    this.warehouse_field.refresh();

    this.price_list_field = frappe.ui.form.make_control({
      df: {
        fieldtype: "Link",
        fieldname: "price_list",
        label: __("Price List"),
        options: "Price List",
        get_query: () => ({ filters: { selling: 1 } }),
      },
      parent: this.$body.find("#cg-price-list"),
      render_input: true,
    });
    this.price_list_field.refresh();

    // Bind column selector
    this.$body.find(".cg-columns-selector .btn").on("click", (e) => {
      this.$body.find(".cg-columns-selector .btn").removeClass("active");
      $(e.target).addClass("active");
    });
  }

  get_options() {
    return {
      item_group: this.item_group_field.get_value(),
      brand: this.brand_field.get_value(),
      warehouse: this.warehouse_field.get_value(),
      price_list: this.price_list_field.get_value(),
      columns:
        this.$body.find(".cg-columns-selector .btn.active").data("columns") ||
        3,
      group_by_item_group: this.$body.find("#cg-group-by-item-group").is(":checked") ? 1 : 0,
      show_barcode: this.$body.find("#cg-show-barcode").is(":checked") ? 1 : 0,
      show_barcode_image: this.$body.find("#cg-show-barcode-image").is(":checked") ? 1 : 0,
      show_price: this.$body.find("#cg-show-price").is(":checked") ? 1 : 0,
      show_description: this.$body.find("#cg-show-desc").is(":checked") ? 1 : 0,
    };
  }

  generate_preview() {
    const options = this.get_options();

    frappe.call({
      method:
        "retail_tools.retail_tools.page.catalog_generator.catalog_generator.generate_catalog_html",
      args: options,
      freeze: true,
      freeze_message: __("Generating catalog..."),
      callback: (r) => {
        if (r.message && r.message.ok) {
          this.$body.find(".cg-empty-state").hide();
          this.$body.find(".cg-preview").html(r.message.html).show();

          // Initialize barcodes if show_barcode_image is enabled
          if (options.show_barcode_image) {
            this.init_barcodes();
          }

          frappe.show_alert({
            message: __("{0} products in catalog", [r.message.count]),
            indicator: "green",
          });
        } else {
          frappe.show_alert({
            message: r.message?.message || __("No items found"),
            indicator: "orange",
          });
        }
      },
      error: (err) => {
        console.error("Catalog error:", err);
        frappe.show_alert({
          message: __("Error generating catalog"),
          indicator: "red",
        });
      },
    });
  }

  print_catalog() {
    const $preview = this.$body.find(".cg-preview");
    if (!$preview.html()) {
      frappe.show_alert({
        message: __("Please generate a preview first"),
        indicator: "orange",
      });
      return;
    }

    // Open print dialog
    const printContent = $preview.html();
    const printWindow = window.open("", "_blank");
    printWindow.document.write(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>${__("Product Catalog")}</title>
        <style>
          body { margin: 0; padding: 20px; }
          @media print {
            body { padding: 0; }
          }
        </style>
      </head>
      <body>
        ${printContent}
        <script>window.print(); window.close();</script>
      </body>
      </html>
    `);
    printWindow.document.close();
  }

  init_barcodes() {
    // Load JsBarcode library if not already loaded
    if (typeof JsBarcode === "undefined") {
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js";
      script.onload = () => this.render_barcodes();
      document.head.appendChild(script);
    } else {
      this.render_barcodes();
    }
  }

  render_barcodes() {
    this.$body.find(".barcode-svg").each(function () {
      const barcode = $(this).data("barcode");
      if (barcode) {
        try {
          JsBarcode(this, String(barcode), {
            format: "CODE128",
            width: 1.5,
            height: 40,
            displayValue: true,
            fontSize: 10,
            margin: 5,
          });
        } catch (e) {
          console.log("Barcode error:", e);
        }
      }
    });
  }
};
