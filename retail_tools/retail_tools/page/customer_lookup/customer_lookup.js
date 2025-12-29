/* global frappe, __ */
/* eslint-disable no-undef */

/**
 * Customer Lookup Page
 *
 * A dashboard-style page for quickly looking up customer information including:
 * - Basic customer info
 * - Outstanding balance
 * - Purchase history
 * - Loyalty points (if available)
 *
 * Features:
 * - Search by name, code, phone, or email
 * - Responsive mobile-first design
 */

frappe.pages["customer-lookup"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Customer Lookup"),
        single_column: true,
    });

    page.customer_lookup = new retail_tools.CustomerLookup(page, wrapper);
};

frappe.pages["customer-lookup"].on_page_hide = function (wrapper) {
    if (wrapper.page.customer_lookup) {
        wrapper.page.customer_lookup.destroy();
    }
};

frappe.provide("retail_tools");

retail_tools.CustomerLookup = class CustomerLookup {
    /**
     * Initialize the Customer Lookup component
     * @param {Object} page - Frappe page object
     * @param {HTMLElement} wrapper - Page wrapper element
     */
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$container = $(wrapper).find(".layout-main-section");
        this.current_customer = null;

        this.make_filters();
        this.make_layout();
    }

    /**
     * Clean up event handlers and resources
     */
    destroy() {
        if (this.$search_input) {
            this.$search_input.off();
        }
    }

    make_filters() {
        // We'll bind events after layout is created
    }

    make_layout() {
        this.$container.html(`
      <div class="cl-wrapper">
        <div class="cl-search-container">
          <div class="cl-search-box">
            <i class="fa fa-search cl-search-icon"></i>
            <input type="text" class="cl-search-input" placeholder="${__("Enter name, code, phone, or email...")}">
          </div>
        </div>
        <div class="cl-empty-state">
          <div class="cl-empty-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
              <circle cx="12" cy="7" r="4"></circle>
            </svg>
          </div>
          <h3>${__("Search for a Customer")}</h3>
          <p class="text-muted">${__("Enter a name, code, phone number, or email above")}</p>
        </div>
        <div class="cl-content" style="display: none;">
          <div class="cl-header"></div>
          <div class="cl-kpis"></div>
          <div class="cl-sections">
            <div class="cl-invoices"></div>
            <div class="cl-loyalty"></div>
          </div>
        </div>
      </div>
    `);

        // Bind search events
        this.$search_input = this.$container.find(".cl-search-input");

        this.$search_input.on("keypress", (e) => {
            if (e.which === 13) {
                const value = this.$search_input.val();
                if (value && value.length >= 2) {
                    this.search_customer(value);
                }
            }
        });

        // Also search on blur/change after typing
        let searchTimeout;
        this.$search_input.on("input", (e) => {
            clearTimeout(searchTimeout);
            const value = this.$search_input.val();
            if (value && value.length >= 3) {
                searchTimeout = setTimeout(() => {
                    this.search_customer(value);
                }, 500);
            }
        });
    }

    search_customer(query) {
        frappe.call({
            method:
                "retail_tools.retail_tools.page.customer_lookup.customer_lookup.search_customer",
            args: { query },
            callback: (r) => {
                if (r.message && r.message.ok) {
                    const customers = r.message.customers;
                    if (customers.length === 1) {
                        this.load_snapshot(customers[0].name);
                    } else {
                        this._show_customer_selector(customers);
                    }
                } else {
                    frappe.show_alert({
                        message: r.message?.message || __("No customers found"),
                        indicator: "orange",
                    });
                }
            },
            error: (err) => {
                console.error("Search error:", err);
                frappe.show_alert({
                    message: __("Error searching customers"),
                    indicator: "red",
                });
            },
        });
    }

    /**
     * Show dialog to select from multiple matching customers
     * @param {Array} customers - List of matching customers
     */
    _show_customer_selector(customers) {
        const options = customers.map(
            (c) => `${c.name} - ${c.customer_name} (${c.mobile_no || c.email_id || ""})`
        );

        const d = new frappe.ui.Dialog({
            title: __("Select Customer"),
            fields: [
                {
                    fieldtype: "Select",
                    fieldname: "customer",
                    label: __("Customer"),
                    options: options.join("\n"),
                    reqd: 1,
                },
            ],
            primary_action_label: __("Select"),
            primary_action: () => {
                const selected = d.get_value("customer");
                const customer_name = selected.split(" - ")[0];
                d.hide();
                this.load_snapshot(customer_name);
            },
        });
        d.show();
    }

    load_snapshot(customer) {
        frappe.call({
            method:
                "retail_tools.retail_tools.page.customer_lookup.customer_lookup.get_customer_snapshot",
            args: { customer },
            callback: (r) => {
                if (r.message && r.message.ok) {
                    this.current_customer = customer;
                    this.render(r.message);
                } else {
                    frappe.show_alert({
                        message: r.message?.message || __("Error loading customer"),
                        indicator: "red",
                    });
                }
            },
            error: (err) => {
                console.error("Snapshot error:", err);
                frappe.show_alert({
                    message: __("Error loading customer data"),
                    indicator: "red",
                });
            },
        });
    }

    render(data) {
        this.$container.find(".cl-empty-state").hide();
        this.$container.find(".cl-content").show();

        this._render_header(data.customer);
        this._render_kpis(data.outstanding, data.lifetime_value, data.last_purchase);
        this._render_invoices(data.recent_invoices);
        this._render_loyalty(data.loyalty);
    }

    _render_header(customer) {
        const address = customer.address_display || "";
        const contact = customer.mobile_no || customer.email_id || "";

        this.$container.find(".cl-header").html(`
      <div class="cl-customer-card">
        <div class="cl-customer-avatar">
          ${customer.customer_name.charAt(0).toUpperCase()}
        </div>
        <div class="cl-customer-info">
          <h2 class="cl-customer-name">
            <a href="/app/customer/${encodeURIComponent(customer.name)}">${frappe.utils.escape_html(customer.customer_name)}</a>
          </h2>
          <div class="cl-customer-meta">
            <span class="cl-badge">${frappe.utils.escape_html(customer.customer_group || "")}</span>
            <span class="cl-badge">${frappe.utils.escape_html(customer.territory || "")}</span>
          </div>
          <div class="cl-customer-contact">
            ${contact ? `<span><i class="fa fa-phone"></i> ${frappe.utils.escape_html(contact)}</span>` : ""}
            ${address ? `<span><i class="fa fa-map-marker"></i> ${frappe.utils.escape_html(address)}</span>` : ""}
          </div>
        </div>
      </div>
    `);
    }

    _render_kpis(outstanding, lifetime, lastPurchase) {
        const formatCurrency = (val, currency) => {
            return frappe.format(val, { fieldtype: "Currency", currency: currency });
        };

        const formatDate = (val) => {
            return val ? frappe.format(val, { fieldtype: "Date" }) : __("Never");
        };

        const outstandingClass = outstanding.amount > 0 ? "cl-kpi-warning" : "cl-kpi-success";

        this.$container.find(".cl-kpis").html(`
      <div class="cl-kpi-grid">
        <div class="cl-kpi ${outstandingClass}">
          <div class="cl-kpi-value">${formatCurrency(outstanding.amount, outstanding.currency)}</div>
          <div class="cl-kpi-label">${__("Outstanding Balance")}</div>
        </div>
        <div class="cl-kpi">
          <div class="cl-kpi-value">${formatCurrency(lifetime.amount, lifetime.currency)}</div>
          <div class="cl-kpi-label">${__("Lifetime Purchases")} (${lifetime.count})</div>
        </div>
        <div class="cl-kpi">
          <div class="cl-kpi-value">${formatDate(lastPurchase)}</div>
          <div class="cl-kpi-label">${__("Last Purchase")}</div>
        </div>
      </div>
    `);
    }

    _render_invoices(invoices) {
        if (!invoices || invoices.length === 0) {
            this.$container.find(".cl-invoices").html(`
        <div class="cl-section">
          <h4 class="cl-section-title">${__("Recent Purchases")}</h4>
          <p class="text-muted">${__("No purchase history found")}</p>
        </div>
      `);
            return;
        }

        const rows = invoices.map((inv) => {
            const statusClass = inv.status === "Paid" ? "success" : inv.status === "Overdue" ? "danger" : "warning";
            const returnBadge = inv.is_return ? `<span class="cl-return-badge">${__("Return")}</span>` : "";

            return `
        <tr>
          <td>
            <a href="/app/sales-invoice/${encodeURIComponent(inv.name)}">${frappe.utils.escape_html(inv.name)}</a>
            ${returnBadge}
          </td>
          <td>${frappe.format(inv.posting_date, { fieldtype: "Date" })}</td>
          <td class="text-right">${frappe.format(inv.grand_total, { fieldtype: "Currency", currency: inv.currency })}</td>
          <td><span class="indicator-pill ${statusClass}">${inv.status}</span></td>
        </tr>
      `;
        }).join("");

        this.$container.find(".cl-invoices").html(`
      <div class="cl-section">
        <h4 class="cl-section-title">${__("Recent Purchases")}</h4>
        <div class="cl-table-wrapper">
          <table class="cl-table">
            <thead>
              <tr>
                <th>${__("Invoice")}</th>
                <th>${__("Date")}</th>
                <th class="text-right">${__("Amount")}</th>
                <th>${__("Status")}</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `);
    }

    _render_loyalty(loyalty) {
        if (!loyalty) {
            this.$container.find(".cl-loyalty").html("");
            return;
        }

        const expiringWarning = loyalty.expiring_soon > 0
            ? `<div class="cl-loyalty-warning"><i class="fa fa-exclamation-triangle"></i> ${loyalty.expiring_soon} ${__("points expiring in 30 days")}</div>`
            : "";

        this.$container.find(".cl-loyalty").html(`
      <div class="cl-section cl-loyalty-section">
        <h4 class="cl-section-title">${__("Loyalty Points")}</h4>
        <div class="cl-loyalty-card">
          <div class="cl-loyalty-program">${frappe.utils.escape_html(loyalty.program)}</div>
          <div class="cl-loyalty-points">${loyalty.total_points.toLocaleString()}</div>
          <div class="cl-loyalty-label">${__("Available Points")}</div>
          ${expiringWarning}
        </div>
      </div>
    `);
    }
};
