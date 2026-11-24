"""Isolated tests: daily follow-up report rules, follow-up due email recipients, Postponed highlight colours.
Run with unittest outside a Frappe bench (the highlight test needs `node`)."""
import importlib
import json
import shutil
import subprocess
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class Row(dict):
    __getattr__ = dict.get


def as_date(value=None):
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10]) if value else date.today()


def fu(name, rec, when, nxt=None, summary="Called", agent="rep@x.com", action=None):
    return {"name": name, "reference_doctype": "Lead", "reference_name": rec, "follow_up_datetime": when,
            "next_follow_up_date": nxt, "summary": summary, "agent": agent, "next_action": action}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT))
        cls.frappe = MagicMock()
        cls.frappe.whitelist.side_effect = lambda **kw: lambda fn: fn
        cls.frappe._ = lambda m: m
        cls.frappe.utils.cint.side_effect = lambda n: int(n or 0)
        cls.frappe.utils.getdate.side_effect = as_date
        cls.frappe.utils.get_datetime.side_effect = lambda x: x if isinstance(x, datetime) else datetime.fromisoformat(str(x))
        cls.frappe.utils.add_days.side_effect = lambda d, n: d + timedelta(days=n)
        cls.mods = patch.dict(sys.modules, {"frappe": cls.frappe, "frappe.utils": cls.frappe.utils,
                                            "frappe.custom.doctype.custom_field.custom_field": MagicMock()})
        cls.mods.start()
        cls.rep = importlib.import_module("alphax_crm.crm.followup_report")
        cls.w = importlib.import_module("alphax_crm.crm.workflow")

    @classmethod
    def tearDownClass(cls):
        cls.mods.stop()
        for m in [m for m in sys.modules if m.startswith("alphax_crm.")]:
            sys.modules.pop(m, None)


class DailyReportTest(Base):
    D = date(2026, 11, 24)

    def status_of(self, rows, rec):
        return [(r["status"], r["scheduled_for"].isoformat()) for r in rows if r["reference_name"] == rec]

    def test_pending_overdue_upcoming(self):
        rows = self.rep.classify([
            fu("1", "L-PEND", datetime(2026, 11, 20, 9), "2026-11-24"),
            fu("2", "L-OVER", datetime(2026, 11, 18, 9), "2026-11-22"),
            fu("3", "L-LATER", datetime(2026, 11, 20, 9), "2026-11-30"),
        ], self.D)
        self.assertEqual(self.status_of(rows, "L-PEND"), [("Pending", "2026-11-24")])
        self.assertEqual(self.status_of(rows, "L-OVER"), [("Overdue", "2026-11-22")])
        self.assertEqual(self.status_of(rows, "L-LATER"), [])
        self.assertEqual(next(r for r in rows if r["reference_name"] == "L-OVER")["overdue_days"], 2)

    def test_completed_when_next_follow_up_is_logged(self):
        rows = self.rep.classify([
            fu("1", "L-A", datetime(2026, 11, 20, 9), "2026-11-24"),
            fu("2", "L-A", datetime(2026, 11, 24, 10), "2026-12-01"),   # done on the day, sets the next one
        ], self.D)
        self.assertEqual(self.status_of(rows, "L-A"), [("Completed", "2026-11-24")])

    def test_overdue_cleared_today_counts_as_completed_but_older_clearance_is_hidden(self):
        rows = self.rep.classify([
            fu("1", "L-LATE", datetime(2026, 11, 15, 9), "2026-11-18"),
            fu("2", "L-LATE", datetime(2026, 11, 24, 11)),                # cleared today, no next date
            fu("3", "L-OLD", datetime(2026, 11, 10, 9), "2026-11-12"),
            fu("4", "L-OLD", datetime(2026, 11, 13, 9)),                  # cleared long ago
        ], self.D)
        self.assertEqual(self.status_of(rows, "L-LATE"), [("Completed", "2026-11-18")])
        self.assertEqual(self.status_of(rows, "L-OLD"), [])

    def test_work_after_the_report_date_is_not_counted(self):
        rows = self.rep.classify([
            fu("1", "L-X", datetime(2026, 11, 18, 9), "2026-11-22"),
            fu("2", "L-X", datetime(2026, 11, 26, 9)),                    # logged after the report date
        ], self.D)
        self.assertEqual(self.status_of(rows, "L-X"), [("Overdue", "2026-11-22")])

    def test_system_placeholders_are_ignored(self):
        rows = self.rep.classify([
            fu("1", "L-P", datetime(2026, 11, 20, 9), "2026-11-24"),
            fu("2", "L-P", datetime(2026, 11, 21, 9), None, summary="AlphaX: Lead postponed - log the next follow-up here."),
        ], self.D)
        self.assertEqual(self.status_of(rows, "L-P"), [("Pending", "2026-11-24")])   # placeholder did not complete it

    def test_counts_and_order(self):
        rows = self.rep.classify([
            fu("1", "A", datetime(2026, 11, 20, 9), "2026-11-24"),
            fu("2", "B", datetime(2026, 11, 18, 9), "2026-11-22"),
            fu("3", "C", datetime(2026, 11, 20, 9), "2026-11-24"), fu("4", "C", datetime(2026, 11, 24, 9)),
        ], self.D)
        self.assertEqual([r["status"] for r in rows], ["Overdue", "Pending", "Completed"])
        self.assertEqual(self.rep.summary_counts(rows, self.D),
                         {"scheduled": 2, "completed": 1, "pending": 1, "overdue": 1})


