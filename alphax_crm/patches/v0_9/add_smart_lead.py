import frappe


def execute():
    """Add Smart Lead: custom fields on Lead + seed the field map."""
    from alphax_crm.setup.install import setup_custom_fields, seed_smart_lead_map

    setup_custom_fields()
    seed_smart_lead_map()
    frappe.db.commit()
