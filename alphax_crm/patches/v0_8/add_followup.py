import frappe


def execute():
    """Register the Follow-up mechanism (doctype ships via model sync; this
    just clears caches so the new report/doctype are picked up)."""
    frappe.clear_cache()
    frappe.db.commit()
