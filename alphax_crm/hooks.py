app_name = "alphax_crm"
app_title = "AlphaX CRM Automation"
app_publisher = "Neotec Integrated Solutions"
app_description = "Compliance-grade CRM automation for AlphaX on Frappe/ERPNext."
app_email = "support@neotec.ai"
app_license = "Proprietary"
app_version = "0.45.0"

# Requires ERPNext (Lead / Opportunity / CRM doctypes)
required_apps = ["erpnext"]

# ------------------------------------------------------------------------------
# Global assets
# ------------------------------------------------------------------------------
app_include_js = [
    "/assets/alphax_crm/js/alphax_call.js",
    "/assets/alphax_crm/js/alphax_ai_assistant.js",
    "/assets/alphax_crm/js/alphax_ai_writing.js",
]

# AI writing-tools config (spell check / translate) sent to the desk once per session
boot_session = ["alphax_crm.ai.writing.boot_session", "alphax_crm.crm.workflow.boot_session"]

# ------------------------------------------------------------------------------
# Client scripts
# ------------------------------------------------------------------------------
doctype_js = {
    "Opportunity": "public/js/opportunity.js",
    "Lead": "public/js/lead.js",
    "AlphaX PreLead": "public/js/prelead.js",
    "AlphaX Smart Lead": "public/js/smart_lead.js",
    "AlphaX CRM Settings": "public/js/crm_settings.js",
    "Quotation": "public/js/quotation.js",
}

# List-view scripts (separate hook from doctype_js/form scripts above). Lead
# is a core ERPNext doctype, so its list customization can't use the
# doctype-folder <name>_list.js convention AlphaX PreLead's list view uses —
# it has to be registered explicitly here.
doctype_list_js = {
    "Lead": "public/js/lead_list.js",
}

# ------------------------------------------------------------------------------
# Install / migrate
# ------------------------------------------------------------------------------
after_install = "alphax_crm.setup.install.after_install"
after_migrate = "alphax_crm.setup.install.after_migrate"

# ------------------------------------------------------------------------------
# Document events  (all heavy AI/network work is enqueued, never inline)
# ------------------------------------------------------------------------------
doc_events = {
    "Lead": {
        "before_validate": "alphax_crm.crm.lead.before_validate",
        "before_insert": "alphax_crm.crm.lead.before_insert",
        "validate": "alphax_crm.crm.lead.validate",
        "after_insert": "alphax_crm.crm.lead.after_insert",
        "on_update": "alphax_crm.crm.lead.on_update",
    },
    "Opportunity": {
        "validate": ["alphax_crm.crm.opportunity.validate", "alphax_crm.crm.workflow.opportunity_validate"],
        "after_insert": ["alphax_crm.crm.opportunity.after_insert", "alphax_crm.crm.workflow.opportunity_after_save"],
        "on_update": ["alphax_crm.crm.opportunity.on_update", "alphax_crm.crm.workflow.opportunity_after_save"],
    },
    # ERPNext sets the Lead to "Converted" when a Customer is created from it: keep the approved stage
    "Customer": {
        "validate": "alphax_crm.crm.workflow.customer_validate",
        "after_insert": "alphax_crm.crm.workflow.customer_after_save",
        "on_update": "alphax_crm.crm.workflow.customer_after_save",
    },
    "Communication": {
        "after_insert": [
            "alphax_crm.crm.activity.on_communication",
            "alphax_crm.ai.sales.on_communication",
            "alphax_crm.ai.sales.on_inbound_email",
        ],
    },
    "Comment": {
        "after_insert": "alphax_crm.crm.activity.on_comment",
    },
    "AlphaX PreLead": {
        "validate": "alphax_crm.crm.prelead.validate",
        "on_update": "alphax_crm.crm.prelead.on_update",
    },
    "Quotation": {
        "validate": "alphax_crm.crm.workflow.quotation_validate",
        "after_insert": "alphax_crm.crm.workflow.quotation_after_insert",
        "before_submit": "alphax_crm.crm.workflow.quotation_before_submit",
        "before_cancel": "alphax_crm.crm.workflow.quotation_before_cancel",
        "on_submit": ["alphax_crm.crm.workflow.quotation_on_submit", "alphax_crm.crm.quotation.guard_lead_stage"],
        "on_cancel": ["alphax_crm.crm.workflow.quotation_on_cancel", "alphax_crm.crm.quotation.guard_lead_stage"],
        "on_update": "alphax_crm.crm.quotation.guard_lead_stage",
        "on_update_after_submit": "alphax_crm.crm.quotation.guard_lead_stage",
    },
}

