"""Data-quality gate for AlphaX CRM.

Declares, per field, whether it must be filled (even when it is not a mandatory
ERPNext field) and what "correct" means for it. The engine:

  * evaluates every configured rule against a Lead,
  * produces a completeness score + a human-readable report,
  * and, at the configured enforcement point (qualify / convert / save),
    blocks progression with ONE consolidated message listing every problem.

Rules live in AlphaX CRM Settings -> Data Quality (child table
`AlphaX Data Quality Rule`), so no code change is needed to tune them.
"""

import re

import frappe
from frappe import _

from alphax_crm.crm.utils import get_settings

# Statuses that count as "pushing the lead forward" (the practical "submit").
FINALIZING_STATUSES = ("Opportunity", "Converted")


# ---------------------------------------------------------------------------
# Validators  (return True if the value is acceptable)
# ---------------------------------------------------------------------------
def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


def _valid_saudi_mobile(v, p=None):
    d = _digits(v)
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("966"):
        d = d[3:]
    if d.startswith("0"):
        d = d[1:]
    return bool(re.match(r"^5\d{8}$", d))


def normalize_saudi_mobile(v):
    """Return canonical +9665XXXXXXXX for a Saudi mobile, else the original."""
    if not v:
        return v
    d = _digits(v)
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("966"):
        d = d[3:]
    if d.startswith("0"):
        d = d[1:]
    if re.match(r"^5\d{8}$", d):
        return "+966" + d
    return v


VALIDATORS = {
    "Any Value": lambda v, p: bool(str(v).strip()),
    "Email": lambda v, p: bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(v).strip())),
    "Saudi Mobile": _valid_saudi_mobile,
    "Phone": lambda v, p: bool(re.match(r"^\+?\d{7,15}$", re.sub(r"[\s\-()]", "", str(v).strip()))),
    "Number": lambda v, p: _is_number(v),
    "Positive Number": lambda v, p: _is_number(v) and float(v) > 0,
    "VAT Number (KSA)": lambda v, p: bool(re.match(r"^3\d{13}3$", _digits(v))),
    "National ID / Iqama": lambda v, p: bool(re.match(r"^[12]\d{9}$", _digits(v))),
    "CR Number": lambda v, p: bool(re.match(r"^\d{10}$", _digits(v))),
    "URL": lambda v, p: bool(re.match(r"^https?://[^\s]+\.[^\s]+$", str(v).strip(), re.I)),
    "Regex": lambda v, p: bool(re.search(p or ".*", str(v))),
    "Min Length": lambda v, p: len(str(v).strip()) >= _to_int(p, 1),
}

# Default message per validation type (used when a rule sets no custom message).
_DEFAULT_MSG = {
    "Email": "is not a valid email address",
    "Saudi Mobile": "is not a valid Saudi mobile number",
    "Phone": "is not a valid phone number",
    "Number": "must be a number",
    "Positive Number": "must be a number greater than zero",
    "VAT Number (KSA)": "is not a valid 15-digit ZATCA VAT number",
    "National ID / Iqama": "is not a valid National ID / Iqama (10 digits)",
    "CR Number": "is not a valid Commercial Registration number (10 digits)",
    "URL": "must be a valid URL (starting with http:// or https://)",
    "Regex": "does not match the required format",
    "Min Length": "is too short",
}


