import frappe


def execute():
    """Add the Lead Activity Monitor: last-activity fields + monitored statuses."""
    from alphax_crm.setup.install import setup_custom_fields, ensure_activity_monitor_defaults

    setup_custom_fields()
    ensure_activity_monitor_defaults()
    frappe.db.commit()
