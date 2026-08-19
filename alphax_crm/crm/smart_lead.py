"""AlphaX Smart Lead -> ERPNext Lead mapping.

The Smart Lead is the clean data-entry surface. On save it maps into the (often
over-customized) ERPNext Lead using a configurable field map held in
AlphaX CRM Settings (smart_lead_map), so no duplicate fields and no field-type
fights. Multi cost-center service dimensions and the Saudi National Address are
carried across too.
"""

import frappe
from frappe import _


TRANSFORMS = {
    "None": lambda v: v,
    "Trim": lambda v: (v or "").strip(),
    "Title Case": lambda v: (v or "").title(),
    "Uppercase": lambda v: (v or "").upper(),
    "Lowercase": lambda v: (v or "").lower(),
}


def _normalize_mobile(v):
    try:
        from alphax_crm.crm.data_quality import normalize_saudi_mobile

        return normalize_saudi_mobile(v) or v
    except Exception:
        return v


def _default_map():
    # (smart_field, lead_field, transform)
    return [
        ("organization", "company_name", "None"),
        ("contact_name", "lead_name", "None"),
        ("first_name", "first_name", "None"),
        ("last_name", "last_name", "None"),
        ("job_title", "job_title", "None"),
        ("email", "email_id", "None"),
        ("mobile_no", "mobile_no", "Normalize Mobile"),
        ("whatsapp_no", "whatsapp_no", "Normalize Mobile"),
        ("phone", "phone", "None"),
        ("website", "website", "None"),
        ("lead_source", "source", "None"),
        ("territory", "territory", "None"),
        ("lead_owner", "lead_owner", "None"),
        ("lead_type", "type", "None"),
        ("request_type", "request_type", "None"),
        ("na_city", "city", "None"),
        ("status", "status", "None"),
        ("industry", "industry", "None"),
        ("business_units", "custom_business_lead_unit", "None"),
    ]


def get_map(settings=None):
    settings = settings or frappe.get_cached_doc("AlphaX CRM Settings")
    rows = settings.get("smart_lead_map") or []
    if rows:
        return [(r.smart_field, r.lead_field, r.transform or "None") for r in rows if r.smart_field and r.lead_field]
    return _default_map()


def _apply(transform, value):
    if transform == "Normalize Mobile":
        return _normalize_mobile(value)
    return TRANSFORMS.get(transform, TRANSFORMS["None"])(value)


def maybe_sync_to_lead(doc, on_insert=False):
    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    if settings.get("smart_lead_autocreate") == 0:
        return
    # On insert always create; on update only re-sync if already linked.
    if not on_insert and not doc.get("lead"):
        return
    try:
        sync_to_lead(doc.name)
    except Exception:
        frappe.log_error(title="AlphaX CRM: smart lead sync", message=frappe.get_traceback())


@frappe.whitelist()
def sync_to_lead(smart_lead):
    """Create or update the ERPNext Lead from a Smart Lead. Returns lead name."""
    doc = frappe.get_doc("AlphaX Smart Lead", smart_lead)
    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    lead_meta = frappe.get_meta("Lead")

    if doc.get("lead") and frappe.db.exists("Lead", doc.lead):
        lead = frappe.get_doc("Lead", doc.lead)
        creating = False
    else:
        lead = frappe.new_doc("Lead")
        creating = True

    # 1) configurable field map
    for smart_field, lead_field, transform in get_map(settings):
        if not lead_meta.has_field(lead_field):
            continue
        val = doc.get(smart_field)
        if val in (None, ""):
            continue
        # Link guards
        df = lead_meta.get_field(lead_field)
        if df and df.fieldtype == "Link" and df.options and not frappe.db.exists(df.options, val):
            continue
        lead.set(lead_field, _apply(transform, val))

    # 2) national address -> combined + custom field
    na = _national_address_string(doc)
    if na and lead_meta.has_field("alphax_national_address"):
        lead.alphax_national_address = na
    if doc.get("na_city") and lead_meta.has_field("city") and not lead.get("city"):
        lead.city = doc.na_city

    # 3) primary cost center (highest split, else first) -> dimension field
    primary = _primary_cost_center(doc)
    if primary and lead_meta.has_field("cost_center") and frappe.db.exists("Cost Center", primary):
        lead.cost_center = primary

    # 4) branch (if the Lead has such a field)
    if doc.get("branch") and lead_meta.has_field("branch") and frappe.db.exists("Branch", doc.branch):
        lead.branch = doc.branch

    # 5) back-link + skip DQ block on auto creation
    if lead_meta.has_field("alphax_smart_lead"):
        lead.alphax_smart_lead = doc.name
    lead.flags.alphax_skip_dq = True
    lead.flags.ignore_permissions = True

    if creating:
        lead.insert(ignore_permissions=True)
    else:
        lead.save(ignore_permissions=True)

    frappe.db.set_value("AlphaX Smart Lead", doc.name,
                        {"lead": lead.name, "mapped": 1}, update_modified=False)

    if creating:
        lead.add_comment("Comment", text=_("Created from Smart Lead {0}.").format(doc.name))
    return lead.name


