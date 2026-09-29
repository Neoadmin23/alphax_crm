import frappe


def execute():
    """Add configurable report fields/filters + prospect convert-target setting."""
    from alphax_crm.setup.install import ensure_prospect_defaults, _seed_monitor_fields

    ensure_prospect_defaults()
    _seed_monitor_fields()
    frappe.db.commit()
