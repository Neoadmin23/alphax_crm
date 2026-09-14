"""Lead lifecycle automation for AlphaX CRM.

Wired via hooks.doc_events on the ERPNext `Lead` doctype:
    before_insert -> de-duplication + consent stamping
    validate      -> recompute lead score (config-driven)
    after_insert  -> next-contact seeding, AI classification (enqueued)
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_days, nowdate

from alphax_crm.crm.utils import get_settings, log_error


# ---------------------------------------------------------------------------
# before_insert
# ---------------------------------------------------------------------------
def before_insert(doc, method=None):
    settings = get_settings()
    _check_duplicate(doc, settings)
    _stamp_consent(doc)


def _check_duplicate(doc, settings):
    if not settings.dedup_enabled:
        return

    fields = [f.strip() for f in (settings.dedup_fields or "").split(",") if f.strip()]
    if not fields:
        fields = ["email_id", "mobile_no", "phone"]

    or_filters = {}
    for f in fields:
        val = doc.get(f)
        if val:
            or_filters[f] = val

    if not or_filters:
        return

    existing = frappe.db.get_value(
        "Lead",
        or_filters,
        ["name", "lead_name"],
        as_dict=True,
        order_by="creation desc",
    )
    # get_value with a dict uses AND; emulate OR by probing each field
    if not existing:
        for f, val in or_filters.items():
            existing = frappe.db.get_value(
                "Lead", {f: val}, ["name", "lead_name"], as_dict=True
            )
            if existing:
                break

    if existing:
        msg = _("A lead with the same contact already exists: {0} ({1}).").format(
            existing.lead_name or "", existing.name
        )
        if settings.dedup_action == "Block":
            frappe.throw(msg, title=_("Duplicate Lead"))
        else:
            doc.add_comment("Comment", text=f"AlphaX: possible duplicate of {existing.name}")


def _stamp_consent(doc):
    """Default lawful basis + consent timestamp when a consent flag is set."""
    if doc.get("alphax_consent_given") and not doc.get("alphax_consent_datetime"):
        doc.alphax_consent_datetime = now_datetime()
    if not doc.get("alphax_lawful_basis"):
        doc.alphax_lawful_basis = "Legitimate Interest"


# ---------------------------------------------------------------------------
# validate -> scoring
# ---------------------------------------------------------------------------
def validate(doc, method=None):
    settings = get_settings()
    if settings.scoring_enabled:
        score, breakdown = compute_score(doc, settings)
        doc.alphax_lead_score = score
        doc.alphax_score_breakdown = breakdown

    # Data-quality completeness + correctness gate.
    try:
        from alphax_crm.crm import data_quality

        data_quality.enforce(doc, settings)
    except frappe.ValidationError:
        raise
    except Exception:
        log_error("data quality enforce")


def compute_score(doc, settings=None):
    """Config-driven additive scoring from AlphaX Lead Score Rule rows.

    Each rule = (dimension, match_value, points). The lead's field that maps
    to the dimension is compared (case-insensitive) to match_value; on match,
    points are added. Returns (int_score, human_readable_breakdown).
    """
    settings = settings or get_settings()
    dimension_field = {
        "Source": "source",
        "Industry": "industry",
        "Status": "status",
        "Territory": "territory",
        "Request Type": "request_type",
    }

    total = 0
    lines = []
    for rule in settings.get("score_rules") or []:
        field = dimension_field.get(rule.dimension)
        if not field:
            continue
        actual = (doc.get(field) or "").strip().lower()
        target = (rule.match_value or "").strip().lower()
        if actual and actual == target:
            total += int(rule.points or 0)
            lines.append(f"{rule.dimension}={rule.match_value}: +{rule.points}")

    # Engagement signal: prior communications lift the score.
    if doc.name:
        comms = frappe.db.count(
            "Communication",
            {"reference_doctype": "Lead", "reference_name": doc.name},
        )
        if comms:
            bump = min(comms * (settings.engagement_points or 2), settings.engagement_cap or 20)
            total += bump
            lines.append(f"Engagement x{comms}: +{bump}")

    total = max(0, min(total, 100))
    breakdown = "\n".join(lines) if lines else "No scoring rules matched."
    return total, breakdown


# ---------------------------------------------------------------------------
# after_insert
# ---------------------------------------------------------------------------
def after_insert(doc, method=None):
    settings = get_settings()

    # Seed a next-contact date so follow-up SLAs have something to track.
    if not doc.get("alphax_next_contact_date"):
        days = settings.first_followup_days or 1
        frappe.db.set_value(
            "Lead", doc.name, "alphax_next_contact_date", add_days(nowdate(), days),
            update_modified=False,
        )

    # Auto-promote hot leads to an Opportunity.
    try:
        if (
            settings.scoring_enabled
            and settings.auto_opportunity_enabled
            and (doc.get("alphax_lead_score") or 0) >= (settings.auto_opportunity_threshold or 70)
        ):
            _create_opportunity(doc)
    except Exception:
        log_error("auto-opportunity")

    # AI classification / first-reply draft -> background.
    # Smart Import sets flags.alphax_skip_ai per-batch unless the user opts in
    # (bulk imports would otherwise queue one AI job per row).
    if doc.flags.get("alphax_skip_ai"):
        return
    if settings.ai_enabled and (settings.ai_classify_leads or settings.ai_draft_reply):
        frappe.enqueue(
            "alphax_crm.api.ai.process_lead",
            queue="long",
            lead=doc.name,
            enqueue_after_commit=True,
        )


def _create_opportunity(doc):
    if frappe.db.exists("Opportunity", {"party_name": doc.name, "opportunity_from": "Lead"}):
        return
    opp = frappe.new_doc("Opportunity")
    opp.opportunity_from = "Lead"
    opp.party_name = doc.name
    opp.source = doc.get("source")
    opp.contact_email = doc.get("email_id")
    opp.contact_mobile = doc.get("mobile_no")
    if doc.get("company"):
        opp.company = doc.company
    opp.flags.ignore_permissions = True
    opp.insert(ignore_permissions=True)
    doc.add_comment("Comment", text=f"AlphaX: auto-created Opportunity {opp.name} (score {doc.alphax_lead_score}).")


# ---------------------------------------------------------------------------
# on_update -> capture status / review-status changes as activity
# ---------------------------------------------------------------------------
def on_update(doc, method=None):
    settings = get_settings()
    if not settings.get("activity_monitor_enabled", 1) or not settings.get("capture_status_change", 1):
        return
    before = doc.get_doc_before_save()
    if not before:
        return
    from alphax_crm.crm.activity import record_activity

    if before.get("status") != doc.get("status") and doc.get("status"):
        record_activity("Lead", doc.name, f"Status \u2192 {doc.status}",
                        frappe.session.user, f"Status changed to {doc.status}")
    elif (before.get("alphax_review_status") != doc.get("alphax_review_status")
          and doc.get("alphax_review_status")):
        record_activity("Lead", doc.name, f"Review \u2192 {doc.alphax_review_status}",
                        frappe.session.user,
                        doc.get("alphax_review_notes") or f"Review: {doc.alphax_review_status}")
