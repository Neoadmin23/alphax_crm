import frappe
from alphax_crm.crm.commercial import movements


def execute(filters=None):
    return movements(frappe._dict(filters or {}))
