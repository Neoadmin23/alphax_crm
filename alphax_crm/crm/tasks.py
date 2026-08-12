"""Scheduled jobs for AlphaX CRM Automation.

Registered in hooks.scheduler_events (daily_long):
    scan_stale_records  -> follow-up SLA enforcement (notify / reassign)
    run_pdpl_retention  -> anonymize or delete stale leads per retention policy
"""

import frappe
from frappe.utils import add_days, nowdate, getdate, date_diff, cint

from alphax_crm.crm.utils import get_settings, log_error


# ---------------------------------------------------------------------------
# Stale-deal detection
# ---------------------------------------------------------------------------
def scan_stale_records():
    settings = get_settings()
    if not settings.stale_detection_enabled:
        return
    try:
        _scan("Lead", settings.stale_lead_days or 5, settings)
    except Exception:
        log_error("stale scan: Lead")
    try:
        _scan("Opportunity", settings.stale_opportunity_days or 7, settings)
    except Exception:
        log_error("stale scan: Opportunity")


def _scan(doctype, days, settings):
    cutoff = add_days(nowdate(), -int(days))
    open_status = ["Open", "Replied"] if doctype == "Lead" else ["Open", "Quotation", "Replied"]

    rows = frappe.get_all(
        doctype,
        filters={
            "status": ["in", open_status],
            "modified": ["<", cutoff],
        },
        fields=["name", "owner", "modified"],
        limit_page_length=settings.stale_batch_size or 200,
    )

    action = settings.stale_action or "Notify Owner"
    for row in rows:
        assignee = _current_assignee(doctype, row.name) or row.owner
        if action in ("Notify Owner", "Both"):
            _notify_stale(doctype, row.name, assignee, days)
        if action in ("Reassign", "Both"):
            _reassign(doctype, row.name, settings)


def _current_assignee(doctype, name):
    todos = frappe.get_all(
        "ToDo",
        filters={"reference_type": doctype, "reference_name": name, "status": "Open"},
        fields=["allocated_to"],
        order_by="creation desc",
        limit=1,
    )
    return todos[0].allocated_to if todos else None


def _notify_stale(doctype, name, user, days):
    if not user:
        return
    frappe.get_doc(
        {
            "doctype": "Notification Log",
            "subject": f"AlphaX: {doctype} {name} has had no activity for {days}+ days",
            "for_user": user,
            "type": "Alert",
            "document_type": doctype,
            "document_name": name,
            "from_user": "Administrator",
        }
    ).insert(ignore_permissions=True)


def _reassign(doctype, name, settings):
    pool = [u.strip() for u in (settings.reassign_pool or "").split(",") if u.strip()]
    if not pool:
        return
    # Simple least-loaded pick across the pool.
    counts = {}
    for u in pool:
        counts[u] = frappe.db.count(
            "ToDo", {"allocated_to": u, "status": "Open"}
        )
    target = min(counts, key=counts.get)

    # Clear existing open assignments, then assign to target.
    from frappe.desk.form.assign_to import add as assign_add, clear as assign_clear

    try:
        assign_clear(doctype, name)
        assign_add(
            {
                "assign_to": [target],
                "doctype": doctype,
                "name": name,
                "description": "AlphaX: reassigned (stale follow-up).",
            }
        )
        frappe.get_doc(doctype, name).add_comment(
            "Comment", text=f"AlphaX: reassigned to {target} after inactivity."
        )
    except Exception:
        log_error("reassign")


# ---------------------------------------------------------------------------
# PDPL retention
# ---------------------------------------------------------------------------
def run_pdpl_retention():
    settings = get_settings()
    if not settings.pdpl_retention_enabled:
        return

    days = int(settings.pdpl_retention_days or 365)
    cutoff = add_days(nowdate(), -days)
    action = settings.pdpl_retention_action or "Anonymize"

    # Only act on leads that never converted and have no lawful basis to retain.
    leads = frappe.get_all(
        "Lead",
        filters={
            "status": ["in", ["Lead", "Open", "Do Not Contact", "Junk", "Quotation"]],
            "modified": ["<", cutoff],
        },
        fields=["name", "alphax_lawful_basis"],
        limit_page_length=settings.retention_batch_size or 100,
    )

    for lead in leads:
        # Contract / Legal Obligation bases are retained.
        if (lead.alphax_lawful_basis or "") in ("Contract", "Legal Obligation"):
            continue
        try:
            if action == "Delete":
                frappe.delete_doc("Lead", lead.name, ignore_permissions=True, force=True)
            else:
                _anonymize_lead(lead.name)
        except Exception:
            log_error(f"retention {action}: {lead.name}")

    frappe.db.commit()


