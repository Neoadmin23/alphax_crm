import frappe
from alphax_crm.crm.sales_desk import forecast


def execute(filters=None):
    return forecast(frappe._dict(filters or {}))
