"""Shared helpers for AlphaX CRM Automation."""

import frappe

SETTINGS_DT = "AlphaX CRM Settings"


def get_settings():
    """Return the cached AlphaX CRM Settings single doc."""
    return frappe.get_cached_doc(SETTINGS_DT)


def is_enabled(flag):
    """Return truthy value of a boolean field on the settings single."""
    try:
        return bool(get_settings().get(flag))
    except Exception:
        return False


def log_error(title, message=None):
    """Thin wrapper so all module errors land under one searchable title."""
    frappe.log_error(message=message or frappe.get_traceback(), title=f"AlphaX CRM: {title}")


def active_lead_workflow_field():
    """The workflow_state_field of whichever Workflow is currently active
    for Lead, or None if there isn't one. Cached per-request via
    frappe.local since this is a database-only fact that can't change
    mid-request, and multiple call sites (PreLead conversion, Lead
    transition logging) need it.
    """
    if not hasattr(frappe.local, "_alphax_active_lead_wf_field"):
        frappe.local._alphax_active_lead_wf_field = frappe.db.get_value(
            "Workflow", {"document_type": "Lead", "is_active": 1}, "workflow_state_field"
        )
    return frappe.local._alphax_active_lead_wf_field
