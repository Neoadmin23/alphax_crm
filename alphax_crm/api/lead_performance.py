"""AlphaX "Lead performance" report — one period-driven screen that replaces
the separate Daily / Weekly / Monthly summaries (see the design mockup
"AlphaX CRM Reporting Dashboard").

Everything is computed server-side from data this app already keeps:
  * stage entries   -> AlphaX Stage Transition Log (every Lead Stage change)
  * new leads       -> Lead.creation
  * quotations      -> submitted Quotation documents addressed to a Lead
  * open pipeline   -> Lead.status right now
Every number respects the existing dashboard filters (Sales Person, Source,
City, Country, Business Unit, Sub Service) plus Status (custom_lead_status)
and Current stage (Lead.status).

Period rules (from the mockup's definitions):
  Daily        = the report-through day
  Weekly       = Sunday of that week .. report-through date
  Monthly      = 1st of the month .. report-through date (month-to-date)
  Quarterly    = quarter start .. report-through date
  Half-yearly  = Jan 1 / Jul 1 .. report-through date
Prior-year windows use the same calendar period and the same elapsed days
(weekly: same Sunday-based week number and weekday).
"""

import calendar
import datetime

import frappe
from frappe import _

from alphax_crm.crm.bi_report import (
    datetime_range,
    fetch_lead_dim_map,
    get_closure_values,
    get_lead_stage_options,
    lead_dimension_filters,
    passes_dimension_filters,
    usable_lead_field,
)

PERIODS = ["Daily", "Weekly", "Monthly", "Quarterly", "Half-Yearly"]
_CHUNK = 1000


