import frappe


def execute():
    """Add Prospect layer + Lead review workflow (per sales process flow)."""
    from alphax_crm.setup.install import (
        setup_custom_fields,
        ensure_prospect_defaults,
        seed_prospect_statuses,
        setup_notifications,
        setup_lead_workflow,
    )

    setup_custom_fields()
    seed_prospect_statuses()
    ensure_prospect_defaults()
    setup_notifications()
    setup_lead_workflow()
    frappe.db.commit()
