import frappe
from alphax_crm.crm.sales_desk import scorecard


def execute(filters=None):
    return scorecard(frappe._dict(filters or {}))