def _is_number(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(doc, settings=None):
    """Return a structured quality report for `doc` without side effects."""
    settings = settings or get_settings()
    meta = frappe.get_meta(doc.doctype)

    issues = []          # blocking-eligible (Required)
    warnings = []        # advisory (Recommended)
    required_total = 0
    required_ok = 0

    for rule in settings.get("dq_rules") or []:
        field = (rule.field or "").strip()
        if not field or not meta.has_field(field):
            continue
        label = rule.label or (meta.get_label(field) if meta.has_field(field) else field)
        value = doc.get(field)
        is_required = (rule.requirement or "Required") == "Required"
        if is_required:
            required_total += 1

        # 1) presence
        if _is_empty(value):
            entry = {"field": field, "label": label, "reason": _("is required and is empty"), "kind": "missing"}
            (issues if is_required else warnings).append(entry)
            continue

        # 2) correctness
        validator = VALIDATORS.get(rule.validation or "Any Value", VALIDATORS["Any Value"])
        try:
            ok = validator(value, rule.param)
        except Exception:
            ok = False
        if not ok:
            reason = rule.message or _(_DEFAULT_MSG.get(rule.validation, "is invalid"))
            entry = {"field": field, "label": label, "reason": reason, "kind": "invalid"}
            (issues if is_required else warnings).append(entry)
        elif is_required:
            required_ok += 1

    score = 100 if required_total == 0 else round(required_ok * 100.0 / required_total)
    report = _format_report(issues, warnings, score)
    return {
        "score": score,
        "required_total": required_total,
        "required_ok": required_ok,
        "issues": issues,
        "warnings": warnings,
        "report": report,
    }


def _format_report(issues, warnings, score):
    lines = [f"Completeness: {score}%"]
    if issues:
        lines.append("Must fix:")
        lines += [f"  - {i['label']} {i['reason']}" for i in issues]
    if warnings:
        lines.append("Recommended:")
        lines += [f"  - {w['label']} {w['reason']}" for w in warnings]
    if not issues and not warnings:
        lines.append("All configured checks passed.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Enforcement  (called from crm.lead.validate)
# ---------------------------------------------------------------------------
def enforce(doc, settings=None):
    settings = settings or get_settings()
    if not settings.data_quality_enabled:
        return

    result = evaluate(doc, settings)

    # Always surface the score/report on the record.
    if frappe.get_meta(doc.doctype).has_field("alphax_dq_score"):
        doc.alphax_dq_score = result["score"]
    if frappe.get_meta(doc.doctype).has_field("alphax_dq_report"):
        doc.alphax_dq_report = result["report"]

    trigger = _trigger_for(doc)
    if not _should_gate(doc, trigger, settings):
        return

    issues = result["issues"]
    min_completeness = settings.dq_min_completeness or 0
    below_threshold = min_completeness and result["score"] < min_completeness

    if issues or below_threshold:
        if settings.dq_block_incomplete:
            frappe.throw(_build_block_message(result, trigger, min_completeness), title=_("Lead Data Incomplete"))
        else:
            frappe.msgprint(_build_block_message(result, trigger, min_completeness),
                            title=_("Lead Data Quality"), indicator="orange")
    elif result["warnings"]:
        frappe.msgprint(result["report"], title=_("Recommended fields incomplete"), indicator="yellow")


def _trigger_for(doc):
    """Classify this save as a forward move (finalizing) or a plain save."""
    new_status = doc.get("status")
    if new_status not in FINALIZING_STATUSES:
        return "save"
    before = doc.get_doc_before_save() if not doc.is_new() else None
    if before is None or before.get("status") != new_status:
        return "qualify"
    return "save"


def _should_gate(doc, trigger, settings):
    # Never gate leads captured by intake/WhatsApp on their creating save.
    if settings.dq_skip_for_intake and getattr(doc.flags, "alphax_skip_dq", False):
        return False

    mode = settings.dq_enforce_on or "Qualify or Convert"
    if mode == "Both":
        return True
    if mode == "On Save":
        return True
    # "Qualify or Convert"
    return trigger == "qualify"


def _build_block_message(result, trigger, min_completeness):
    action = "qualify or convert this lead" if trigger == "qualify" else "save this lead"
    parts = [_("Please complete the required data before you {0}.").format(action), ""]
    for i in result["issues"]:
        parts.append("• <b>{0}</b> {1}".format(frappe.utils.escape_html(i["label"]), frappe.utils.escape_html(i["reason"])))
    if min_completeness and result["score"] < min_completeness:
        parts.append("")
        parts.append(_("Completeness is {0}%, but {1}% is required.").format(result["score"], min_completeness))
    if result["warnings"]:
        parts.append("")
        parts.append(_("Recommended (not blocking):"))
        for w in result["warnings"]:
            parts.append("• {0} {1}".format(frappe.utils.escape_html(w["label"]), frappe.utils.escape_html(w["reason"])))
    return "<br>".join(parts)


# ---------------------------------------------------------------------------
# Whitelisted live check  (used by the client script for real-time feedback)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def check(doc):
    """Evaluate an in-progress Lead (dict from the form) and return the report."""
    import json

    if isinstance(doc, str):
        doc = json.loads(doc)
    lead = frappe.get_doc(doc)
    result = evaluate(lead)
    # Trim to what the client needs.
    return {
        "score": result["score"],
        "issues": result["issues"],
        "warnings": result["warnings"],
        "required_total": result["required_total"],
        "required_ok": result["required_ok"],
    }
