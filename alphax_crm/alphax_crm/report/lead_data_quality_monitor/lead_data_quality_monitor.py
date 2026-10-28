"""Lead Data Quality Monitor.

Lead data-quality, aging, and follow-up health report for the Lead doctype.
"""

import frappe


def execute(filters=None):
    filters = filters or {}
    filters["min_dq"] = filters.get("min_dq") if filters.get("min_dq") not in (None, "") else filters.get("dq_from")
    filters["max_dq"] = filters.get("max_dq") if filters.get("max_dq") not in (None, "") else filters.get("dq_to")
    MIN_IDLE = frappe.utils.cint(filters.get("idle_days"))

    # ============================================================
    # CONFIG
    # ============================================================

    STALE_IDLE_DAYS = frappe.utils.cint(filters.get("stale_after_days")) or 14   # idle threshold for "Stale"
    CLOSED_STAGES = ["Converted", "Lost Quotation", "Lost with reason", "Do Not Contact"]   # Lead Stage values = closed
    CLOSED_STATUSES = ["Inactive Lead"]                                                     # Lead Status values = closed
    LOW_DQ = 50                                                     # DQ % below this = "Low"

    # bucket label -> (min_age, max_age)  (None = open-ended)
    BUCKETS = [
        ("0-7 Days", 0, 7),
        ("8-15 Days", 8, 15),
        ("16-30 Days", 16, 30),
        ("31-60 Days", 31, 60),
        ("61-90 Days", 61, 90),
        ("90+ Days", 91, None),
    ]
    BUCKET_MAP = {}
    for b in BUCKETS:
        BUCKET_MAP[b[0]] = (b[1], b[2])


    # ============================================================
    # COLUMNS
    # ============================================================

    columns = [
        {"label": "Lead", "fieldname": "name", "fieldtype": "Link", "options": "Lead", "width": 170},
        {"label": "Created Date", "fieldname": "creation", "fieldtype": "Datetime", "width": 150},
        {"label": "Lead Name", "fieldname": "lead_name", "fieldtype": "Data", "width": 180},
        {"label": "Company", "fieldname": "company_name", "fieldtype": "Data", "width": 200},
        {"label": "Source", "fieldname": "source", "fieldtype": "Link", "options": "Lead Source", "width": 120},
        {"label": "Lead Owner", "fieldname": "lead_owner", "fieldtype": "Link", "options": "User", "width": 180},
        {"label": "Workflow State", "fieldname": "workflow_state", "fieldtype": "Data", "width": 150},
        {"label": "Lead Status", "fieldname": "custom_lead_status", "fieldtype": "Data", "width": 130},
        {"label": "Lead Stage", "fieldname": "status", "fieldtype": "Data", "width": 140},
        {"label": "Data Quality %", "fieldname": "alphax_dq_score", "fieldtype": "Percent", "width": 120},
        {"label": "DQ Level", "fieldname": "dq_level", "fieldtype": "Data", "width": 90},
        {"label": "Lead Age (Days)", "fieldname": "lead_age_days", "fieldtype": "Int", "width": 120},
        {"label": "Aging Bucket", "fieldname": "aging_bucket", "fieldtype": "Data", "width": 120},
        {"label": "Last Activity", "fieldname": "alphax_last_activity", "fieldtype": "Datetime", "width": 160},
        {"label": "Idle Days", "fieldname": "alphax_idle_days", "fieldtype": "Int", "width": 90},
        {"label": "Follow-up Health", "fieldname": "followup_health", "fieldtype": "Data", "width": 130},
        {"label": "Last Modified", "fieldname": "modified", "fieldtype": "Datetime", "width": 160},
    ]


    # ============================================================
    # FILTER CONDITIONS (all parameterised)
    # ============================================================

    conditions = []
    values = {}

    # Year: range instead of YEAR(creation) so the index on creation can be used
    if filters.get("year"):
        yr = frappe.utils.cint(filters.get("year"))
        conditions.append("creation >= %(year_start)s AND creation < %(year_end)s")
        values["year_start"] = str(yr) + "-01-01"
        values["year_end"] = str(yr + 1) + "-01-01"

    if filters.get("from_date"):
        conditions.append("creation >= %(from_date)s")
        values["from_date"] = filters.get("from_date")

    if filters.get("to_date"):
        # < next day keeps the whole "to" day and stays index-friendly
        conditions.append("creation < %(to_date_next)s")
        values["to_date_next"] = frappe.utils.add_days(filters.get("to_date"), 1)

    if filters.get("lead_owner"):
        conditions.append("lead_owner = %(lead_owner)s")
        values["lead_owner"] = filters.get("lead_owner")

    if filters.get("workflow_state"):
        conditions.append("workflow_state = %(workflow_state)s")
        values["workflow_state"] = filters.get("workflow_state")

    if filters.get("lead_status"):
        conditions.append("custom_lead_status = %(lead_status)s")
        values["lead_status"] = filters.get("lead_status")

    if filters.get("lead_stage"):
        conditions.append("status = %(lead_stage)s")
        values["lead_stage"] = filters.get("lead_stage")

    if filters.get("source"):
        conditions.append("source = %(source)s")
        values["source"] = filters.get("source")

    # Quick search (lead id / name / company)
    if filters.get("search"):
        conditions.append("(name LIKE %(search)s OR lead_name LIKE %(search)s OR company_name LIKE %(search)s)")
        values["search"] = "%" + filters.get("search") + "%"

    # Data quality range
    if filters.get("min_dq") not in (None, ""):
        conditions.append("IFNULL(alphax_dq_score, 0) >= %(min_dq)s")
        values["min_dq"] = frappe.utils.flt(filters.get("min_dq"))

    if filters.get("max_dq") not in (None, ""):
        conditions.append("IFNULL(alphax_dq_score, 0) <= %(max_dq)s")
        values["max_dq"] = frappe.utils.flt(filters.get("max_dq"))

    # Aging bucket pushed into SQL (instead of filtering in Python after the fact)
    if filters.get("aging_bucket") in BUCKET_MAP:
        bucket_range = BUCKET_MAP[filters.get("aging_bucket")]
        lo = bucket_range[0]
        hi = bucket_range[1]
        conditions.append("DATEDIFF(CURDATE(), DATE(creation)) >= %(age_lo)s")
        values["age_lo"] = lo
        if hi is not None:
            conditions.append("DATEDIFF(CURDATE(), DATE(creation)) <= %(age_hi)s")
            values["age_hi"] = hi

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""


    # ============================================================
    # QUERY
    # ============================================================

    rows = frappe.db.sql(
        """
        SELECT
            name, creation, modified, lead_name, company_name, source,
            lead_owner, workflow_state, custom_lead_status, status,
            IFNULL(alphax_dq_score, 0) AS alphax_dq_score,
            alphax_last_activity,
            alphax_idle_days,
            DATEDIFF(CURDATE(), DATE(creation)) AS lead_age_days,
            DATEDIFF(CURDATE(), DATE(IFNULL(alphax_last_activity, modified))) AS fallback_idle_days
        FROM `tabLead`
        """ + where_clause + """
        ORDER BY creation DESC
        """,
        values,
        as_dict=True,
    )


    # ============================================================
    # ENRICH ROWS
    # ============================================================

    report_rows = []
    bucket_counts = {}
    for b in BUCKETS:
        bucket_counts[b[0]] = 0
    owner_counts = {}
    total_age = 0
    total_dq = 0
    stale_count = 0
    low_dq_count = 0

    for row in rows:
        age = frappe.utils.cint(row.get("lead_age_days"))

        # Aging bucket
        label = BUCKETS[-1][0]
        for bk in BUCKETS:
            if bk[2] is None or age <= bk[2]:
                label = bk[0]
                break
        row["aging_bucket"] = label

        # Idle days: use the stored value, else derive from last activity / modified
        idle = row.get("alphax_idle_days")
        idle = frappe.utils.cint(idle) if idle is not None else frappe.utils.cint(row.get("fallback_idle_days"))
        row["alphax_idle_days"] = idle

        # Data quality level
        dq = frappe.utils.flt(row.get("alphax_dq_score"))
        row["dq_level"] = "High" if dq >= 80 else ("Medium" if dq >= LOW_DQ else "Low")

        # Follow-up health
        is_open = (row.get("status") not in CLOSED_STAGES) and (row.get("custom_lead_status") not in CLOSED_STATUSES)
        if not is_open:
            row["followup_health"] = "Closed"
        elif idle > STALE_IDLE_DAYS * 2:
            row["followup_health"] = "Critical"
        elif idle > STALE_IDLE_DAYS:
            row["followup_health"] = "Stale"
        else:
            row["followup_health"] = "Active"

        # Open leads only
        if frappe.utils.cint(filters.get("open_only")) and not is_open:
            continue

        # Minimum idle days filter
        if MIN_IDLE and idle < MIN_IDLE:
            continue

        # Optional "stale only" filter
        if frappe.utils.cint(filters.get("stale_only")) and row["followup_health"] not in ("Stale", "Critical"):
            continue

        # Aggregates
        bucket_counts[label] = bucket_counts[label] + 1
        owner = row.get("lead_owner") or "Unassigned"
        owner_counts[owner] = owner_counts.get(owner, 0) + 1
        total_age += age
        total_dq += dq
        if row["followup_health"] in ("Stale", "Critical"):
            stale_count += 1
        if dq < LOW_DQ:
            low_dq_count += 1

        report_rows.append(row)


    # ============================================================
    # SUMMARY CARDS + CHART
    # ============================================================

    total = len(report_rows)
    avg_age = round(total_age / total, 1) if total else 0
    avg_dq = round(total_dq / total, 1) if total else 0

    report_summary = [
        {"value": total, "label": "Total Leads", "datatype": "Int", "indicator": "Blue"},
        {"value": avg_age, "label": "Avg Lead Age (Days)", "datatype": "Float", "indicator": "Orange"},
        {"value": avg_dq, "label": "Avg Data Quality %", "datatype": "Percent",
         "indicator": "Green" if avg_dq >= 80 else ("Orange" if avg_dq >= LOW_DQ else "Red")},
        {"value": stale_count, "label": "Stale / Critical Leads", "datatype": "Int",
         "indicator": "Red" if stale_count else "Green"},
        {"value": low_dq_count, "label": "Low Data Quality (<" + str(LOW_DQ) + "%)", "datatype": "Int",
         "indicator": "Red" if low_dq_count else "Green"},
    ]

    chart_labels = []
    chart_values = []
    for b in BUCKETS:
        chart_labels.append(b[0])
        chart_values.append(bucket_counts[b[0]])

    chart = {
        "data": {
            "labels": chart_labels,
            "datasets": [{"name": "Leads", "values": chart_values}],
        },
        "type": "bar",
        "colors": ["#5e64ff"],
        "height": 260,
    }

    message = None
    if not total:
        message = "No leads match the selected filters."


    # ============================================================
    # RETURN
    # ============================================================

    data = columns, report_rows, message, chart, report_summary
    return data
