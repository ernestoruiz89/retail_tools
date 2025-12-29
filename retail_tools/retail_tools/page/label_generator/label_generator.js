/* global frappe, __ */
/* eslint-disable no-undef */

/**
 * Label Generator Page
 *
 * Generate printable barcode labels with:
 * - Item selection with quantity
 * - Multiple label formats
 * - Print support
 */

frappe.pages["label-generator"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Label Generator"),
        single_column: true,
    });

    page.label_generator = new retail_tools.LabelGenerator(page, wrapper);
};

frappe.provide("retail_tools");

retail_tools.LabelGenerator = class LabelGenerator {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$body = $(this.page.body);
        this.items = [];

        this.make_actions();
        this.make_layout();
    }

    make_actions() {
        this.page.set_primary_action(__("Generate Labels"), () =>
            this.generate_labels()
        );

        this.page.add_inner_button(__("Print"), () => this.print_labels());

        this.page.add_inner_button(__("Clear All"), () => this.clear_items());
    }

    make_layout() {
        this.$body.html(`
      <div class="lg-wrapper">
        <div class="lg-controls">
          <div class="lg-add-item">
            <div class="lg-field" id="lg-item-field"></div>
            <div class="lg-field lg-qty-field" id="lg-qty-field"></div>
            <button class="btn btn-primary lg-add-btn">${__("Add")}</button>
          </div>
          <div class="lg-format-row">
            <label>${__("Label Format")}:</label>
            <div class="lg-field" id="lg-format-field"></div>
            <label class="lg-checkbox">
              <input type="checkbox" id="lg-show-price" checked>
              ${__("Show Price")}
            </label>
          </div>
        </div>
        <div class="lg-items-list">
          <div class="lg-items-header">
            <span class="lg-col-item">${__("Item")}</span>
            <span class="lg-col-barcode">${__("Barcode")}</span>
            <span class="lg-col-qty">${__("Qty")}</span>
            <span class="lg-col-actions"></span>
          </div>
          <div class="lg-items-body"></div>
          <div class="lg-items-empty">
            <p class="text-muted">${__("Add items to generate labels")}</p>
          </div>
        </div>
        <div class="lg-preview-container">
          <div class="lg-preview"></div>
        </div>
      </div>
    `);

        // Create Item field
        this.item_field = frappe.ui.form.make_control({
            df: {
                fieldtype: "Link",
                fieldname: "item_code",
                label: __("Item"),
                options: "Item",
                placeholder: __("Select or scan item..."),
            },
            parent: this.$body.find("#lg-item-field"),
            render_input: true,
        });
        this.item_field.refresh();

        // Create Quantity field
        this.qty_field = frappe.ui.form.make_control({
            df: {
                fieldtype: "Int",
                fieldname: "qty",
                label: __("Qty"),
                default: 1,
            },
            parent: this.$body.find("#lg-qty-field"),
            render_input: true,
        });
        this.qty_field.set_value(1);
        this.qty_field.refresh();

        // Create Format field
        this.format_field = frappe.ui.form.make_control({
            df: {
                fieldtype: "Select",
                fieldname: "label_format",
                label: __("Format"),
                options: [
                    { value: "small", label: __("Small (38x25mm) - 4 cols") },
                    { value: "medium", label: __("Medium (50x30mm) - 3 cols") },
                    { value: "large", label: __("Large (70x40mm) - 2 cols") },
                ],
                default: "medium",
            },
            parent: this.$body.find("#lg-format-field"),
            render_input: true,
        });
        this.format_field.set_value("medium");
        this.format_field.refresh();

        // Bind add button
        this.$body.find(".lg-add-btn").on("click", () => this.add_item());

        // Bind enter key on item field
        this.$body.find("#lg-item-field input").on("keypress", (e) => {
            if (e.which === 13) {
                this.add_item();
            }
        });
    }

    add_item() {
        const item_code = this.item_field.get_value();
        const qty = parseInt(this.qty_field.get_value()) || 1;

        if (!item_code) {
            frappe.show_alert({
                message: __("Please select an item"),
                indicator: "orange",
            });
            return;
        }

        // Check if item already in list
        const existing = this.items.find((i) => i.item_code === item_code);
        if (existing) {
            existing.qty += qty;
            this.render_items_list();
            this.item_field.set_value("");
            return;
        }

        // Get item details
        frappe.call({
            method:
                "retail_tools.retail_tools.page.label_generator.label_generator.get_item_for_label",
            args: { item_code },
            callback: (r) => {
                if (r.message && r.message.ok) {
                    this.items.push({
                        ...r.message.item,
                        qty: qty,
                    });
                    this.render_items_list();
                    this.item_field.set_value("");
                    this.qty_field.set_value(1);
                } else {
                    frappe.show_alert({
                        message: r.message?.message || __("Item not found"),
                        indicator: "red",
                    });
                }
            },
        });
    }

    render_items_list() {
        const $body = this.$body.find(".lg-items-body");
        const $empty = this.$body.find(".lg-items-empty");

        if (this.items.length === 0) {
            $body.html("");
            $empty.show();
            return;
        }

        $empty.hide();

        let html = "";
        this.items.forEach((item, idx) => {
            html += `
        <div class="lg-item-row" data-idx="${idx}">
          <span class="lg-col-item">${frappe.utils.escape_html(item.item_name)}</span>
          <span class="lg-col-barcode">${item.barcode || "-"}</span>
          <span class="lg-col-qty">
            <input type="number" class="form-control lg-qty-input" value="${item.qty}" min="1">
          </span>
          <span class="lg-col-actions">
            <button class="btn btn-xs btn-danger lg-remove-btn">
              <i class="fa fa-times"></i>
            </button>
          </span>
        </div>
      `;
        });

        $body.html(html);

        // Bind qty change
        $body.find(".lg-qty-input").on("change", (e) => {
            const idx = $(e.target).closest(".lg-item-row").data("idx");
            this.items[idx].qty = parseInt($(e.target).val()) || 1;
        });

        // Bind remove
        $body.find(".lg-remove-btn").on("click", (e) => {
            const idx = $(e.target).closest(".lg-item-row").data("idx");
            this.items.splice(idx, 1);
            this.render_items_list();
        });
    }

    clear_items() {
        this.items = [];
        this.render_items_list();
        this.$body.find(".lg-preview").html("");
    }

    generate_labels() {
        if (this.items.length === 0) {
            frappe.show_alert({
                message: __("Please add items first"),
                indicator: "orange",
            });
            return;
        }

        const label_format = this.format_field.get_value() || "medium";

        frappe.call({
            method:
                "retail_tools.retail_tools.page.label_generator.label_generator.generate_labels_html",
            args: {
                items: JSON.stringify(this.items),
                label_format: label_format,
            },
            freeze: true,
            freeze_message: __("Generating labels..."),
            callback: (r) => {
                if (r.message && r.message.ok) {
                    this.$body.find(".lg-preview").html(r.message.html);
                    this.init_barcodes();
                    frappe.show_alert({
                        message: __("{0} labels generated", [r.message.count]),
                        indicator: "green",
                    });
                } else {
                    frappe.show_alert({
                        message: r.message?.message || __("Error generating labels"),
                        indicator: "red",
                    });
                }
            },
        });
    }

    init_barcodes() {
        if (typeof JsBarcode === "undefined") {
            const script = document.createElement("script");
            script.src =
                "https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js";
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
                        width: 1.2,
                        height: 30,
                        displayValue: true,
                        fontSize: 10,
                        margin: 2,
                    });
                } catch (e) {
                    console.log("Barcode error:", e);
                }
            }
        });
    }

    print_labels() {
        const $preview = this.$body.find(".lg-preview");
        if (!$preview.html()) {
            frappe.show_alert({
                message: __("Please generate labels first"),
                indicator: "orange",
            });
            return;
        }

        const printContent = $preview.html();
        const printWindow = window.open("", "_blank");
        printWindow.document.write(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>${__("Barcode Labels")}</title>
        <style>
          body { margin: 0; padding: 10px; }
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
};
