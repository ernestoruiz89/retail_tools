"""
Customer Lookup - Backend API

Provides API endpoints for the Customer Lookup page to search customers
and retrieve comprehensive customer snapshots including:
- Basic customer information
- Outstanding balance
- Purchase history
- Loyalty points (if available)
"""

from functools import lru_cache

import frappe
from frappe import _


@lru_cache(maxsize=1)
def _has_doctype(doctype: str) -> bool:
    """
    Check if a DocType exists in the system.

    Args:
        doctype: Name of the DocType to check

    Returns:
        True if the DocType exists, False otherwise
    """
    return frappe.db.exists("DocType", doctype)


@frappe.whitelist()
def search_customer(query: str) -> dict:
    """
    Search for customers by code, name, phone, or email.

    Args:
        query: Search string

    Returns:
        dict with:
        - ok (bool): Success status
        - customers (list): List of matching customers
        - message (str): Error message if failed
    """
    if not query or len(query.strip()) < 2:
        return {"ok": False, "message": _("Please enter at least 2 characters")}

    query = query.strip()

    # Search in multiple fields
    customers = frappe.get_all(
        "Customer",
        filters=[
            [
                "Customer",
                "name",
                "like",
                f"%{query}%",
            ]
        ],
        or_filters=[
            ["customer_name", "like", f"%{query}%"],
            ["mobile_no", "like", f"%{query}%"],
            ["email_id", "like", f"%{query}%"],
        ],
        fields=["name", "customer_name", "customer_group", "mobile_no", "email_id"],
        limit=20,
        order_by="customer_name asc",
    )

    if not customers:
        return {"ok": False, "message": _("No customers found")}

    return {"ok": True, "customers": customers}


@frappe.whitelist()
def get_customer_snapshot(customer: str) -> dict:
    """
    Return a comprehensive snapshot for a customer.

    Includes:
    - Basic customer information
    - Outstanding balance
    - Total lifetime purchases
    - Recent sales invoices
    - Loyalty points (if Loyalty Program exists)

    Args:
        customer: Customer ID/name

    Returns:
        dict with customer data or error message
    """
    if not customer:
        return {"ok": False, "message": _("Customer is required")}

    if not frappe.db.exists("Customer", customer):
        return {"ok": False, "message": _("Customer not found")}

    # Get basic customer data
    customer_data = _get_customer_data(customer)

    # Get financial data
    outstanding = _get_outstanding_balance(customer)
    lifetime_value = _get_lifetime_value(customer)
    last_purchase = _get_last_purchase_date(customer)

    # Get recent invoices
    recent_invoices = _get_recent_invoices(customer)

    # Get loyalty points if available
    loyalty_points = _get_loyalty_points(customer)

    return {
        "ok": True,
        "customer": customer_data,
        "outstanding": outstanding,
        "lifetime_value": lifetime_value,
        "last_purchase": last_purchase,
        "recent_invoices": recent_invoices,
        "loyalty": loyalty_points,
    }


def _get_customer_data(customer: str) -> dict:
    """Get basic customer master data."""
    fields = [
        "name",
        "customer_name",
        "customer_group",
        "territory",
        "customer_type",
        "mobile_no",
        "email_id",
        "image",
        "primary_address",
        "customer_primary_contact",
    ]

    data = frappe.get_value("Customer", customer, fields, as_dict=True)

    # Get formatted address if available
    if data.get("primary_address"):
        data["address_display"] = frappe.get_value(
            "Address", data["primary_address"], "address_line1"
        )

    # Get contact name if available
    if data.get("customer_primary_contact"):
        data["contact_display"] = frappe.get_value(
            "Contact", data["customer_primary_contact"], "first_name"
        )

    return data


