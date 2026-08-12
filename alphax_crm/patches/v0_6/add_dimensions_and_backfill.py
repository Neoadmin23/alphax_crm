import frappe


def execute():
    """Extend activity monitor to Opportunity/Prospect, add accounting-dimension
    Link fields, and backfill last-activity from existing communications."""
    from alphax_crm.setup.install import (
        setup_custom_fields,
        setup_accounting_dimensions,
        ensure_activity_monitor_defaults,
    )
    from alphax_crm.crm.tasks import backfill_activity_monitor

    setup_custom_fields()
    ensure_activity_monitor_defaults()
    setup_accounting_dimensions()
    backfill_activity_monitor(["Lead", "Opportunity", "AlphaX Prospect"])
    frappe.db.commit()