# ------------------------------------------------------------------ helpers
def _require_management():
    if not ({"Sales User", "Sales Manager", "System Manager"} & set(frappe.get_roles())):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _d(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return frappe.utils.getdate(str(v)[:10])


def _cols(doctype):
    try:
        return set(frappe.db.get_table_columns(doctype))
    except Exception:
        return set()


def _chunks(items, n=_CHUNK):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _safe_replace_year(d, year):
    try:
        return d.replace(year=year)
    except ValueError:  # 29 Feb
        return d.replace(year=year, day=28)


def period_window(period, through):
    """(start, end) for a period type, ending on the report-through date."""
    through = _d(through)
    period = period or "Monthly"
    if period == "Daily":
        return through, through
    if period == "Weekly":
        offset = (through.weekday() + 1) % 7  # Sunday = 0
        return through - datetime.timedelta(days=offset), through
    if period == "Quarterly":
        m = ((through.month - 1) // 3) * 3 + 1
        return through.replace(month=m, day=1), through
    if period in ("Half-Yearly", "Half-yearly"):
        return through.replace(month=1 if through.month <= 6 else 7, day=1), through
    return through.replace(day=1), through


def _week_number_and_dow(d):
    return int(d.strftime("%U")), (d.weekday() + 1) % 7


def window_years_back(period, start, end, years):
    """Same calendar period / elapsed days, `years` years earlier."""
    if period == "Weekly":
        week, dow = _week_number_and_dow(end)
        y = end.year - years
        jan1 = datetime.date(y, 1, 1)
        first_sun = jan1 + datetime.timedelta(days=(7 - (jan1.weekday() + 1) % 7) % 7)
        if week >= 1:
            new_end = first_sun + datetime.timedelta(days=(week - 1) * 7 + dow)
            return new_end - datetime.timedelta(days=(end - start).days), new_end
    return _safe_replace_year(start, start.year - years), _safe_replace_year(end, end.year - years)


def _clean(v):
    return (v or "").strip() if isinstance(v, str) else v


# ------------------------------------------------------------ filter engine
class _Ctx:
    """One request's filters + cached lookups."""

    def __init__(self, f):
        self.f = frappe._dict(f)
        self.won, self.lost, self.postponed = get_closure_values()
        self.stages = get_lead_stage_options()
        self.status_ok = bool(usable_lead_field("custom_lead_status"))
        self._dim = {}

    # status / current stage filters beyond the shared dimension filters
    def extra_ok(self, row):
        if self.f.get("current_stage") and (row.get("status") or "") != self.f.current_stage:
            return False
        if self.f.get("status") and self.status_ok and (row.get("custom_lead_status") or "") != self.f.status:
            return False
        return True

    def lead_conditions(self):
        c = lead_dimension_filters(self.f)
        if self.f.get("current_stage"):
            c["status"] = self.f.current_stage
        if self.f.get("status") and self.status_ok:
            c["custom_lead_status"] = self.f.status
        return c

    def dims(self, names):
        names = [n for n in set(names) if n not in self._dim]
        for part in _chunks(names):
            self._dim.update(fetch_lead_dim_map(part))
        return self._dim

    def passes(self, name):
        row = self._dim.get(name)
        return bool(row) and passes_dimension_filters(row, self.f) and self.extra_ok(row)

    # ---- data pulls
    def log_rows(self, start, end, names=None):
        flt = {"reference_doctype": "Lead", "field_label": "Lead Stage"}
        if start:
            a, b = datetime_range(start, end)
            flt["changed_on"] = ["between", [a, b]]
        rows = []
        if names is None:
            rows = frappe.get_all("AlphaX Stage Transition Log", filters=flt,
                                  fields=["reference_name", "to_value", "changed_on"], limit_page_length=0)
        else:
            for part in _chunks(names):
                f2 = dict(flt)
                f2["reference_name"] = ["in", part]
                rows += frappe.get_all("AlphaX Stage Transition Log", filters=f2,
                                       fields=["reference_name", "to_value", "changed_on"], limit_page_length=0)
        return rows

    def new_lead_names(self, start, end):
        a, b = datetime_range(start, end)
        c = self.lead_conditions()
        c["creation"] = ["between", [a, b]]
        return {r.name for r in frappe.get_all("Lead", filters=c, fields=["name"], limit_page_length=0)}

    def stage_sets(self, start, end):
        """{stage: set(lead names)} for distinct leads entering each stage in
        the window, after filters. 'Lead' (the initial stage) also counts
        every lead created in the window, since creation is its entry."""
        rows = self.log_rows(start, end)
        self.dims([r.reference_name for r in rows])
        sets = {}
        for r in rows:
            if self.passes(r.reference_name):
                sets.setdefault(r.to_value, set()).add(r.reference_name)
        new = self.new_lead_names(start, end)
        if self.stages:
            first = self.stages[0]
            sets.setdefault(first, set()).update(new)
        return sets, new

    def earliest(self):
        """Earliest date we hold any history for (to show 'No data')."""
        dates = []
        try:
            r = frappe.get_all("Lead", fields=["creation"], order_by="creation asc", limit_page_length=1)
            if r and r[0].get("creation"):
                dates.append(_d(r[0].creation))
        except Exception:
            pass
        try:
            r = frappe.get_all("AlphaX Stage Transition Log", fields=["changed_on"], order_by="changed_on asc",
                               limit_page_length=1)
            if r and r[0].get("changed_on"):
                dates.append(_d(r[0].changed_on))
        except Exception:
            pass
        return min(dates) if dates else None


def _filters_from(kw):
    return {k: kw.get(k) for k in ("lead_owner", "source", "city", "country", "custom_business_line_",
                                   "custom_sub_service", "status", "current_stage") if kw.get(k)}


# --------------------------------------------------------------- the report
def _stage_summary(ctx, start, end):
    sets, new = ctx.stage_sets(start, end)
    won = len(sets.get(ctx.won, ()))
    lost_names = set()
    for s in ctx.lost:
        lost_names |= sets.get(s, set())
    counts = {s: len(sets.get(s, ())) for s in ctx.stages}
    # stages seen in the log but not in the configured list still count
    for s, v in sets.items():
        counts.setdefault(s, len(v))
    return {
        "new_leads": len(new),
        "stages": counts,
        "total_entries": sum(counts.values()),
        "won": won,
        "lost": len(lost_names),
    }, sets


def _default_currency():
    try:
        return frappe.defaults.get_global_default("currency") or "SAR"
    except Exception:
        return "SAR"


def _quotations(ctx, start, end):
    cols = _cols("Quotation")
    fields = ["name", "party_name", "grand_total"]
    pay = "payment_terms_template" if "payment_terms_template" in cols else None
    if pay:
        fields.append(pay)
    if "currency" in cols:
        fields.append("currency")
    rows = frappe.get_all("Quotation", filters={"quotation_to": "Lead", "docstatus": 1,
                                                "transaction_date": ["between", [start, end]]},
                          fields=fields, limit_page_length=0)
    ctx.dims([r.party_name for r in rows if r.party_name])
    total, count, by_pay, cur = 0.0, 0, {}, None
    for r in rows:
        if not r.party_name or not ctx.passes(r.party_name):
            continue
        v = r.get("grand_total") or 0
        key = (r.get(pay) if pay else None) or _("(no payment terms)")
        e = by_pay.setdefault(key, {"payment_type": key, "count": 0, "value": 0.0})
        e["count"] += 1
        e["value"] += v
        total += v
        count += 1
        cur = cur or r.get("currency")
    types = sorted(by_pay.values(), key=lambda x: -x["value"])
    return {"count": count, "value": total, "avg": (total / count) if count else 0,
            "types": types, "currency": cur or _default_currency()}


def _snapshot(ctx, through):
    """Open pipeline by stage right now + stage aging (days since the most
    recent entry into the stage the lead is in now)."""
    c = ctx.lead_conditions()
    closed = [ctx.won] + list(ctx.lost)
    if "status" not in c:
        c["status"] = ["not in", closed]
    lcols = _cols("Lead")
    fields = ["name", "status", "creation"] + (["modified"] if "modified" in lcols else [])
    leads = frappe.get_all("Lead", filters=c, fields=fields, limit_page_length=0)
    leads = [l for l in leads if (l.status or "") not in closed]
    last_entry = {}
    for r in ctx.log_rows(None, None, names=[l.name for l in leads]):
        if r.to_value:
            k = (r.reference_name, r.to_value)
            ts = str(r.changed_on)
            if k not in last_entry or ts > last_entry[k]:
                last_entry[k] = ts
    today = _d(frappe.utils.today())
    by_stage = {}
    for l in leads:
        st = l.status or "(none)"
        when = last_entry.get((l.name, st)) or l.get("modified") or l.creation
        days = max((today - _d(when)).days, 0) if when else 0
        e = by_stage.setdefault(st, {"count": 0, "days": []})
        e["count"] += 1
        e["days"].append(days)
    order = [s for s in ctx.stages if s in by_stage] + [s for s in by_stage if s not in ctx.stages]
    pipeline = [{"stage": s, "count": by_stage[s]["count"]} for s in order]
    aging = [{"stage": s, "avg_days": round(sum(by_stage[s]["days"]) / len(by_stage[s]["days"]), 1),
              "max_days": max(by_stage[s]["days"]), "count": by_stage[s]["count"]} for s in order]
    return pipeline, aging, len(leads)


def _funnel(ctx, start, end, through):
    """Cohort conversion: leads created in the window and how many reached each
    stage by the report-through date."""
    cohort = ctx.new_lead_names(start, end)
    if not cohort:
        return []
    reached = {}
    _a, flt_end = datetime_range(start, through)
    for part in _chunks(cohort):
        rows = frappe.get_all("AlphaX Stage Transition Log",
                              filters={"reference_doctype": "Lead", "field_label": "Lead Stage",
                                       "reference_name": ["in", part], "changed_on": ["<=", flt_end]},
                              fields=["reference_name", "to_value"], limit_page_length=0)
        for r in rows:
            reached.setdefault(r.to_value, set()).add(r.reference_name)
    path = [s for s in ctx.stages if s not in ctx.lost and s != ctx.postponed and s != ctx.won]
    path = path[:6] + [ctx.won]
    out, prev, base = [], None, len(cohort)
    for i, s in enumerate(path):
        n = base if i == 0 else len(reached.get(s, set()) & cohort)
        out.append({"stage": s, "count": n,
                    "pct_of_leads": round(100.0 * n / base, 1) if base else None,
                    "step_pct": round(100.0 * n / prev, 1) if prev else None})
        prev = n or prev
    return out


def _lost_reasons(ctx, start, end, sets):
    names = set()
    for s in ctx.lost:
        names |= sets.get(s, set())
    reasons = {}
    for n in names:
        row = ctx._dim.get(n) or {}
        r = row.get("lost_reason") or row.get("detailed_reason") or _("(not set)")
        reasons[r] = reasons.get(r, 0) + 1
    return [{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda x: -x[1])]


@frappe.whitelist()
def get_lead_options():
    """Status + Current stage choices for the Lead performance filters."""
    _require_management()
    stages = get_lead_stage_options()
    statuses = []
    try:
        fld = frappe.get_meta("Lead").get_field("custom_lead_status")
        if fld and fld.options and fld.fieldtype == "Select":
            statuses = [o.strip() for o in fld.options.split("\n") if o.strip()]
        elif fld:
            rows = frappe.get_all("Lead", filters={"custom_lead_status": ["is", "set"]},
                                  fields=["custom_lead_status"], distinct=True, limit_page_length=0)
            statuses = sorted({r.custom_lead_status for r in rows})
    except Exception:
        statuses = []
    return {"stages": stages, "statuses": statuses}


@frappe.whitelist()
def get_lead_performance(period="Monthly", report_through=None, years_back=3, lead_owner=None, source=None,
                         city=None, country=None, custom_business_line_=None, custom_sub_service=None,
                         status=None, current_stage=None):
    _require_management()
    years_back = max(1, min(int(years_back or 3), 5))
    through = _d(report_through or frappe.utils.today())
    period = period if period in PERIODS else "Monthly"
    ctx = _Ctx(_filters_from(locals()))
    start, end = period_window(period, through)

    cur, cur_sets = _stage_summary(ctx, start, end)
    quote = _quotations(ctx, start, end)
    earliest = ctx.earliest()

    years = []
    for k in range(years_back, -1, -1):
        s, e = (start, end) if k == 0 else window_years_back(period, start, end, k)
        if k == 0:
            summ = cur
        else:
            summ, _unused = _stage_summary(ctx, s, e)
        has_data = bool(earliest and e >= earliest) and (summ["new_leads"] or summ["total_entries"] or k == 0)
        years.append({"year": e.year, "start": str(s), "end": str(e), "has_data": bool(has_data), **summ})
    prev = None
    for y in years:
        if not y["has_data"]:
            y["yoy_leads"] = None
        elif prev and prev["has_data"] and prev["new_leads"]:
            y["yoy_leads"] = round(100.0 * (y["new_leads"] - prev["new_leads"]) / prev["new_leads"], 1)
        else:
            y["yoy_leads"] = None
        prev = y

    pipeline, aging, open_total = _snapshot(ctx, through)

    return {
        "period": period,
        "start": str(start), "end": str(end), "days": (end - start).days + 1,
        "report_through": str(through),
        "stages": ctx.stages, "won_stage": ctx.won, "lost_stages": ctx.lost, "postponed_stage": ctx.postponed,
        "current": {**cur, "avg_quotation": quote["avg"]},
        "yoy_new_leads": years[-1]["yoy_leads"],
        "years": years,
        "quotation": quote,
        "pipeline": pipeline, "open_total": open_total, "aging": aging,
        "lost_reasons": _lost_reasons(ctx, start, end, cur_sets),
        "funnel": _funnel(ctx, start, end, through),
    }


@frappe.whitelist()
def get_lead_drill(kind, stage=None, period="Monthly", report_through=None, year=None, lead_owner=None, source=None,
                   city=None, country=None, custom_business_line_=None, custom_sub_service=None, status=None,
                   current_stage=None):
    """Contributing leads behind a number. kind = new | stage | pipeline | lost."""
    _require_management()
    through = _d(report_through or frappe.utils.today())
    period = period if period in PERIODS else "Monthly"
    ctx = _Ctx(_filters_from(locals()))
    start, end = period_window(period, through)
    if year and int(year) != end.year:
        start, end = window_years_back(period, start, end, end.year - int(year))

    if kind == "new":
        names = ctx.new_lead_names(start, end)
    elif kind == "pipeline":
        c = ctx.lead_conditions()
        if stage:
            c["status"] = stage
        names = {r.name for r in frappe.get_all("Lead", filters=c, fields=["name"], limit_page_length=0)}
    else:
        sets, _new = ctx.stage_sets(start, end)
        if kind == "lost":
            names = set().union(*[sets.get(s, set()) for s in ctx.lost]) if ctx.lost else set()
        else:
            names = sets.get(stage, set())

    lcols = _cols("Lead")
    want = ["name", "lead_name", "company_name", "lead_owner", "source", "city", "status", "creation"]
    fields = [f for f in want if f in lcols]
    rows = []
    for part in _chunks(names):
        rows += frappe.get_all("Lead", filters={"name": ["in", part]}, fields=fields, limit_page_length=0)
    rows.sort(key=lambda r: str(r.get("creation") or ""), reverse=True)
    out = [{k: (str(v) if k == "creation" and v else v) for k, v in dict(r).items()} for r in rows[:500]]
    return {"rows": out, "total": len(rows), "start": str(start), "end": str(end)}
