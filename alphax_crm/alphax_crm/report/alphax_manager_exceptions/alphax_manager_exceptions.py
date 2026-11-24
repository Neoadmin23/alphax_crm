import frappe
from alphax_crm.crm.sales_desk import exceptions


def execute(filters=None):
    return exceptions(frappe._dict(filters or {}))