def _national_address_string(doc):
    parts = [
        doc.get("na_building_no"), doc.get("na_street"), doc.get("na_district"),
        doc.get("na_city"), doc.get("na_region"), doc.get("na_postal_code"),
    ]
    line = ", ".join([p for p in parts if p])
    if doc.get("na_short_address"):
        line = f"{doc.na_short_address} — {line}" if line else doc.na_short_address
    return line


def _primary_cost_center(doc):
    rows = doc.get("service_dimensions") or []
    if not rows:
        return None
    ranked = sorted(rows, key=lambda r: (r.split_percent or 0), reverse=True)
    return ranked[0].cost_center


# Each target doctype in the CRM spells "email" differently — same lesson
# learned (the hard way) from Smart Import's duplicate check: build filters
# per doctype, never assume one fieldname works everywhere.
_DEDUP_EMAIL_FIELD = {"Lead": "email_id", "AlphaX Prospect": "email_id", "AlphaX Smart Lead": "email"}


@frappe.whitelist()
def check_duplicate(email=None, mobile_no=None, exclude=None):
    """Live duplicate check for the Smart Lead form (email/mobile, on blur).

    Returns a list of {doctype, name, title} for existing Lead / AlphaX
    Prospect / AlphaX Smart Lead records matching either value, excluding
    `exclude` (the current, possibly-unsaved record's own name) so an
    existing record doesn't flag itself while being edited.
    """
    if not email and not mobile_no:
        return []
    matches = []
    for dt, email_field in _DEDUP_EMAIL_FIELD.items():
        or_filters = []
        if email:
            or_filters.append([email_field, "=", email])
        if mobile_no:
            or_filters.append(["mobile_no", "=", mobile_no])
        if not or_filters:
            continue
        title_field = "lead_name" if dt == "Lead" else ("prospect_name" if dt == "AlphaX Prospect" else "organization")
        for row in frappe.get_all(dt, or_filters=or_filters, fields=["name", title_field], limit=5):
            name = row.get("name")
            if dt == "AlphaX Smart Lead" and exclude and name == exclude:
                continue
            matches.append({"doctype": dt, "name": name, "title": row.get(title_field) or name})
    return matches


@frappe.whitelist()
def verify_national_address(smart_lead=None, short_address=None, cr_number=None):
    """Verify / fetch the Saudi National Address via the SPL API.

    Requires SPL credentials in AlphaX CRM Settings (na_api_url + na_api_key).
    Without them this returns a helpful message rather than failing — the SPL
    National Address service is a paid, credentialed API (address.gov.sa).
    """
    settings = frappe.get_cached_doc("AlphaX CRM Settings")
    api_url = settings.get("na_api_url")
    api_key = settings.get_password("na_api_key") if settings.get("na_api_key") else None
    if not api_url or not api_key:
        return {"ok": False, "message": _(
            "Saudi National Address lookup needs SPL API credentials. Set 'National Address API URL' "
            "and 'API Key' in AlphaX CRM Settings (from address.gov.sa).")}
    # Live call intentionally left as an integration point (requires SPL contract):
    # response = requests.get(api_url, params={...}, headers={"api_key": api_key}, timeout=20)
    return {"ok": False, "message": _(
        "SPL credentials found. Wire the live SPL endpoint to enable automatic lookup.")}
