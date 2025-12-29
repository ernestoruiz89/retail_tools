/**
 * Retail Tools - Main JS Bundle
 * 
 * Provides utilities and shared functionality for Retail Tools pages
 */

frappe.provide("retail_tools");

// Utility to format currency with locale support
retail_tools.format_currency = function (value, currency) {
    return frappe.format(value, { fieldtype: "Currency", currency: currency });
};

// Utility to show loading indicator on element
retail_tools.show_loading = function ($element, message) {
    message = message || __("Loading...");
    $element.html(`<div class="text-center text-muted py-4">
        <i class="fa fa-spinner fa-spin fa-2x mb-2"></i>
        <div>${message}</div>
    </div>`);
};

// Utility to show empty state
retail_tools.show_empty = function ($element, message, icon) {
    icon = icon || "fa-inbox";
    message = message || __("No data");
    $element.html(`<div class="text-center text-muted py-4">
        <i class="fa ${icon} fa-2x mb-2"></i>
        <div>${message}</div>
    </div>`);
};

// Initialize when frappe is ready
$(document).ready(function () {
    console.log("Retail Tools loaded");
});