def _anonymize_lead(name):
    redactions = {
        "lead_name": f"Redacted-{name}",
        "first_name": "Redacted",
        "last_name": "",
        "email_id": "",
        "mobile_no": "",
        "phone": "",
        "whatsapp_no": "",
        "company_name": "Redacted",
        "alphax_score_breakdown": "Redacted under PDPL retention policy.",
    }
    meta = frappe.get_meta("Lead")
    payload = {k: v for k, v in redactions.items() if meta.has_field(k)}
    payload["alphax_pdpl_anonymized"] = 1
    frappe.db.set_value("Lead", name, payload, update_modified=True)
    frappe.get_doc("Lead", name).add_comment(
        "Comment", text="AlphaX: anonymized under PDPL retention policy."
    )


# ---------------------------------------------------------------------------
# Activity monitor — refresh idle days for monitored leads
# ---------------------------------------------------------------------------
def get_monitored_statuses(settings=None):
    """Return {status: threshold_days} for active monitored statuses."""
    settings = settings or get_settings()
    out = {}
    default_threshold = settings.get("default_idle_threshold_days") or 3
    for row in settings.get("monitored_statuses") or []:
        if not row.is_active:
            continue
        out[row.status] = int(row.idle_threshold_days or default_threshold)
    return out


@frappe.whitelist()
def get_default_monitored_status(settings=None):
    settings = settings or get_settings()
    for row in settings.get("monitored_statuses") or []:
        if row.is_default and row.is_active:
            return row.status
    rows = [r.status for r in (settings.get("monitored_statuses") or []) if r.is_active]
    return rows[0] if rows else "Open"


def refresh_activity_monitor():
    settings = get_settings()
    if not settings.get("activity_monitor_enabled", 1):
        return
    today = getdate(nowdate())
    for target in ("Lead", "Opportunity", "AlphaX Prospect"):
        try:
            records = get_open_records(target, settings, fields=["name", "creation", "alphax_last_activity"])
        except Exception:
            log_error(f"idle refresh fetch: {target}")
            continue
        for r in records:
            anchor = r.get("alphax_last_activity") or r.get("creation")
            try:
                idle = max(date_diff(today, getdate(anchor)), 0)
            except Exception:
                idle = 0
            frappe.db.set_value(target, r["name"], "alphax_idle_days", idle, update_modified=False)
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Shared helpers (used by the owner-summary + activity reports)
# ---------------------------------------------------------------------------
OWNER_FIELDS = ("lead_owner", "opportunity_owner", "prospect_owner")


def get_owner_field(doctype):
    meta = frappe.get_meta(doctype)
    for f in OWNER_FIELDS:
        if meta.has_field(f):
            return f
    return "owner"


def get_open_filters(target, settings):
    """Filters selecting the 'open / still-working' records per doctype."""
    if target == "Lead":
        statuses = list(get_monitored_statuses(settings).keys())
        return {"status": ["in", statuses]} if statuses else {}
    if target == "Opportunity":
        return {"status": ["in", ["Open", "Replied", "Quotation"]]}
    if target == "AlphaX Prospect":
        return {"converted": 0}
    return {}


def get_open_records(target, settings, fields=None, extra_filters=None):
    fields = fields or ["name", "status", "creation", "alphax_last_activity"]
    if not frappe.db.exists("DocType", target):
        return []
    meta = frappe.get_meta(target)
    std = ("name", "creation", "owner", "modified", "docstatus")
    fields = [f for f in fields if f in std or meta.has_field(f)]
    conditions = get_open_filters(target, settings)
    if extra_filters:
        for k, v in extra_filters.items():
            if v and meta.has_field(k):
                conditions[k] = v
    return frappe.get_all(target, filters=conditions, fields=fields, limit_page_length=0)


def threshold_for(target, status, settings, thresholds=None):
    default_threshold = settings.get("default_idle_threshold_days") or 3
    if target == "Lead":
        thresholds = thresholds if thresholds is not None else get_monitored_statuses(settings)
        return thresholds.get(status, default_threshold)
    return default_threshold


