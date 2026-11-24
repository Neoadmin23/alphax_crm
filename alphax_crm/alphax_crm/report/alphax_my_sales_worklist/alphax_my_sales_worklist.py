import frappe
from alphax_crm.crm.sales_desk import worklist


def execute(filters=None):
    return worklist(frappe._dict(filters or {}))
