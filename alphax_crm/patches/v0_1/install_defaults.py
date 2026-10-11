import frappe


def execute():
    """Install/refresh AlphaX CRM defaults, custom fields, notifications, workflow."""
    from alphax_crm.setup.install import (
        setup_custom_fields,
        seed_default_settings,
        setup_notifications,
        setup_lead_workflow,
    )

    setup_custom_fields()
    seed_default_settings()
    setup_notifications()
    setup_lead_workflow()
    frappe.db.commit()
