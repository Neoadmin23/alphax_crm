"""Lead Monitor Summary.

Aggregated Lead Data Quality Monitor for Sales Managers and management:
one row per group (sales person, stage, source ...), with follow-up health
and data-quality numbers. The drill-down links open the lead list behind
each number in "Lead Data Quality Monitor".
"""


import frappe


def execute(filters=None):
    filters = filters or {}

    # The live site may carry a separate "Lead Status" custom field. When it
    # does not, fall back to the native Lead.status field so the report does
    # not depend on a Custom Field that the app does not own.
    HAS_CUSTOM_LEAD_STATUS = frappe.get_meta("Lead").has_field("custom_lead_status")
    LEAD_STATUS_FIELD = "custom_lead_status" if HAS_CUSTOM_LEAD_STATUS else "status"

    # ============================================================
    # CONFIG
    # ============================================================

    GROUP_BY = filters.get("group_by") or "Lead Owner"
    STALE_IDLE_DAYS = frappe.utils.cint(filters.get("stale_after_days")) or 14
    CLOSED_STAGES = ["Converted", "Lost Quotation", "Lost with reason", "Do Not Contact"]   # Lead Stage = closed
    CLOSED_STATUSES = ["Inactive Lead"] if HAS_CUSTOM_LEAD_STATUS else []       # Lead Status = closed
    LOW_DQ = 50
    DQ_REQUIRED = 100          # workflow rule: DQ must be 100% to go for approval

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
    # FILTERS (all parameterised)
    # ============================================================

    conditions = []
    values = {}

    if filters.get("year"):
        yr = frappe.utils.cint(filters.get("year"))
        conditions.append("creation >= %(year_start)s AND creation < %(year_end)s")
        values["year_start"] = str(yr) + "-01-01"
        values["year_end"] = str(yr + 1) + "-01-01"

    if filters.get("from_date"):
        conditions.append("creation >= %(from_date)s")
        values["from_date"] = filters.get("from_date")

    if filters.get("to_date"):
        conditions.append("creation < %(to_date_next)s")
        values["to_date_next"] = frappe.utils.add_days(filters.get("to_date"), 1)

    if filters.get("lead_owner"):
        conditions.append("lead_owner = %(lead_owner)s")
        values["lead_owner"] = filters.get("lead_owner")

    if filters.get("workflow_state"):
        conditions.append("workflow_state = %(workflow_state)s")
        values["workflow_state"] = filters.get("workflow_state")

    if filters.get("lead_status"):
        conditions.append(f"{LEAD_STATUS_FIELD} = %(lead_status)s")
        values["lead_status"] = filters.get("lead_status")

    if HAS_CUSTOM_LEAD_STATUS and filters.get("lead_stage"):
        conditions.append("status = %(lead_stage)s")
        values["lead_stage"] = filters.get("lead_stage")

    if filters.get("source"):
        conditions.append("source = %(source)s")
        values["source"] = filters.get("source")

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
        f"""
        SELECT
            name, creation, modified, lead_owner, workflow_state, source, status,
            {LEAD_STATUS_FIELD} AS lead_status,
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
    # AGGREGATE
    # ============================================================

    groups = {}
    all_total = 0
    all_open = 0
    all_crit = 0
    all_stale = 0
    all_active = 0
    all_closed = 0
    all_idle = 0
    all_dq = 0
    all_low = 0
    all_blocked = 0

    for row in rows:
        age = frappe.utils.cint(row.get("lead_age_days"))

        label = BUCKETS[-1][0]
        for bk in BUCKETS:
            if bk[2] is None or age <= bk[2]:
                label = bk[0]
                break

        idle = row.get("alphax_idle_days")
        idle = frappe.utils.cint(idle) if idle is not None else frappe.utils.cint(row.get("fallback_idle_days"))
        dq = frappe.utils.flt(row.get("alphax_dq_score"))

        is_open = (row.get("status") not in CLOSED_STAGES) and (row.get("lead_status") not in CLOSED_STATUSES)
        if not is_open:
            health = "closed"
        elif idle > STALE_IDLE_DAYS * 2:
            health = "critical"
        elif idle > STALE_IDLE_DAYS:
            health = "stale"
        else:
            health = "active"

        if frappe.utils.cint(filters.get("open_only")) and not is_open:
            continue

        if filters.get("followup_health") and health != str(filters.get("followup_health")).lower():
            continue

        # which group does this lead belong to?
        if GROUP_BY == "Lead Stage":
            gv = row.get("status") or "(none)"
        elif GROUP_BY == "Lead Status":
            gv = row.get("lead_status") or "(none)"
        elif GROUP_BY == "Workflow State":
            gv = row.get("workflow_state") or "(none)"
        elif GROUP_BY == "Source":
            gv = row.get("source") or "(none)"
        elif GROUP_BY == "Aging Bucket":
            gv = label
        elif GROUP_BY == "Created Month":
            gv = str(row.get("creation") or "")[:7] or "(none)"
        else:
            gv = row.get("lead_owner") or "Unassigned"

        if gv not in groups:
            groups[gv] = {"grp": gv, "total": 0, "open": 0, "critical": 0, "stale": 0, "active": 0,
                          "closed": 0, "idle_sum": 0, "dq_sum": 0, "low_dq": 0, "blocked": 0}
        g = groups[gv]
        g["total"] = g["total"] + 1
        g[health] = g[health] + 1
        g["idle_sum"] = g["idle_sum"] + idle
        g["dq_sum"] = g["dq_sum"] + dq
        if dq < LOW_DQ:
            g["low_dq"] = g["low_dq"] + 1
        if is_open:
            g["open"] = g["open"] + 1
            if dq < DQ_REQUIRED:
                g["blocked"] = g["blocked"] + 1
                all_blocked = all_blocked + 1
            all_open = all_open + 1

        all_total = all_total + 1
        all_idle = all_idle + idle
        all_dq = all_dq + dq
        if dq < LOW_DQ:
            all_low = all_low + 1
        if health == "critical":
            all_crit = all_crit + 1
        elif health == "stale":
            all_stale = all_stale + 1
        elif health == "active":
            all_active = all_active + 1
        else:
            all_closed = all_closed + 1


    # ============================================================
    # ORDER THE GROUPS
    #   people / stage / source ... : most Critical first
    #   Aging Bucket                : youngest to oldest
    #   Created Month               : newest first
    # ============================================================

    pool = []
    for gk in groups:
        t = groups[gk]
        if GROUP_BY == "Created Month":
            t["sk"] = (t["grp"], 0, 0)
        elif GROUP_BY == "Aging Bucket":
            bi = 0
            for i in range(len(BUCKETS)):
                if BUCKETS[i][0] == t["grp"]:
                    bi = i
            t["sk"] = (0 - bi, 0, 0)
        else:
            t["sk"] = (t["critical"], t["stale"], t["total"])
        pool.append(t)

    ordered = []
    while pool:
        best_i = 0
        for i in range(len(pool)):
            if pool[i]["sk"] > pool[best_i]["sk"]:
                best_i = i
        ordered.append(pool.pop(best_i))


    # ============================================================
    # TABLE
    # ============================================================

    columns = [
        {"label": GROUP_BY, "fieldname": "grp", "fieldtype": "Data", "width": 260},
        {"label": "Total Leads", "fieldname": "total", "fieldtype": "Int", "width": 100},
        {"label": "Open", "fieldname": "open", "fieldtype": "Int", "width": 80},
        {"label": "Critical", "fieldname": "critical", "fieldtype": "Int", "width": 90},
        {"label": "Stale", "fieldname": "stale", "fieldtype": "Int", "width": 80},
        {"label": "Active", "fieldname": "active", "fieldtype": "Int", "width": 80},
        {"label": "Closed", "fieldname": "closed", "fieldtype": "Int", "width": 80},
        {"label": "Critical % of Open", "fieldname": "crit_pct", "fieldtype": "Percent", "width": 130},
        {"label": "Avg Idle Days", "fieldname": "avg_idle", "fieldtype": "Float", "width": 110, "precision": 1},
        {"label": "Avg Data Quality %", "fieldname": "avg_dq", "fieldtype": "Percent", "width": 130},
        {"label": "Open with DQ < 100%", "fieldname": "blocked", "fieldtype": "Int", "width": 140},
        {"label": "Low DQ (<" + str(LOW_DQ) + "%)", "fieldname": "low_dq", "fieldtype": "Int", "width": 110},
    ]

    report_rows = []
    for t in ordered:
        n = t["total"] or 1
        report_rows.append({
            "grp": t["grp"], "total": t["total"], "open": t["open"], "critical": t["critical"],
            "stale": t["stale"], "active": t["active"], "closed": t["closed"],
            "crit_pct": round(t["critical"] * 100.0 / t["open"], 1) if t["open"] else 0,
            "avg_idle": round(t["idle_sum"] / n, 1), "avg_dq": round(t["dq_sum"] / n, 1),
            "blocked": t["blocked"], "low_dq": t["low_dq"],
        })

    n_all = all_total or 1
    if all_total:
        report_rows.append({
            "grp": "TOTAL", "total": all_total, "open": all_open, "critical": all_crit, "stale": all_stale,
            "active": all_active, "closed": all_closed,
            "crit_pct": round(all_crit * 100.0 / all_open, 1) if all_open else 0,
            "avg_idle": round(all_idle / n_all, 1), "avg_dq": round(all_dq / n_all, 1),
            "blocked": all_blocked, "low_dq": all_low,
        })


    # ============================================================
    # SUMMARY CARDS + CHART
    # ============================================================

    avg_dq_all = round(all_dq / n_all, 1) if all_total else 0
    crit_pct_all = round(all_crit * 100.0 / all_open, 1) if all_open else 0

    report_summary = [
        {"value": all_total, "label": "Total Leads", "datatype": "Int", "indicator": "Blue"},
        {"value": all_open, "label": "Open Leads", "datatype": "Int", "indicator": "Blue"},
        {"value": all_crit, "label": "Critical", "datatype": "Int", "indicator": "Red" if all_crit else "Green"},
        {"value": all_stale, "label": "Stale", "datatype": "Int", "indicator": "Orange" if all_stale else "Green"},
        {"value": all_active, "label": "Active", "datatype": "Int", "indicator": "Green"},
        {"value": all_closed, "label": "Closed", "datatype": "Int", "indicator": "Grey"},
        {"value": crit_pct_all, "label": "Critical % of Open", "datatype": "Percent",
         "indicator": "Red" if crit_pct_all >= 30 else ("Orange" if crit_pct_all >= 10 else "Green")},
        {"value": avg_dq_all, "label": "Avg Data Quality %", "datatype": "Percent",
         "indicator": "Green" if avg_dq_all >= 80 else ("Orange" if avg_dq_all >= LOW_DQ else "Red")},
        {"value": all_blocked, "label": "Open with DQ < 100%", "datatype": "Int",
         "indicator": "Red" if all_blocked else "Green"},
    ]

    c_labels = []
    c_crit = []
    c_stale = []
    c_active = []
    for t in ordered[:15]:
        c_labels.append(t["grp"].split("@")[0])
        c_crit.append(t["critical"])
        c_stale.append(t["stale"])
        c_active.append(t["active"])
    if GROUP_BY == "Created Month":
        c_labels.reverse()
        c_crit.reverse()
        c_stale.reverse()
        c_active.reverse()

    chart = {
        "data": {
            "labels": c_labels,
            "datasets": [
                {"name": "Critical", "values": c_crit},
                {"name": "Stale", "values": c_stale},
                {"name": "Active", "values": c_active},
            ],
        },
        "type": "bar",
        "colors": ["#d92d20", "#dc6803", "#039855"],
        "barOptions": {"stacked": 1},
        "height": 280,
    }

    message = None
    if not all_total:
        message = "No leads match the selected filters."

    data = columns, report_rows, message, chart, report_summary
    return data
