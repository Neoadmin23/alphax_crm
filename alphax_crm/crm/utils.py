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
