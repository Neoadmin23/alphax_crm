"""WF-01 Stage Progression Control + WF-06 Closure Controls for AlphaX CRM.

Both are enforced from crm.lead.validate(), AFTER Lead Status -> Lead Stage
automation (_sync_stage_from_status) has already run — that automation can
itself change `status`, and it's the final value after that step which has
to obey the approved flow / closure requirements, whatever caused it to
change (a direct edit of Lead Stage, or an indirect one via Lead Status).

Both rules are admin-configurable (AlphaX CRM Settings), not hardcoded:
  - WF-01's "approved flow" is whatever (From Stage -> To Stage) pairs are
    listed in Stage Transitions. The spec's own diagram is only the seeded
    starting point (see setup/install.py's _default_stage_transitions) —
    add, remove or rename stages there and this follows, no code change.
  - WF-06's Won/Lost field requirements reference the *value* to check for
    (won_stage_value, contract_signed_value, lost_stage_values) as settings,
    not literal strings, so renaming a stage or the "signed" label doesn't
    require a patch.
"""

import frappe
from frappe import _

from alphax_crm.crm.utils import get_settings

_STAGE_FIELD = "status"


# ---------------------------------------------------------------------------
# WF-01 — Stage Progression Control
# ---------------------------------------------------------------------------
def enforce_stage_flow(doc, settings=None):
    """Lead Stage cannot skip a step in the approved flow.

    An empty Stage Transitions table means "not configured yet" and the
    guard is skipped entirely, rather than blocking every save — the same
    fail-open posture as the Data Quality Gate before its first rule is
    added.
    """
    settings = settings or get_settings()
    if not settings.get("stage_flow_enabled", 1):
        return
    if doc.is_new() or not doc.meta.has_field(_STAGE_FIELD):
        return

    transitions = settings.get("stage_transitions") or []
    if not transitions:
        return

    before = doc.get_doc_before_save()
    if not before:
        return
    old_stage = (before.get(_STAGE_FIELD) or "").strip()
    new_stage = (doc.get(_STAGE_FIELD) or "").strip()
    if not old_stage or not new_stage or old_stage.lower() == new_stage.lower():
        return

    bypass_roles = {r.strip() for r in (settings.get("stage_flow_bypass_roles") or "").split(",") if r.strip()}
    if bypass_roles & set(frappe.get_roles()):
        return

    allowed = any(
        (t.from_stage or "").strip().lower() == old_stage.lower()
        and (t.to_stage or "").strip().lower() == new_stage.lower()
        for t in transitions
    )
    if not allowed:
        frappe.throw(
            _(
                'Lead Stage cannot move from "{0}" directly to "{1}" — that skips a step in the '
                "approved workflow. Move it through the stages in order, or ask a manager to make "
                "this change."
            ).format(old_stage, new_stage),
            title=_("Stage Cannot Be Skipped"),
        )


# ---------------------------------------------------------------------------
# WF-06 — Closure Controls
# ---------------------------------------------------------------------------
def enforce_closure_controls(doc, settings=None):
    settings = settings or get_settings()
    if not settings.get("closure_controls_enabled", 1):
        return
    if not doc.meta.has_field(_STAGE_FIELD):
        return

    stage = (doc.get(_STAGE_FIELD) or "").strip()
    if not stage:
        return

    won_value = (settings.get("won_stage_value") or "Won").strip()
    lost_values = {s.strip().lower() for s in (settings.get("lost_stage_values") or "").split(",") if s.strip()}

    if stage.lower() == won_value.lower():
        _enforce_won(doc, settings)
    elif stage.lower() in lost_values:
        _enforce_lost(doc, settings)


def _enforce_won(doc, settings):
    missing = []
    contract_signed_value = (settings.get("contract_signed_value") or "Signed").strip()
    if doc.meta.has_field("alphax_contract_status"):
        if (doc.get("alphax_contract_status") or "").strip().lower() != contract_signed_value.lower():
            missing.append(_('Contract must be "{0}"').format(contract_signed_value))
    if doc.meta.has_field("alphax_won_lost_date") and not doc.get("alphax_won_lost_date"):
        missing.append(_("Won/Lost Date is required"))
    if settings.get("require_customer_for_won", 1) and doc.name:
        if not frappe.db.exists("Customer", {"lead_name": doc.name}):
            missing.append(_('A Customer must be created from this Lead first (use "Create > Customer")'))

    if missing:
        frappe.throw(
            _('This Lead cannot be marked "{0}" yet:').format(settings.get("won_stage_value") or "Won")
            + "<br>"
            + "<br>".join(f"• {frappe.utils.escape_html(m)}" for m in missing),
            title=_("Closure Requirements Not Met"),
        )


def _enforce_lost(doc, settings):
    missing = []
    if doc.meta.has_field("alphax_lost_reason") and not doc.get("alphax_lost_reason"):
        missing.append(_("Lost Reason is required"))
    if doc.meta.has_field("alphax_lost_detailed_reason") and not doc.get("alphax_lost_detailed_reason"):
        missing.append(_("Detailed Reason is required"))
    if doc.meta.has_field("alphax_won_lost_date") and not doc.get("alphax_won_lost_date"):
        missing.append(_("Won/Lost Date is required"))

    if missing:
        frappe.throw(
            _("This Lead cannot be closed as Lost yet:")
            + "<br>"
            + "<br>".join(f"• {frappe.utils.escape_html(m)}" for m in missing),
            title=_("Closure Requirements Not Met"),
        )
