"""Idempotent setup for AlphaX CRM Automation.

Runs on after_install and (via patch) after_migrate, so pushing the app to
Frappe Cloud and letting it migrate is enough — no bench shell required.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    setup_custom_fields()
    setup_accounting_dimensions()
    seed_default_settings()
    ensure_whatsapp_defaults()
    ensure_dq_rules()
    ensure_prospect_defaults()
    ensure_activity_monitor_defaults()
    _seed_monitor_fields()
    seed_smart_lead_map()
    seed_prospect_statuses()
    seed_job_titles()
    seed_lead_stage_map()
    sync_lead_stage_options()
    seed_stage_transitions()
    ensure_closure_defaults()
    ensure_wf_defaults()
    seed_stage_sla_rules()
    setup_notifications()
    setup_lead_approval_workflow()
    frappe.db.commit()


def after_migrate():
    # Keep config self-healing on every deploy.
    setup_custom_fields()
    setup_accounting_dimensions()
    ensure_whatsapp_defaults()
    ensure_dq_rules()
    ensure_prospect_defaults()
    ensure_activity_monitor_defaults()
    _seed_monitor_fields()
    seed_smart_lead_map()
    seed_prospect_statuses()
    seed_job_titles()
    seed_lead_stage_map()
    sync_lead_stage_options()
    seed_stage_transitions()
    ensure_closure_defaults()
    ensure_wf_defaults()
    seed_stage_sla_rules()
    setup_notifications()
    setup_lead_approval_workflow()
    frappe.db.commit()


def _default_stage_transitions():
    # The approved flow from the spec's own diagram:
    #   Lead -> Interested -> Qualified lead -> Quotation
    #   -> Postponed / Contract Under Signing -> Won / Lost
    # This is only the seeded starting point — fully editable afterward in
    # AlphaX CRM Settings > Stage Transitions, with no code change needed to
    # add, remove, or rename a step.
    return [
        ("Lead", "Interested"),
        ("Interested", "Qualified lead"),
        ("Qualified lead", "Quotation"),
        ("Quotation", "Postponed"),
        ("Quotation", "Contract Under Signing"),
        ("Postponed", "Won"),
        ("Postponed", "Lost with reason"),
        ("Postponed", "Lost Quotation"),
        ("Contract Under Signing", "Won"),
        ("Contract Under Signing", "Lost with reason"),
        ("Contract Under Signing", "Lost Quotation"),
    ]


def seed_stage_transitions():
    """Seed the approved-flow table (WF-01) only if it's empty — never
    overwrites transitions the admin has since customized."""
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    if not frappe.db.exists("DocType", "AlphaX Lead Stage Transition"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    if not frappe.get_meta("AlphaX CRM Settings").has_field("stage_transitions"):
        return
    settings = frappe.get_single("AlphaX CRM Settings")
    if settings.get("stage_transitions"):
        return
    for frm, to in _default_stage_transitions():
        settings.append("stage_transitions", {"from_stage": frm, "to_stage": to})
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)


def ensure_closure_defaults():
    """Populate WF-06 closure-control defaults on existing installs without
    overwriting anything already set (idempotent, self-healing on migrate,
    same pattern as ensure_whatsapp_defaults/ensure_prospect_defaults)."""
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    meta = frappe.get_meta("AlphaX CRM Settings")
    if not meta.has_field("closure_controls_enabled"):
        return
    doc = frappe.get_single("AlphaX CRM Settings")
    defaults = {
        "stage_flow_enabled": 1,
        "stage_flow_bypass_roles": "System Manager,Sales Manager",
        "closure_controls_enabled": 1,
        "won_stage_value": "Won",
        "lost_stage_values": "Lost with reason,Lost Quotation",
        "contract_signed_value": "Signed",
        "require_customer_for_won": 1,
    }
    changed = False
    for f, v in defaults.items():
        if doc.get(f) in (None, ""):
            doc.set(f, v)
            changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)


def ensure_wf_defaults():
    """Defaults for the WF-02/03/05 settings added alongside the Phase 1
    stage-flow/closure work: the Approver role, quotation-submit
    notifications, Postponed/Lost Quotation stage values. Idempotent, never
    overwrites a value already set."""
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    meta = frappe.get_meta("AlphaX CRM Settings")
    if not meta.has_field("approver_role"):
        return
    doc = frappe.get_single("AlphaX CRM Settings")
    defaults = {
        "approver_role": "Sales Manager",
        "notify_approvers_on_quotation": 1,
        "postponed_stage_value": "Postponed",
        "postponed_default_revisit_days": 30,
        "lost_quotation_stage_value": "Lost Quotation",
        "lost_quotation_digest_enabled": 1,
        "stage_sla_enabled": 1,
    }
    changed = False
    for f, v in defaults.items():
        if doc.get(f) in (None, ""):
            doc.set(f, v)
            changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)


def _default_stage_sla_rules():
    # (stage, days, notify, require_no_activity, label)
    return [
        # WF-05 "Lead": two-stage reminder, per the customer's own revision
        # (first reminder Day 3, second reminder 4 days after that = Day 7)
        # — no separate "escalation" milestone specified for this stage.
        ("Lead", 3, "Lead Owner", 1, "First reminder — no contact yet"),
        ("Lead", 7, "Lead Owner", 1, "Second reminder — still no contact"),
        # Interested: meeting expected within 3 days.
        ("Interested", 3, "Lead Owner", 1, "Reminder — schedule/hold a meeting"),
        ("Interested", 7, "Approver (Sales Manager)", 1, "Escalation — meeting not held"),
        # Qualified lead: quotation expected within 5 days.
        ("Qualified lead", 5, "Lead Owner", 1, "Reminder — quotation expected"),
        ("Qualified lead", 10, "Approver (Sales Manager)", 1, "Escalation — quotation overdue"),
        # Contract Under Signing: follow-up every 3 days, escalate Day 10,
        # plus a dedicated Approver check-in on Day 4 (per the customer's
        # own addition).
        ("Contract Under Signing", 3, "Lead Owner", 1, "Follow-up"),
        ("Contract Under Signing", 4, "Approver (Sales Manager)", 0, "Approver check-in"),
        ("Contract Under Signing", 6, "Lead Owner", 1, "Follow-up"),
        ("Contract Under Signing", 9, "Lead Owner", 1, "Follow-up"),
        ("Contract Under Signing", 10, "Approver (Sales Manager)", 1, "Escalation — contract not signed"),
    ]


def seed_stage_sla_rules():
    """Seed WF-05's per-stage SLA table only if it's empty — never
    overwrites rules the admin has since customized. Postponed is handled
    by its own Next-Contact-Date logic (run_postponed_followups), not this
    table."""
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    if not frappe.db.exists("DocType", "AlphaX Lead Stage SLA"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    if not frappe.get_meta("AlphaX CRM Settings").has_field("stage_sla_rules"):
        return
    settings = frappe.get_single("AlphaX CRM Settings")
    if settings.get("stage_sla_rules"):
        return
    for stage, days, notify, require_no_activity, label in _default_stage_sla_rules():
        settings.append("stage_sla_rules", {
            "stage": stage, "days": days, "notify": notify,
            "require_no_activity": require_no_activity, "label": label,
        })
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)


def sync_lead_stage_options():
    """Fixes existing sites where the seeded/edited Lead Stage Map names
    values (Qualified lead, Postponed, Contract Under Signing, Won, Lost
    with reason, ...) that were never added as options on Lead's native
    `status` Select field — see crm.utils.ensure_select_option for why that
    blocks every save that triggers the automation, with an error message
    that doesn't obviously point back here. Safe/idempotent on every
    install and migrate; also runs on every AlphaX CRM Settings save (see
    that doctype's on_update) so this never lags behind an admin edit.
    """
    if not frappe.db.exists("DocType", "AlphaX CRM Settings") or not frappe.db.exists("DocType", "Lead"):
        return
    try:
        from alphax_crm.crm.lead import sync_lead_stage_options as _sync

        frappe.clear_cache(doctype="AlphaX CRM Settings")
        _sync(frappe.get_single("AlphaX CRM Settings"))
    except Exception:
        frappe.log_error(title="AlphaX CRM: sync lead stage options (install)", message=frappe.get_traceback())


def _seed_monitor_fields():
    try:
        from alphax_crm.crm.tasks import seed_monitor_fields

        seed_monitor_fields()
    except Exception:
        frappe.log_error(title="AlphaX CRM: seed monitor fields", message=frappe.get_traceback())


# ---------------------------------------------------------------------------
# Custom fields  (AlphaX-prefixed so the hooks fixture filter picks them up)
# ---------------------------------------------------------------------------
def setup_custom_fields():
    fields = {
        "Lead": [
            {
                "fieldname": "alphax_crm_section",
                "label": "AlphaX CRM",
                "fieldtype": "Section Break",
                "insert_after": "company_name",
                "collapsible": 1,
            },
            {
                "fieldname": "alphax_lead_score",
                "label": "Lead Score",
                "fieldtype": "Int",
                "read_only": 1,
                "in_list_view": 1,
                "insert_after": "alphax_crm_section",
            },
            {
                "fieldname": "alphax_dq_score",
                "label": "Data Completeness %",
                "fieldtype": "Int",
                "read_only": 1,
                "insert_after": "alphax_lead_score",
            },
            {
                "fieldname": "alphax_next_contact_date",
                "label": "Next Contact Date",
                "fieldtype": "Date",
                "insert_after": "alphax_lead_score",
            },
            {
                "fieldname": "alphax_last_activity",
                "label": "Last Activity",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "alphax_next_contact_date",
            },
            {
                "fieldname": "alphax_last_activity_by",
                "label": "Last Activity By",
                "fieldtype": "Link",
                "options": "User",
                "read_only": 1,
                "insert_after": "alphax_last_activity",
            },
            {
                "fieldname": "alphax_last_activity_type",
                "label": "Last Activity Type",
                "fieldtype": "Data",
                "read_only": 1,
                "insert_after": "alphax_last_activity_by",
            },
            {
                "fieldname": "alphax_last_activity_summary",
                "label": "Last Activity Summary",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_last_activity_type",
            },
            {
                "fieldname": "alphax_idle_days",
                "label": "Idle Days",
                "fieldtype": "Int",
                "read_only": 1,
                "in_standard_filter": 1,
                "insert_after": "alphax_last_activity_summary",
            },
            {
                "fieldname": "alphax_score_breakdown",
                "label": "Score Breakdown",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_idle_days",
            },
            {
                "fieldname": "alphax_dq_report",
                "label": "Data Quality Report",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_score_breakdown",
            },
            {
                "fieldname": "alphax_ai_col",
                "fieldtype": "Column Break",
                "insert_after": "alphax_score_breakdown",
            },
            {
                "fieldname": "alphax_ai_brief",
                "label": "AI Brief",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_ai_col",
            },
            {
                "fieldname": "alphax_ai_draft_reply",
                "label": "AI Draft Reply",
                "fieldtype": "Text",
                "insert_after": "alphax_ai_brief",
            },
            {
                "fieldname": "alphax_inbound_message",
                "label": "Inbound Message",
                "fieldtype": "Small Text",
                "insert_after": "alphax_ai_draft_reply",
            },
            {
                "fieldname": "alphax_pdpl_section",
                "label": "Consent & PDPL",
                "fieldtype": "Section Break",
                "collapsible": 1,
                "insert_after": "alphax_inbound_message",
            },
            {
                "fieldname": "alphax_consent_given",
                "label": "Consent Given",
                "fieldtype": "Check",
                "insert_after": "alphax_pdpl_section",
            },
            {
                "fieldname": "alphax_consent_datetime",
                "label": "Consent Timestamp",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "alphax_consent_given",
            },
            {
                "fieldname": "alphax_consent_source",
                "label": "Consent Source",
                "fieldtype": "Data",
                "insert_after": "alphax_consent_datetime",
            },
            {
                "fieldname": "alphax_pdpl_col",
                "fieldtype": "Column Break",
                "insert_after": "alphax_consent_source",
            },
            {
                "fieldname": "alphax_lawful_basis",
                "label": "Lawful Basis",
                "fieldtype": "Select",
                "options": "\nConsent\nContract\nLegitimate Interest\nLegal Obligation",
                "insert_after": "alphax_pdpl_col",
            },
            {
                "fieldname": "alphax_pdpl_anonymized",
                "label": "PDPL Anonymized",
                "fieldtype": "Check",
                "read_only": 1,
                "insert_after": "alphax_lawful_basis",
            },
            {
                "fieldname": "alphax_review_section",
                "label": "Lead Review",
                "fieldtype": "Section Break",
                "collapsible": 0,
                "insert_after": "alphax_pdpl_anonymized",
            },
            {
                "fieldname": "alphax_review_status",
                "label": "Review Status",
                "fieldtype": "Select",
                "options": "\nPending Review\nApproved\nReturned for Correction\nRejected",
                "default": "Pending Review",
                "in_standard_filter": 1,
                "in_list_view": 1,
                "read_only": 1,
                "insert_after": "alphax_review_section",
            },
            {
                "fieldname": "alphax_prospect",
                "label": "Source PreLead",
                "fieldtype": "Data",
                "read_only": 1,
                "hidden": 0,
                "insert_after": "alphax_review_status",
                "description": "Plain text, not a Link — deliberately, so this Lead and the PreLead it came from can each be deleted independently without Frappe's link-integrity check blocking either one.",
            },
            {
                "fieldname": "alphax_review_col",
                "fieldtype": "Column Break",
                "insert_after": "alphax_prospect",
            },
            {
                "fieldname": "alphax_review_notes",
                "label": "Review / Correction Notes",
                "fieldtype": "Small Text",
                "insert_after": "alphax_review_col",
            },
            {
                "fieldname": "alphax_reviewed_by",
                "label": "Reviewed By",
                "fieldtype": "Link",
                "options": "User",
                "read_only": 1,
                "insert_after": "alphax_review_notes",
            },
            {
                "fieldname": "alphax_smart_lead",
                "label": "Smart Lead",
                "fieldtype": "Link",
                "options": "AlphaX Smart Lead",
                "read_only": 1,
                "insert_after": "alphax_reviewed_by",
            },
            {
                "fieldname": "alphax_national_address",
                "label": "National Address",
                "fieldtype": "Small Text",
                "insert_after": "alphax_smart_lead",
            },
            {
                "fieldname": "alphax_closure_section",
                "label": "Closure Controls (WF-06)",
                "fieldtype": "Section Break",
                "collapsible": 1,
                "insert_after": "alphax_national_address",
            },
            {
                "fieldname": "alphax_contract_status",
                "label": "Contract",
                "fieldtype": "Select",
                "options": "\nBlank\nSigned",
                "insert_after": "alphax_closure_section",
                "description": "Required to be \"Signed\" (or whatever AlphaX CRM Settings > Closure Controls names as the signed value) before this Lead can be marked Won.",
            },
            {
                "fieldname": "alphax_won_lost_date",
                "label": "Won/Lost Date",
                "fieldtype": "Date",
                "insert_after": "alphax_contract_status",
            },
            {
                "fieldname": "alphax_closure_col",
                "fieldtype": "Column Break",
                "insert_after": "alphax_won_lost_date",
            },
            {
                "fieldname": "alphax_lost_reason",
                "label": "Lost Reason",
                "fieldtype": "Data",
                "insert_after": "alphax_closure_col",
            },
            {
                "fieldname": "alphax_lost_detailed_reason",
                "label": "Detailed Reason",
                "fieldtype": "Small Text",
                "insert_after": "alphax_lost_reason",
            },
        ],
        "Opportunity": [
            {
                "fieldname": "alphax_crm_section",
                "label": "AlphaX CRM",
                "fieldtype": "Section Break",
                "collapsible": 1,
                "insert_after": "contact_mobile",
            },
            {
                "fieldname": "alphax_next_activity_date",
                "label": "Next Activity Date",
                "fieldtype": "Date",
                "insert_after": "alphax_crm_section",
            },
            {
                "fieldname": "alphax_last_activity",
                "label": "Last Activity",
                "fieldtype": "Datetime",
                "read_only": 1,
                "insert_after": "alphax_next_activity_date",
            },
            {
                "fieldname": "alphax_last_activity_by",
                "label": "Last Activity By",
                "fieldtype": "Link",
                "options": "User",
                "read_only": 1,
                "insert_after": "alphax_last_activity",
            },
            {
                "fieldname": "alphax_last_activity_type",
                "label": "Last Activity Type",
                "fieldtype": "Data",
                "read_only": 1,
                "insert_after": "alphax_last_activity_by",
            },
            {
                "fieldname": "alphax_last_activity_summary",
                "label": "Last Activity Summary",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_last_activity_type",
            },
            {
                "fieldname": "alphax_idle_days",
                "label": "Idle Days",
                "fieldtype": "Int",
                "read_only": 1,
                "in_standard_filter": 1,
                "insert_after": "alphax_last_activity_summary",
            },
            {
                "fieldname": "alphax_ai_col",
                "fieldtype": "Column Break",
                "insert_after": "alphax_idle_days",
            },
            {
                "fieldname": "alphax_ai_brief",
                "label": "AI Brief",
                "fieldtype": "Small Text",
                "read_only": 1,
                "insert_after": "alphax_ai_col",
            },
            {
                "fieldname": "alphax_risk_signal",
                "label": "Risk Signal",
                "fieldtype": "Data",
                "read_only": 1,
                "insert_after": "alphax_ai_brief",
            },
        ],
        "Communication": [
            {
                "fieldname": "alphax_wa_message_id",
                "label": "WhatsApp Message ID",
                "fieldtype": "Data",
                "read_only": 1,
                "no_copy": 1,
                "search_index": 1,
                "insert_after": "message_id",
            },
        ],
    }
    create_custom_fields(fields, ignore_validate=True)

    # Belt-and-suspenders: create_custom_fields() only reliably updates the
    # properties explicitly listed above for a field that already exists —
    # if "hidden" was set independently at some point (manually, or by an
    # older version of this field definition that never mentioned it), a
    # generic sync isn't guaranteed to touch it. Force it directly so this
    # field can't silently stay invisible on an existing site.
    if frappe.db.exists("Custom Field", "Lead-alphax_prospect"):
        frappe.db.set_value("Custom Field", "Lead-alphax_prospect", "hidden", 0)


# ---------------------------------------------------------------------------
# Accounting dimensions -> Link fields on Lead / PreLead / Opportunity
# ---------------------------------------------------------------------------
DIM_TARGETS = ["Lead", "AlphaX PreLead", "Opportunity"]
DIM_ANCHOR = {"Lead": "alphax_reviewed_by", "AlphaX PreLead": "job_title", "Opportunity": "alphax_risk_signal"}


def active_accounting_dimensions():
    """Return [(fieldname, label, link_doctype)] for every activated dimension."""
    dims = []
    seen = set()
    if frappe.db.exists("DocType", "Accounting Dimension"):
        for d in frappe.get_all(
            "Accounting Dimension",
            filters={"disabled": 0},
            fields=["fieldname", "label", "document_type"],
        ):
            if d.fieldname and d.document_type and d.fieldname not in seen:
                dims.append((d.fieldname, d.label or d.document_type, d.document_type))
                seen.add(d.fieldname)
    # Standard dimensions Noor named: Cost Center + Department.
    for fn, dt in (("cost_center", "Cost Center"), ("department", "Department")):
        if fn not in seen and frappe.db.exists("DocType", dt):
            dims.append((fn, dt, dt))
            seen.add(fn)
    return dims


def setup_accounting_dimensions():
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    settings = frappe.get_single("AlphaX CRM Settings")
    if settings.get("sync_accounting_dimensions") == 0:
        return

    dims = active_accounting_dimensions()
    if not dims:
        return

    fields = {}
    for target in DIM_TARGETS:
        if not frappe.db.exists("DocType", target):
            continue
        if target == "AlphaX PreLead":
            # Opt-in and restricted (default: Cost Center only) — see
            # prospect_dimensions_enabled / prospect_dimension_fields.
            # Lead and Opportunity are unaffected and keep the prior
            # all-active-dimensions behavior.
            if not settings.get("prospect_dimensions_enabled"):
                continue
            allowed = {
                f.strip() for f in (settings.get("prospect_dimension_fields") or "cost_center").split(",")
                if f.strip()
            }
            target_dims = [d for d in dims if d[0] in allowed]
        else:
            target_dims = dims
        if not target_dims:
            continue
        meta = frappe.get_meta(target)
        rows = []
        anchor = DIM_ANCHOR.get(target)
        if not anchor or not meta.has_field(anchor):
            anchor = meta.fields[-1].fieldname if meta.fields else None
        if not meta.has_field("alphax_dimensions_section"):
            rows.append({
                "fieldname": "alphax_dimensions_section", "fieldtype": "Section Break",
                "label": "Accounting Dimensions", "collapsible": 1, "insert_after": anchor,
            })
        prev = "alphax_dimensions_section"
        for fn, label, doctype in target_dims:
            if target == "AlphaX PreLead" and fn == "cost_center":
                # A PreLead can belong to more than one cost center — a flat
                # Link can't represent that. Reuse the exact same
                # multi-cost-center pattern already proven on AlphaX Smart
                # Lead (a table of Cost Center + split %, resolved to a
                # single "primary" cost center — highest split — when
                # converting to Lead) instead of inventing a second one.
                if meta.has_field("cost_center_splits"):
                    prev = "cost_center_splits"
                    continue
                if not frappe.db.exists("DocType", "AlphaX Service Dimension"):
                    continue
                rows.append({
                    "fieldname": "cost_center_splits", "fieldtype": "Table", "label": "Cost Center Splits",
                    "options": "AlphaX Service Dimension", "insert_after": prev,
                })
                prev = "cost_center_splits"
                continue
            if meta.has_field(fn):        # already on the doctype (native or created)
                prev = fn
                continue
            if not frappe.db.exists("DocType", doctype):
                continue
            rows.append({
                "fieldname": fn, "fieldtype": "Link", "label": label,
                "options": doctype, "insert_after": prev,
            })
            prev = fn
        if rows:
            fields[target] = rows

    if fields:
        create_custom_fields(fields, ignore_validate=True)


# ---------------------------------------------------------------------------
# Default settings + starter score rules
# ---------------------------------------------------------------------------
def seed_default_settings():
    doc = frappe.get_single("AlphaX CRM Settings")
    if doc.get("score_rules"):
        return  # already configured

    defaults = {
        "scoring_enabled": 1,
        "auto_opportunity_enabled": 1,
        "auto_opportunity_threshold": 70,
        "engagement_points": 2,
        "engagement_cap": 20,
        "dedup_enabled": 1,
        "dedup_fields": "email_id,mobile_no,phone",
        "dedup_action": "Warn",
        "first_followup_days": 1,
        "stale_detection_enabled": 1,
        "stale_lead_days": 5,
        "stale_opportunity_days": 7,
        "stale_action": "Notify Owner",
        "stale_batch_size": 200,
        "default_source": "Campaign",
        "ai_enabled": 0,
        "ai_base_url": "http://localhost:11434",
        "ai_chat_path": "/api/chat",
        "ai_model": "llama3.1",
        "ai_timeout": 60,
        "ai_bilingual": 1,
        "won_status": "Converted",
        "lost_status": "Lost",
        "dashboard_default_range_days": 30,
        "pdpl_retention_enabled": 0,
        "pdpl_retention_days": 365,
        "pdpl_retention_action": "Anonymize",
        "retention_batch_size": 100,
        "data_quality_enabled": 1,
        "dq_enforce_on": "Qualify or Convert",
        "dq_block_incomplete": 1,
        "dq_skip_for_intake": 1,
        "dq_min_completeness": 0,
        "prospect_autoconvert": 1,
        "prospect_review_required": 1,
    }
    for k, v in defaults.items():
        doc.set(k, v)

    starter_rules = [
        ("Source", "Website", 15),
        ("Source", "Referral", 25),
        ("Source", "Campaign", 10),
        ("Status", "Replied", 20),
        ("Industry", "Government", 25),
    ]
    for dim, val, pts in starter_rules:
        if frappe.get_meta("AlphaX CRM Settings").has_field("score_rules"):
            doc.append("score_rules", {"dimension": dim, "match_value": val, "points": pts})

    for r in _default_dq_rules():
        if frappe.get_meta("AlphaX CRM Settings").has_field("dq_rules"):
            doc.append("dq_rules", r)

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def _default_dq_rules():
    return [
        {"field": "lead_name", "label": "Lead / Contact Name", "requirement": "Required", "validation": "Min Length", "param": "2"},
        {"field": "email_id", "label": "Email", "requirement": "Required", "validation": "Email"},
        {"field": "mobile_no", "label": "Mobile No", "requirement": "Required", "validation": "Saudi Mobile"},
        {"field": "source", "label": "Source", "requirement": "Required", "validation": "Any Value"},
        {"field": "company_name", "label": "Company", "requirement": "Recommended", "validation": "Any Value"},
        {"field": "territory", "label": "Territory", "requirement": "Recommended", "validation": "Any Value"},
        {"field": "industry", "label": "Industry", "requirement": "Recommended", "validation": "Any Value"},
    ]


def ensure_dq_rules():
    """Seed data-quality rules/defaults on existing installs (idempotent).

    Guards against being called before the schema is synced (e.g. a
    pre-model-sync patch phase): if the child doctype or the dq_rules table
    field is not yet available, it does nothing and lets a later post-sync
    pass (after_migrate) seed the rules.
    """
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    if not frappe.db.exists("DocType", "AlphaX Data Quality Rule"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    if not frappe.get_meta("AlphaX CRM Settings").has_field("dq_rules"):
        return

    doc = frappe.get_single("AlphaX CRM Settings")
    changed = False
    dq_defaults = {
        "dq_enforce_on": "Qualify or Convert",
        "dq_block_incomplete": 1,
        "dq_skip_for_intake": 1,
    }
    for f, v in dq_defaults.items():
        if not doc.get(f):
            doc.set(f, v)
            changed = True
    if not (doc.get("dq_rules") or []):
        for r in _default_dq_rules():
            doc.append("dq_rules", r)
        if doc.get("data_quality_enabled") is None:
            doc.data_quality_enabled = 1
        changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# PreLead statuses (configurable labels) + prospect defaults
# ---------------------------------------------------------------------------
def _default_prospect_statuses():
    # (label, behavior, is_active, is_default, color)
    return [
        ("New", "None", 1, 1, "Gray"),
        ("Contacted", "None", 1, 0, "Blue"),
        ("Interested", "Convert to Lead", 1, 0, "Green"),
        ("Not Interested", "Close (Not Interested)", 1, 0, "Red"),
        ("Unreachable", "Mark Unreachable", 1, 0, "Orange"),
        ("Follow-up Required", "Schedule Follow-up", 1, 0, "Yellow"),
    ]


def seed_prospect_statuses():
    if not frappe.db.exists("DocType", "AlphaX PreLead Status"):
        return
    for label, behavior, active, default, color in _default_prospect_statuses():
        if frappe.db.exists("AlphaX PreLead Status", label):
            continue
        frappe.get_doc(
            {
                "doctype": "AlphaX PreLead Status",
                "status_name": label,
                "behavior": behavior,
                "is_active": active,
                "is_default": default,
                "color": color,
            }
        ).insert(ignore_permissions=True)


def _default_lead_stage_map():
    # Confirmed 1:1 with the customer, mapping the coarse "Lead Status"
    # bucket (custom_lead_status, added on the live site via Customize
    # Form) to the "Lead Stage" shown over the native Status field.
    return [
        ("Lead", "Qualified lead"),
        ("Prospect", "Quotation"),
        ("Cold Lead", "Postponed"),
        ("Inactive Lead", "Lost with reason"),
        ("Successful", "Contract Under Signing"),
        ("Customer", "Won"),
    ]


def seed_lead_stage_map():
    """Seed AlphaX CRM Settings.lead_stage_map with the confirmed default
    Lead Status -> Lead Stage mapping, only if the table is empty (never
    overwrites a mapping the customer has since customized)."""
    settings = frappe.get_single("AlphaX CRM Settings")
    if settings.get("lead_stage_map"):
        return
    for lead_status, lead_stage in _default_lead_stage_map():
        settings.append("lead_stage_map", {"lead_status": lead_status, "lead_stage": lead_stage})
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)


def seed_job_titles():
    """Seed the standard Designation master with AlphaX's known job titles
    (from the customer's own job-title drop-list), so AlphaX PreLead's
    "Job Title" field — now a Link to Designation instead of free text —
    has a usable list from day one. Reuses Designation (already used
    site-wide for Employees) rather than a new AlphaX-specific master.
    Idempotent: only inserts titles that don't already exist.
    """
    if not frappe.db.exists("DocType", "Designation"):
        return
    for title in _default_job_titles():
        if frappe.db.exists("Designation", title):
            continue
        try:
            frappe.get_doc({"doctype": "Designation", "designation_name": title}).insert(
                ignore_permissions=True
            )
        except Exception:
            frappe.log_error(title="AlphaX CRM: job title seed", message=frappe.get_traceback())


def _default_job_titles():
    # As supplied by the customer. A few likely typos are kept verbatim
    # ("Sales manger", "partener") rather than silently corrected, since
    # they may already be in use on existing records — happy to clean these
    # up (and merge "unknown" into a blank/Other) on request.
    return [
        "Owner", "Manager", "Purchase specialist", "Customer service", "Employee",
        "Call center", "Engineering", "unknown", "Sales manger", "Co-Founder",
        "Accountant", "CEO", "Owner's assistant", "HR employee", "Strategic Consultant",
        "Chairman", "Marketer", "Account Manager", "partener", "GM assistant",
        "Administrative Officer", "CFO", "Accounting manager", "specialist",
        "Founder - CEO", "Business Consulting Specialist", "Founder - Sales Director",
        "Founder - COO", "CEO - Medical Director", "Deputy CEO", "Investor",
        "Co-Founder - Creative Director", "HR Manager", "Regional Manager",
        "Co-Founder - interior designer", "Deputy Manager", "GM",
        "CEO - Creative Director", "partener - Creative Director", "Founder - CCO",
        "Board Member", "Co-Founder - Managing Director", "Co-Founder - Chief Instructor",
        "Co-Founder - GM", "Founder - CTO",
    ]


def ensure_prospect_defaults():
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    meta = frappe.get_meta("AlphaX CRM Settings")
    if not meta.has_field("prospect_autoconvert"):
        return
    doc = frappe.get_single("AlphaX CRM Settings")
    changed = False
    for f, v in {"prospect_autoconvert": 1, "prospect_review_required": 1,
                 "prospect_convert_target": "Lead (direct)"}.items():
        if doc.get(f) is None:
            doc.set(f, v)
            changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)


def seed_smart_lead_map():
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    if not frappe.db.exists("DocType", "AlphaX Smart Lead Map"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    meta = frappe.get_meta("AlphaX CRM Settings")
    if not meta.has_field("smart_lead_map"):
        return
    doc = frappe.get_single("AlphaX CRM Settings")
    changed = False
    if doc.get("smart_lead_autocreate") is None:
        doc.smart_lead_autocreate = 1
        changed = True
    if not (doc.get("smart_lead_map") or []):
        from alphax_crm.crm.smart_lead import _default_map

        for smart_field, lead_field, transform in _default_map():
            doc.append("smart_lead_map", {
                "smart_field": smart_field, "lead_field": lead_field, "transform": transform,
            })
        changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)


def _default_monitored_statuses():
    # (status, is_default, threshold_days)
    return [
        ("Open", 1, 3),
        ("Replied", 0, 3),
        ("Lead", 0, 5),
        ("Interested", 0, 2),
        ("Quotation", 0, 4),
    ]


def ensure_activity_monitor_defaults():
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    if not frappe.db.exists("DocType", "AlphaX Monitored Status"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    meta = frappe.get_meta("AlphaX CRM Settings")
    if not meta.has_field("monitored_statuses"):
        return
    doc = frappe.get_single("AlphaX CRM Settings")
    changed = False
    for f, v in {"activity_monitor_enabled": 1, "default_idle_threshold_days": 3, "capture_status_change": 1}.items():
        if doc.get(f) is None:
            doc.set(f, v)
            changed = True
    if not (doc.get("monitored_statuses") or []):
        for status, is_default, threshold in _default_monitored_statuses():
            doc.append("monitored_statuses", {
                "status": status, "is_default": is_default,
                "idle_threshold_days": threshold, "is_active": 1,
            })
        changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)


def ensure_whatsapp_defaults():
    """Populate WhatsApp defaults on existing installs without overwriting
    anything the user has already set."""
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    doc = frappe.get_single("AlphaX CRM Settings")
    defaults = {
        "whatsapp_api_version": "v21.0",
        "whatsapp_default_source": "WhatsApp",
        "whatsapp_auto_ack": 1,
        "whatsapp_ack_mode": "Text",
        "whatsapp_ack_language": "en_US",
        "whatsapp_ack_text": (
            "\u0634\u0643\u0631\u0627\u064b \u0644\u062a\u0648\u0627\u0635\u0644\u0643 \u0645\u0639 AlphaX. "
            "\u0633\u064a\u062a\u0648\u0627\u0635\u0644 \u0645\u0639\u0643 \u0623\u062d\u062f \u0645\u0645\u062b\u0644\u064a\u0646\u0627 \u0642\u0631\u064a\u0628\u0627\u064b.\n"
            "Thank you for contacting AlphaX. One of our representatives will reach out shortly."
        ),
    }
    changed = False
    for field, value in defaults.items():
        if not doc.get(field):
            doc.set(field, value)
            changed = True
    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)


def setup_notifications():
    _ensure_notification(
        name="AlphaX New Lead Alert",
        subject="AlphaX: New lead {{ doc.lead_name }} (score {{ doc.alphax_lead_score }})",
        document_type="Lead",
        event="New",
        recipients=[{"receiver_by_document_field": "lead_owner"}],
        message="A new lead has been captured and assigned to you.\n\n"
        "Name: {{ doc.lead_name }}\nSource: {{ doc.source }}\n"
        "Score: {{ doc.alphax_lead_score }}\n\nRespond quickly — speed-to-lead drives conversion.",
    )
    _ensure_notification(
        name="AlphaX Follow-up Due",
        subject="AlphaX: Follow-up due for {{ doc.lead_name }}",
        document_type="Lead",
        event="Days Before",
        date_changed="alphax_next_contact_date",
        days_in_advance=0,
        recipients=[{"receiver_by_document_field": "lead_owner"}],
        message="Follow-up is due today for lead {{ doc.lead_name }}.",
    )
    # ---- Review process notifications ----
    _ensure_notification(
        name="AlphaX Lead Pending Review",
        subject="AlphaX: Lead {{ doc.lead_name }} is pending your review",
        document_type="Lead",
        event="Value Change",
        value_changed="alphax_review_status",
        condition="doc.alphax_review_status == 'Pending Review'",
        recipients=[{"receiver_by_role": REVIEWER_ROLE}],
        message="Lead {{ doc.lead_name }} ({{ doc.company_name }}) has been submitted for review.\n"
        "Owner: {{ doc.lead_owner }}",
    )
    _ensure_notification(
        name="AlphaX Lead Returned for Correction",
        subject="AlphaX: Lead {{ doc.lead_name }} returned for correction",
        document_type="Lead",
        event="Value Change",
        value_changed="alphax_review_status",
        condition="doc.alphax_review_status == 'Returned for Correction'",
        recipients=[{"receiver_by_document_field": "lead_owner"}],
        message="Your lead {{ doc.lead_name }} was returned for correction.\n"
        "Notes: {{ doc.alphax_review_notes }}\n\nPlease update and resubmit for review.",
    )
    _ensure_notification(
        name="AlphaX Lead Approved",
        subject="AlphaX: Lead {{ doc.lead_name }} approved",
        document_type="Lead",
        event="Value Change",
        value_changed="alphax_review_status",
        condition="doc.alphax_review_status == 'Approved'",
        recipients=[{"receiver_by_document_field": "lead_owner"}],
        message="Your lead {{ doc.lead_name }} has been approved. Continue the customer follow-up.",
    )


def _ensure_notification(name, subject, document_type, event, recipients, message,
                         date_changed=None, days_in_advance=None,
                         value_changed=None, condition=None):
    if frappe.db.exists("Notification", name):
        return
    doc = frappe.new_doc("Notification")
    doc.name = name
    doc.subject = subject
    doc.document_type = document_type
    doc.event = event
    doc.is_standard = 0
    doc.enabled = 1
    doc.channel = "Email"
    doc.message = message
    if date_changed:
        doc.date_changed = date_changed
    if days_in_advance is not None:
        doc.days_in_advance = days_in_advance
    if value_changed:
        doc.value_changed = value_changed
    if condition:
        doc.condition = condition
    for r in recipients:
        doc.append("recipients", r)
    doc.flags.ignore_permissions = True
    try:
        doc.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="AlphaX CRM: notification setup", message=frappe.get_traceback())


# ---------------------------------------------------------------------------
# Lead review workflow (per the sales process flow)
# ---------------------------------------------------------------------------
REVIEWER_ROLE = "AlphaX Lead Reviewer"


def setup_lead_workflow():
    _ensure_reviewer_role()
    _deactivate_legacy_workflow()

    name = "AlphaX Lead Review"
    if frappe.db.exists("Workflow", name):
        # Keep it active; nothing else to do.
        if not frappe.db.get_value("Workflow", name, "is_active"):
            frappe.db.set_value("Workflow", name, "is_active", 1)
        return

    # Review states drive a dedicated field so they don't collide with the
    # native Lead.status (sales stage) field.
    states = [
        ("Pending Review", REVIEWER_ROLE),
        ("Approved", "Sales User"),
        ("Returned for Correction", "Sales User"),
        ("Rejected", REVIEWER_ROLE),
    ]
    # (from_state, action, to_state, allowed_role)
    transitions = [
        ("Pending Review", "Approve", "Approved", REVIEWER_ROLE),
        ("Pending Review", "Return for Correction", "Returned for Correction", REVIEWER_ROLE),
        ("Pending Review", "Reject", "Rejected", REVIEWER_ROLE),
        ("Returned for Correction", "Resubmit", "Pending Review", "Sales User"),
    ]

    for state, _role in states:
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}).insert(
                ignore_permissions=True
            )
    for _from, action, _to, _role in transitions:
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc(
                {"doctype": "Workflow Action Master", "workflow_action_name": action}
            ).insert(ignore_permissions=True)

    wf = frappe.new_doc("Workflow")
    wf.workflow_name = name
    wf.document_type = "Lead"
    wf.is_active = 1
    wf.workflow_state_field = "alphax_review_status"
    wf.override_status = 0
    wf.send_email_alert = 0
    for state, role in states:
        wf.append("states", {"state": state, "doc_status": "0", "allow_edit": role})
    for frm, action, to, role in transitions:
        wf.append(
            "transitions",
            {"state": frm, "action": action, "next_state": to, "allowed": role, "allow_self_approval": 1},
        )
    wf.flags.ignore_permissions = True
    try:
        wf.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="AlphaX CRM: review workflow setup", message=frappe.get_traceback())


def _ensure_reviewer_role():
    if not frappe.db.exists("Role", REVIEWER_ROLE):
        frappe.get_doc({"doctype": "Role", "role_name": REVIEWER_ROLE, "desk_access": 1}).insert(
            ignore_permissions=True
        )


def _deactivate_legacy_workflow():
    """The earlier status-based workflow conflicts with the review workflow
    (one active workflow per doctype). Deactivate it if present."""
    legacy = "AlphaX Lead Workflow"
    if frappe.db.exists("Workflow", legacy) and frappe.db.get_value("Workflow", legacy, "is_active"):
        frappe.db.set_value("Workflow", legacy, "is_active", 0)


# ---------------------------------------------------------------------------
# Lead Approval -CRM  (supersedes "AlphaX Lead Review", per the customer's
# own approval process: Draft -> Pending Approval -> Approved, with a
# Returned for Correction loop). Same supersession pattern used above when
# "AlphaX Lead Review" replaced "AlphaX Lead Workflow" — deactivate the old
# one, provision the new one, idempotently.
# ---------------------------------------------------------------------------
CRM_INITIATOR_ROLE = "CRM Initiator"
LEAD_APPROVAL_WORKFLOW = "Lead Approval -CRM"


def setup_lead_approval_workflow():
    _ensure_crm_initiator_role()
    _deactivate_review_workflow()

    name = LEAD_APPROVAL_WORKFLOW
    if frappe.db.exists("Workflow", name):
        # Keep it active; nothing else to do.
        if not frappe.db.get_value("Workflow", name, "is_active"):
            frappe.db.set_value("Workflow", name, "is_active", 1)
        return

    # (state, doc_status, allow_edit_role)
    states = [
        ("Draft", "0", CRM_INITIATOR_ROLE),
        ("Pending Approval", "0", "Sales Manager"),
        ("Returned for Correction", "0", CRM_INITIATOR_ROLE),
        ("Approved", "0", CRM_INITIATOR_ROLE),
    ]
    # (from_state, action, to_state, allowed_role)
    transitions = [
        ("Draft", "Submit for Approval", "Pending Approval", CRM_INITIATOR_ROLE),
        ("Pending Approval", "Approve", "Approved", "Sales Manager"),
        ("Pending Approval", "Return for Correction", "Returned for Correction", "Sales Manager"),
        ("Returned for Correction", "Resubmit for Approval", "Pending Approval", CRM_INITIATOR_ROLE),
        ("Approved", "Reopen for Correction", "Returned for Correction", CRM_INITIATOR_ROLE),
    ]

    for state, _doc_status, _role in states:
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}).insert(
                ignore_permissions=True
            )
    for _from, action, _to, _role in transitions:
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc(
                {"doctype": "Workflow Action Master", "workflow_action_name": action}
            ).insert(ignore_permissions=True)

    wf = frappe.new_doc("Workflow")
    wf.workflow_name = name
    wf.document_type = "Lead"
    wf.is_active = 1
    # Deliberately Frappe's own default field name (not alphax_review_status,
    # which belonged to the superseded "AlphaX Lead Review" workflow) — kept
    # exactly as configured on the source site. Frappe creates this as a
    # hidden custom Select field on Lead automatically if it doesn't exist.
    wf.workflow_state_field = "workflow_state"
    wf.override_status = 0
    wf.send_email_alert = 0
    for state, doc_status, role in states:
        wf.append("states", {"state": state, "doc_status": doc_status, "allow_edit": role, "send_email": 1})
    for frm, action, to, role in transitions:
        wf.append(
            "transitions",
            {"state": frm, "action": action, "next_state": to, "allowed": role,
             "allow_self_approval": 1, "send_email_to_creator": 0},
        )
    wf.flags.ignore_permissions = True
    try:
        wf.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="AlphaX CRM: lead approval workflow setup", message=frappe.get_traceback())


def _ensure_crm_initiator_role():
    if not frappe.db.exists("Role", CRM_INITIATOR_ROLE):
        frappe.get_doc({"doctype": "Role", "role_name": CRM_INITIATOR_ROLE, "desk_access": 1}).insert(
            ignore_permissions=True
        )


def _deactivate_review_workflow():
    """"AlphaX Lead Review" is superseded by "Lead Approval -CRM". Deactivate
    it if present — one active workflow per doctype."""
    superseded = "AlphaX Lead Review"
    if frappe.db.exists("Workflow", superseded) and frappe.db.get_value("Workflow", superseded, "is_active"):
        frappe.db.set_value("Workflow", superseded, "is_active", 0)