class FollowUpDueEmailTest(Base):
    def run_job(self, lead_stage, followups):
        lead = Row(name="L-1", lead_name="Acme", lead_owner="owner@x.com", owner="admin", status=lead_stage,
                   alphax_next_contact_date="2026-11-24")
        def get_all(doctype, **kw):
            return [lead] if doctype == "Lead" else [Row(f) for f in followups]
        self.frappe.get_all.side_effect = get_all
        self.frappe.get_meta.return_value.has_field.return_value = True
        w = self.w
        with patch.object(w, "get_settings", return_value=Row(won_stage_value="Won", lost_stage_values="", postponed_stage_value="Postponed")), \
             patch.object(w.auto, "is_working_day", return_value=True), \
             patch.object(w, "_previous_working_day", return_value=date(2026, 11, 23)), \
             patch.object(w.auto, "is_paused", return_value=False), \
             patch.object(w.auto, "notify") as notify:
            w.followup_due_daily()
        return notify

    def test_agent_who_logged_it_is_notified_along_with_lead_owner(self):
        notify = self.run_job("Interested", [fu("F1", "L-1", datetime(2026, 11, 20, 9), "2026-11-24", agent="agent@x.com", action="Send brochure")])
        notify.assert_called_once()
        self.assertEqual(sorted(notify.call_args.args[1]), ["agent@x.com", "owner@x.com"])
        self.assertEqual(notify.call_args.kwargs["context"]["next_action"], "Send brochure")
        self.assertEqual(notify.call_args.kwargs["lead"], "L-1")

    def test_lead_stage_is_emailed_only_when_an_agent_logged_the_follow_up(self):
        self.assertFalse(self.run_job("Lead", []).called)                     # seeded date only: WF-05 / new-lead alert cover it
        notify = self.run_job("Lead", [fu("F1", "L-1", datetime(2026, 11, 20, 9), "2026-11-24", agent="agent@x.com")])
        notify.assert_called_once()

    def test_date_not_set_by_the_latest_follow_up_is_treated_as_seeded(self):
        self.assertFalse(self.run_job("Lead", [fu("F1", "L-1", datetime(2026, 11, 20, 9), "2026-12-15")]).called)

    def test_postponed_and_terminal_stages_are_not_emailed_here(self):
        self.assertFalse(self.run_job("Postponed", [fu("F1", "L-1", datetime(2026, 11, 20, 9), "2026-11-24")]).called)
        self.assertFalse(self.run_job("Won", [fu("F1", "L-1", datetime(2026, 11, 20, 9), "2026-11-24")]).called)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PostponedHighlightTest(unittest.TestCase):
    HARNESS = """
const frappe = {
  boot: { alphax_workflow: { postponed: "Postponed", postponed_highlight: %(mode)s } },
  datetime: {
    get_today: () => "2026-11-24",
    get_diff: (a, b) => Math.round((Date.parse(a.slice(0,10)) - Date.parse(b.slice(0,10))) / 86400000),
    str_to_user: (d) => d,
  },
};
const __ = (s, a) => (a || []).reduce((t, v, i) => t.replace("{" + i + "}", v), s);
global.window = {}; global.frappe = frappe; global.__ = __;
require(%(js)s);
const cases = %(cases)s;
console.log(JSON.stringify(cases.map(c => { const s = window.alphax_postponed_state(c); return s ? [s.key, s.color, s.banner] : null; })));
console.log(window.alphax_postponed_mode());
"""

    def run_node(self, cases, mode="undefined"):
        code = self.HARNESS % {"js": json.dumps(str(ROOT / "alphax_crm/public/js/alphax_postponed.js")),
                               "cases": json.dumps(cases), "mode": mode}
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        first, second = out.stdout.strip().splitlines()
        return json.loads(first), second

    def test_colours(self):
        P = {"status": "Postponed"}
        result, mode = self.run_node([
            {**P, "alphax_next_contact_date": "2026-12-15"},                                      # waiting
            {**P, "alphax_next_contact_date": "2026-11-24"},                                      # due today
            {**P, "alphax_next_contact_date": "2026-11-20"},                                      # overdue, nothing since
            {**P, "alphax_next_contact_date": "2026-11-20", "alphax_last_activity": "2026-11-22 10:00:00"},  # overdue, followed up
            {**P, "alphax_next_contact_date": "2026-11-20", "alphax_last_activity": "2026-11-10 10:00:00"},  # activity was before the due date
            {"status": "Quotation", "alphax_next_contact_date": "2026-11-20"},                     # not postponed
            {**P},                                                                                 # no date
        ])
        self.assertEqual(result, [["waiting", "gray", "blue"], ["due", "orange", "orange"], ["overdue", "red", "red"],
                                  ["overdue_followed", "orange", "orange"], ["overdue", "red", "red"], None, None])
        self.assertEqual(mode, "Both")                    # default when the setting is absent

    def test_mode_comes_from_the_setting(self):
        _, mode = self.run_node([], mode='"Lead form"')
        self.assertEqual(mode, "Lead form")


if __name__ == "__main__":
    unittest.main()
