import frappe
from alphax_crm.crm.sales_desk import action_report


def execute(filters=None):
    return action_report(frappe._dict(filters or {}))