# ---------------------------------------------------------------------------
# Backfill last-activity from existing Communications / Comments (one-time)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def backfill_activity_monitor(doctypes=None, limit=0):
    """Seed last-activity fields from the newest existing Communication/Comment
    on each record. Safe to re-run; only fills records with no activity yet."""
    if isinstance(doctypes, str):
        import json
        try:
            doctypes = json.loads(doctypes)
        except Exception:
            doctypes = [doctypes]
    targets = doctypes or ["Lead", "Opportunity", "AlphaX Prospect"]
    today = getdate(nowdate())
    total = 0
    for target in targets:
        if not frappe.db.exists("DocType", target):
            continue
        meta = frappe.get_meta(target)
        if not meta.has_field("alphax_last_activity"):
            continue
        names = frappe.get_all(target, filters={"alphax_last_activity": ["is", "not set"]},
                               pluck="name", limit_page_length=cint(limit) or 0)
        for name in names:
            latest = _latest_activity(target, name)
            payload = {}
            if latest:
                when, by, atype, summary = latest
                payload["alphax_last_activity"] = when
                if meta.has_field("alphax_last_activity_by"):
                    payload["alphax_last_activity_by"] = by
                if meta.has_field("alphax_last_activity_type"):
                    payload["alphax_last_activity_type"] = atype
                if meta.has_field("alphax_last_activity_summary"):
                    payload["alphax_last_activity_summary"] = summary
                anchor = when
            else:
                anchor = frappe.db.get_value(target, name, "creation")
            if meta.has_field("alphax_idle_days"):
                try:
                    payload["alphax_idle_days"] = max(date_diff(today, getdate(anchor)), 0)
                except Exception:
                    payload["alphax_idle_days"] = 0
            if payload:
                frappe.db.set_value(target, name, payload, update_modified=False)
                total += 1
        frappe.db.commit()
    return {"updated": total, "doctypes": targets}


def _latest_activity(target, name):
    """Return (datetime, by_user, type, summary) from the newest Communication
    or Comment on the record, or None."""
    best = None
    comms = frappe.get_all(
        "Communication",
        filters={"reference_doctype": target, "reference_name": name},
        fields=["creation", "owner", "communication_medium", "sent_or_received", "subject", "content"],
        order_by="creation desc", limit=1,
    )
    if comms:
        c = comms[0]
        atype = {"Email": "Email", "Phone": "Call", "Chat": "WhatsApp / Chat"}.get(
            c.communication_medium, c.communication_medium or "Communication")
        if c.sent_or_received:
            atype = f"{atype} ({c.sent_or_received})"
        by = c.owner if c.sent_or_received == "Sent" else None
        summary = (c.subject or frappe.utils.strip_html(c.content or ""))[:180]
        best = (c.creation, by, atype, summary)

    comments = frappe.get_all(
        "Comment",
        filters={"reference_doctype": target, "reference_name": name, "comment_type": "Comment"},
        fields=["creation", "owner", "content"],
        order_by="creation desc", limit=1,
    )
    if comments:
        cm = comments[0]
        if not best or cm.creation > best[0]:
            best = (cm.creation, cm.owner, "Comment", frappe.utils.strip_html(cm.content or "")[:180])
    return best


# ---------------------------------------------------------------------------
# Configurable report fields / filters
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_monitor_fields(target="Lead"):
    """Return configured extra fields with resolved fieldtype/options from the
    target doctype meta, for use as report columns and filters."""
    settings = get_settings()
    meta = frappe.get_meta(target) if frappe.db.exists("DocType", target) else None
    out = []
    for row in settings.get("monitor_fields") or []:
        fn = (row.fieldname or "").strip()
        if not fn:
            continue
        df = meta.get_field(fn) if meta else None
        out.append({
            "fieldname": fn,
            "label": row.label or (df.label if df else fn),
            "as_column": int(row.as_column or 0),
            "as_filter": int(row.as_filter or 0),
            "fieldtype": (df.fieldtype if df else "Data"),
            "options": (df.options if df and df.fieldtype == "Link" else None),
        })
    return out


def apply_dimension_filters(target, conditions, filters):
    """Apply values passed for configured monitor fields onto a filters dict."""
    if not filters:
        return conditions
    meta = frappe.get_meta(target)
    for f in get_monitor_fields(target):
        fn = f["fieldname"]
        val = filters.get(fn)
        if val and meta.has_field(fn):
            conditions[fn] = val
    return conditions


def seed_monitor_fields():
    """Seed the extra-report-field table from active accounting dimensions
    (+ territory) so dimensions are immediately usable as columns/filters."""
    if not frappe.db.exists("DocType", "AlphaX CRM Settings"):
        return
    if not frappe.db.exists("DocType", "AlphaX Monitor Field"):
        return
    frappe.clear_cache(doctype="AlphaX CRM Settings")
    meta = frappe.get_meta("AlphaX CRM Settings")
    if not meta.has_field("monitor_fields"):
        return
    doc = frappe.get_single("AlphaX CRM Settings")
    if doc.get("monitor_fields"):
        return
    from alphax_crm.setup.install import active_accounting_dimensions

    seeded = []
    try:
        for fn, label, _dt in active_accounting_dimensions():
            seeded.append((fn, label))
    except Exception:
        pass
    if not any(x[0] == "territory" for x in seeded):
        seeded.append(("territory", "Territory"))
    for fn, label in seeded:
        doc.append("monitor_fields", {"fieldname": fn, "label": label, "as_column": 1, "as_filter": 1})
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