# ------------------------------------------------------------------------------
# Scheduler  (stale-deal detection + PDPL retention + WF-05 SLA rules)
# ------------------------------------------------------------------------------
scheduler_events = {
    "daily_long": [
        "alphax_crm.crm.tasks.scan_stale_records",
        "alphax_crm.crm.tasks.run_pdpl_retention",
        "alphax_crm.crm.tasks.refresh_activity_monitor",
        "alphax_crm.crm.tasks.notify_overdue_schedules",
        "alphax_crm.ai.sales.daily_next_action_sweep",
        "alphax_crm.ai.engine.purge_old_logs",
    ],
    "cron": {
        # approved AI follow-up emails go out when their time comes
        "*/10 * * * *": ["alphax_crm.ai.sales.send_due_drafts"],
        # WF-04 / WF-05 / lost-quotation digest: 08:00 site time (Asia/Riyadh); each job skips non-working days
        "0 8 * * *": ["alphax_crm.crm.workflow.daily_0800"],
        # WF-02 (24/72 working hours) and notifications queued outside business hours
        "5 * * * *": ["alphax_crm.crm.workflow.wf02_hourly"],
        "*/5 * * * *": ["alphax_crm.crm.automation.flush_outbox"],
    },
}

# ------------------------------------------------------------------------------
# Fixtures  (any AlphaX-prefixed custom fields / property setters created at
# runtime are re-exported on `bench export-fixtures`; defaults are installed
# programmatically in setup/install.py so a fresh push self-heals on migrate)
# ------------------------------------------------------------------------------
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["name", "like", "%-alphax\\_%"]],
    },
    {
        "dt": "Notification",
        "filters": [["name", "like", "AlphaX %"]],
    },
    {
        "dt": "Workflow",
        "filters": [["name", "like", "AlphaX %"]],
    },
    {
        # Select-option extensions ensure_select_option() (crm/utils.py)
        # makes on core fields so an admin-configured mapping's values (e.g.
        # Lead Stage Map's targets) are actually legal on the field
        # automation writes them into. Narrowly scoped to the one field this
        # app touches this way, not every Property Setter on the site.
        "dt": "Property Setter",
        "filters": [["doc_type", "=", "Lead"], ["field_name", "=", "status"], ["property", "=", "options"]],
    },
]

# Record the authenticated executor independently of the Lead's commercial owner.
for _dt, _events in {
    "AlphaX Smart Lead": ["after_insert", "on_update"], "AlphaX PreLead": ["after_insert", "on_update"],
    "Customer": ["after_insert", "on_update"],
    "Lead": ["after_insert", "on_update"], "Opportunity": ["after_insert", "on_update"],
    "Quotation": ["after_insert", "on_update", "on_submit", "on_cancel", "on_update_after_submit"],
    "AlphaX Email Draft": ["after_insert", "on_update"], "AlphaX Follow-up": ["after_insert", "on_update"],
    "Comment": ["after_insert"], "Communication": ["after_insert"],
    "ToDo": ["after_insert", "on_update"], "Event": ["after_insert", "on_update"],
}.items():
    for _event in [*_events, "on_trash"]:
        _handlers = doc_events.setdefault(_dt, {}).get(_event, [])
        if isinstance(_handlers, str):
            _handlers = [_handlers]
        doc_events[_dt][_event] = [*_handlers, "alphax_crm.crm.action_history.capture"]

doc_events["Quotation"]["validate"] = ["alphax_crm.crm.workflow.quotation_validate", "alphax_crm.crm.commercial.validate_replacement"]
scheduler_events["daily_long"].append("alphax_crm.crm.commercial.snapshot_forecast")
doctype_js["AlphaX Automation Log"] = "public/js/automation_log.js"
doc_events["Quotation"]["on_update"].append("alphax_crm.crm.sales_desk.resolve_missing_quote")
doc_events["Quotation"]["on_cancel"].append("alphax_crm.crm.sales_desk.reconcile_cancelled_quote")
