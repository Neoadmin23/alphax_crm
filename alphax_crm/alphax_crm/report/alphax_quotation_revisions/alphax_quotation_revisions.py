import frappe
from alphax_crm.crm.commercial import revisions


def execute(filters=None):
    return revisions(frappe._dict(filters or {}))
