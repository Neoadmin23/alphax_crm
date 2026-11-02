import frappe


def execute():
    """Add WhatsApp intake: Communication dedup field + settings defaults."""
    from alphax_crm.setup.install import setup_custom_fields, ensure_whatsapp_defaults

    setup_custom_fields()
    ensure_whatsapp_defaults()
    frappe.db.commit()