def _get_outstanding_balance(customer: str) -> dict:
    """
    Get total outstanding balance from unpaid Sales Invoices.

    Returns:
        dict with amount and currency
    """
    result = frappe.db.sql(
        """
        SELECT 
            COALESCE(SUM(outstanding_amount), 0) as outstanding,
            currency
        FROM `tabSales Invoice`
        WHERE customer = %s
          AND docstatus = 1
          AND outstanding_amount > 0
        GROUP BY currency
        LIMIT 1
        """,
        (customer,),
        as_dict=True,
    )

    if result:
        return {
            "amount": result[0].outstanding,
            "currency": result[0].currency,
        }

    # Get default currency if no invoices
    default_currency = frappe.get_cached_value(
        "Company",
        frappe.defaults.get_user_default("Company"),
        "default_currency",
    ) or "USD"

    return {"amount": 0, "currency": default_currency}


def _get_lifetime_value(customer: str) -> dict:
    """
    Get total lifetime purchases from Sales Invoices.

    Returns:
        dict with amount, count, and currency
    """
    result = frappe.db.sql(
        """
        SELECT 
            COALESCE(SUM(base_grand_total), 0) as total,
            COUNT(*) as count,
            currency
        FROM `tabSales Invoice`
        WHERE customer = %s
          AND docstatus = 1
        GROUP BY currency
        ORDER BY total DESC
        LIMIT 1
        """,
        (customer,),
        as_dict=True,
    )

    if result:
        return {
            "amount": result[0].total,
            "count": result[0].count,
            "currency": result[0].currency,
        }

    default_currency = frappe.get_cached_value(
        "Company",
        frappe.defaults.get_user_default("Company"),
        "default_currency",
    ) or "USD"

    return {"amount": 0, "count": 0, "currency": default_currency}


def _get_last_purchase_date(customer: str) -> str | None:
    """Get the date of the last purchase."""
    result = frappe.db.get_value(
        "Sales Invoice",
        {"customer": customer, "docstatus": 1},
        "posting_date",
        order_by="posting_date desc",
    )
    return str(result) if result else None


def _get_recent_invoices(customer: str, limit: int = 10) -> list:
    """
    Get recent sales invoices for the customer.

    Args:
        customer: Customer ID
        limit: Maximum number of invoices to return

    Returns:
        List of invoice dicts with key fields
    """
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1},
        fields=[
            "name",
            "posting_date",
            "grand_total",
            "currency",
            "status",
            "outstanding_amount",
            "is_return",
        ],
        order_by="posting_date desc, creation desc",
        limit=limit,
    )

    return invoices


def _get_loyalty_points(customer: str) -> dict | None:
    """
    Get loyalty points for the customer if Loyalty Program exists.

    Returns:
        dict with points info or None if not available
    """
    # Check if Loyalty Point Entry doctype exists
    if not _has_doctype("Loyalty Point Entry"):
        return None

    # Get customer's loyalty program
    loyalty_program = frappe.db.get_value("Customer", customer, "loyalty_program")

    if not loyalty_program:
        return None

    # Calculate total points
    result = frappe.db.sql(
        """
        SELECT 
            COALESCE(SUM(loyalty_points), 0) as total_points
        FROM `tabLoyalty Point Entry`
        WHERE customer = %s
          AND docstatus = 1
        """,
        (customer,),
        as_dict=True,
    )

    total_points = result[0].total_points if result else 0

    # Get expiring points (next 30 days)
    from frappe.utils import add_days, nowdate

    expiring = frappe.db.sql(
        """
        SELECT 
            COALESCE(SUM(loyalty_points), 0) as points
        FROM `tabLoyalty Point Entry`
        WHERE customer = %s
          AND docstatus = 1
          AND expiry_date BETWEEN %s AND %s
          AND loyalty_points > 0
        """,
        (customer, nowdate(), add_days(nowdate(), 30)),
        as_dict=True,
    )

    expiring_points = expiring[0].points if expiring else 0

    return {
        "program": loyalty_program,
        "total_points": total_points,
        "expiring_soon": expiring_points,
    }
