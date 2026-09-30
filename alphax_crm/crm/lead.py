"""Lead lifecycle automation for AlphaX CRM.

Wired via hooks.doc_events on the ERPNext `Lead` doctype:
    before_insert -> de-duplication + consent stamping
    validate      -> recompute lead score (config-driven)
    after_insert  -> next-contact seeding, AI classification (enqueued)
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_days, nowdate

from alphax_crm.crm.utils import ensure_select_option, get_settings, log_error, active_lead_workflow_field


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

    # Lead Status -> Lead Stage automation.
    _sync_stage_from_status(doc, settings)

    # WF-01 stage progression control + WF-06 closure controls — run AFTER
    # the automation above, since that may itself change Lead Stage, and
    # it's the resulting value that has to obey the approved flow / closure
    # requirements, whatever caused it to change.
    from alphax_crm.crm import stage_flow

    stage_flow.enforce_stage_flow(doc, settings)
    stage_flow.enforce_closure_controls(doc, settings)


# ---------------------------------------------------------------------------
# Lead Status -> Lead Stage automation
# ---------------------------------------------------------------------------
# "Lead Status" (custom_lead_status, added on the live site via Customize
# Form) is the coarse human-facing bucket a salesperson picks (Lead /
# Prospect / Cold Lead / Inactive Lead / Successful / Customer). "Lead
# Stage" is the label shown over the *native* `status` field, which is what
# actually drives ERPNext pipeline logic (kanban, reports, the Data Quality
# Gate). The two used to drift out of sync because nothing kept them
# aligned; this keeps Lead Stage following Lead Status automatically,
# per a configurable mapping so it isn't hardcoded to one site's wording.
_STAGE_STATUS_FIELD = "custom_lead_status"
_STAGE_TARGET_FIELD = "status"


def _sync_stage_from_status(doc, settings):
    if not settings.get("auto_set_stage_from_status", 1):
        return
    meta = frappe.get_meta(doc.doctype)
    if not meta.has_field(_STAGE_STATUS_FIELD) or not meta.has_field(_STAGE_TARGET_FIELD):
        return

    lead_status = doc.get(_STAGE_STATUS_FIELD)
    if not lead_status:
        return

    before = doc.get_doc_before_save() if not doc.is_new() else None
    previous_status = before.get(_STAGE_STATUS_FIELD) if before else None
    if before and previous_status == lead_status:
        return  # Lead Status did not change on this save; leave Lead Stage alone.

    mapped_stage = _lead_stage_for(lead_status, settings)
    if not mapped_stage:
        return  # no mapping configured for this Lead Status; don't guess.
    if mapped_stage == doc.get(_STAGE_TARGET_FIELD):
        return

    # Belt-and-suspenders: this should already be a no-op by the time we get
    # here, since sync_lead_stage_options() runs on install/migrate and
    # whenever AlphaX CRM Settings is saved — but checking again, right
    # before actually writing the value, means a save can never be blocked
    # by a mapping row that was only just added (e.g. mid-session, before
    # the next migrate) and guards against the two ever drifting apart.
    ensure_select_option(doc.doctype, _STAGE_TARGET_FIELD, mapped_stage)

    previous_stage = doc.get(_STAGE_TARGET_FIELD)
    doc.status = mapped_stage
    doc.flags.alphax_stage_auto_set = True

    if doc.name and settings.get("track_stage_durations", 1):
        from alphax_crm.crm.activity import record_transition

        record_transition(doc.doctype, doc.name, "Lead Status", previous_status, lead_status)
        record_transition(doc.doctype, doc.name, "Lead Stage", previous_stage, mapped_stage)


def sync_lead_stage_options(settings=None):
    """Make sure every Lead Stage value configured in Lead Status -> Lead
    Stage Mapping is a valid option on Lead's native `status` field — see
    ensure_select_option()'s docstring for why this is needed at all.
    Idempotent and cheap once everything already matches; called on
    install/migrate (setup/install.py) and whenever AlphaX CRM Settings is
    saved (see AlphaXCRMSettings.on_update), so a newly typed mapping value
    is usable immediately, not just after the next deploy.
    """
    settings = settings or get_settings()
    meta = frappe.get_meta("Lead")
    if not meta.has_field(_STAGE_TARGET_FIELD):
        return
    changed = False
    for row in settings.get("lead_stage_map") or []:
        if ensure_select_option("Lead", _STAGE_TARGET_FIELD, row.lead_stage, clear_cache=False):
            changed = True
    if changed:
        frappe.clear_cache(doctype="Lead")


def _lead_stage_for(lead_status, settings=None):
    """Look up the configured Lead Stage for a given Lead Status value."""
    settings = settings or get_settings()
    for row in settings.get("lead_stage_map") or []:
        if (row.lead_status or "").strip().lower() == (lead_status or "").strip().lower():
            return row.lead_stage
    return None


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
    before = doc.get_doc_before_save()

    _log_workflow_transition(doc, before, settings)
    _seed_postponed_followup(doc, before, settings)

    if not settings.get("activity_monitor_enabled", 1) or not settings.get("capture_status_change", 1):
        return
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


def _seed_postponed_followup(doc, before, settings):
    """WF-05: a Postponed Lead needs a Next Contact Date, and nothing
    prompted for one before — the moment a Lead enters the configured
    "Postponed" stage, create a blank AlphaX Follow-up record (no next
    follow-up date set yet) so it shows up wherever open follow-ups are
    tracked, instead of the requirement only existing on paper.
    """
    if not before or doc.is_new():
        return
    if not frappe.db.exists("DocType", "AlphaX Follow-up"):
        return
    postponed = (settings.get("postponed_stage_value") or "Postponed").strip().lower()
    if not postponed:
        return
    old_stage = (before.get("status") or "").strip().lower()
    new_stage = (doc.get("status") or "").strip().lower()
    if new_stage != postponed or old_stage == postponed:
        return
    if frappe.db.exists("AlphaX Follow-up", {
        "reference_doctype": "Lead", "reference_name": doc.name, "next_follow_up_date": ["is", "not set"],
    }):
        return  # a blank one is already pending — don't pile up duplicates.
    try:
        frappe.get_doc({
            "doctype": "AlphaX Follow-up",
            "reference_doctype": "Lead",
            "reference_name": doc.name,
            "follow_up_datetime": now_datetime(),
            "agent": doc.get("lead_owner") or frappe.session.user,
            "channel": "Other",
            "summary": "AlphaX: Lead postponed — set a Next Follow-up Date.",
            "next_action": "Set next follow-up date",
        }).insert(ignore_permissions=True)
    except Exception:
        log_error("seed postponed follow-up")


def _log_workflow_transition(doc, before, settings):
    """Day-gap tracking for the approval workflow state, independent of the
    Lead Status -> Lead Stage automation logged in validate(). Only logs
    changes that weren't already logged there (native `status`/Lead Stage is
    handled in _sync_stage_from_status to avoid double-counting)."""
    if not before or not settings.get("track_stage_durations", 1):
        return
    field = active_lead_workflow_field()
    if not field or not doc.meta.has_field(field):
        return
    old_val = before.get(field)
    new_val = doc.get(field)
    if old_val == new_val or not new_val:
        return
    from alphax_crm.crm.activity import record_transition

    record_transition(doc.doctype, doc.name, "Workflow State", old_val, new_val)
