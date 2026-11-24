import frappe


def execute():
    """Add the data-quality gate: Lead completeness fields + default rules."""
    from alphax_crm.setup.install import setup_custom_fields, ensure_dq_rules

    setup_custom_fields()
    ensure_dq_rules()
    frappe.db.commit()
