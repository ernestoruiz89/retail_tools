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
          <div class="lg-bulk-row">
            <div class="lg-field" id="lg-warehouse-field"></div>
            <button class="btn btn-default lg-load-stock-btn">
              <i class="fa fa-download"></i> ${__("Load Items with Stock")}
            </button>
          </div>
          <div class="lg-bulk-row">
            <div class="lg-field lg-field-narrow" id="lg-receipt-doctype-field"></div>
            <div class="lg-field" id="lg-receipt-document-field"></div>
            <button class="btn btn-default lg-load-receipt-btn">
              <i class="fa fa-file-text-o"></i> ${__("Load from Document")}
            </button>
          </div>
          <div class="lg-format-row">
            <label>${__("Label Format")}:</label>
            <div class="lg-field" id="lg-format-field"></div>
            <div class="lg-field" id="lg-price-list-field"></div>
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

        // Create Price List field
        this.price_list_field = frappe.ui.form.make_control({
            df: {
                fieldtype: "Link",
                fieldname: "price_list",
                label: __("Price List"),
                options: "Price List",
                placeholder: __("Default"),
                get_query: () => {
                    return { filters: { selling: 1 } };
                },
            },
            parent: this.$body.find("#lg-price-list-field"),
            render_input: true,
        });
        this.price_list_field.refresh();

        // Create Warehouse field
        this.warehouse_field = frappe.ui.form.make_control({
            df: {
                fieldtype: "Link",
                fieldname: "warehouse",
                label: __("Warehouse"),
                options: "Warehouse",
                placeholder: __("All warehouses"),
            },
            parent: this.$body.find("#lg-warehouse-field"),
            render_input: true,
        });
        this.warehouse_field.refresh();

        // Create Receipt Document Type field
        this.receipt_doctype_field = frappe.ui.form.make_control({
            df: {
                fieldtype: "Select",
                fieldname: "receipt_doctype",
                label: __("Document Type"),
                options: [
                    { value: "Purchase Invoice", label: __("Purchase Invoice") },
                    { value: "Purchase Receipt", label: __("Purchase Receipt") },
                ],
                default: "Purchase Invoice",
            },
            parent: this.$body.find("#lg-receipt-doctype-field"),
            render_input: true,
        });
        this.receipt_doctype_field.set_value("Purchase Invoice");
        this.receipt_doctype_field.refresh();

        // Create Receipt Document field (Dynamic Link)
        this.receipt_document_field = frappe.ui.form.make_control({
            df: {
                fieldtype: "Link",
                fieldname: "receipt_document",
                label: __("Document"),
                options: "Purchase Invoice",
                placeholder: __("Select document..."),
            },
            parent: this.$body.find("#lg-receipt-document-field"),
            render_input: true,
        });
        this.receipt_document_field.refresh();

        // Bind doctype change to update document link options
        this.receipt_doctype_field.$input.on("change", () => {
            const doctype = this.receipt_doctype_field.get_value();
            this.receipt_document_field.df.options = doctype;
            this.receipt_document_field.set_value("");
            this.receipt_document_field.refresh();
        });

        // Bind add button
        this.$body.find(".lg-add-btn").on("click", () => this.add_item());

        // Bind load stock button
        this.$body.find(".lg-load-stock-btn").on("click", () => this.load_items_with_stock());

        // Bind load from receipt document button
        this.$body.find(".lg-load-receipt-btn").on("click", () => this.load_items_from_receipt_document());

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

    load_items_with_stock() {
        const warehouse = this.warehouse_field.get_value();

        frappe.call({
            method:
                "retail_tools.retail_tools.page.label_generator.label_generator.get_items_with_stock",
            args: { warehouse: warehouse || "" },
            freeze: true,
            freeze_message: __("Loading items with stock..."),
            callback: (r) => {
                if (r.message && r.message.ok) {
                    // Merge with existing items
                    r.message.items.forEach((item) => {
                        const existing = this.items.find(
                            (i) => i.item_code === item.item_code
                        );
                        if (existing) {
                            existing.qty += item.qty;
                        } else {
                            this.items.push(item);
                        }
                    });
                    this.render_items_list();
                    frappe.show_alert({
                        message: __("{0} items loaded", [r.message.count]),
                        indicator: "green",
                    });
                } else {
                    frappe.show_alert({
                        message: r.message?.message || __("No items found"),
                        indicator: "orange",
                    });
                }
            },
        });
    }

    load_items_from_receipt_document() {
        const doctype = this.receipt_doctype_field.get_value();
        const docname = this.receipt_document_field.get_value();

        if (!docname) {
            frappe.show_alert({
                message: __("Please select a document"),
                indicator: "orange",
            });
            return;
        }

        frappe.call({
            method:
                "retail_tools.retail_tools.page.label_generator.label_generator.get_items_from_receipt_document",
            args: { doctype: doctype, docname: docname },
            freeze: true,
            freeze_message: __("Loading items from document..."),
            callback: (r) => {
                if (r.message && r.message.ok) {
                    // Merge with existing items
                    r.message.items.forEach((item) => {
                        const existing = this.items.find(
                            (i) => i.item_code === item.item_code
                        );
                        if (existing) {
                            existing.qty += item.qty;
                        } else {
                            this.items.push(item);
                        }
                    });
                    this.render_items_list();
                    frappe.show_alert({
                        message: __("{0} items loaded", [r.message.count]),
                        indicator: "green",
                    });
                } else {
                    frappe.show_alert({
                        message: r.message?.message || __("No items found"),
                        indicator: "orange",
                    });
                }
            },
        });
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
        const show_price = this.$body.find("#lg-show-price").is(":checked") ? 1 : 0;
        const price_list = this.price_list_field.get_value() || "";

        frappe.call({
            method:
                "retail_tools.retail_tools.page.label_generator.label_generator.generate_labels_html",
            args: {
                items: JSON.stringify(this.items),
                label_format: label_format,
                show_price: show_price,
                price_list: price_list,
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
        const format = this.format_field.get_value();
        let height = 30;
        if (format === "large") height = 55;
        if (format === "small") height = 25;

        this.$body.find(".barcode-svg").each(function () {
            const barcode = $(this).data("barcode");
            if (barcode) {
                try {
                    JsBarcode(this, String(barcode), {
                        format: "CODE128",
                        width: 1.2,
                        height: height,
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
