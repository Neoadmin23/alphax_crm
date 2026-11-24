"""Isolated tests: WF-02 working-hours counting mode and the SLA default-rule merge.
Run with unittest outside a Frappe bench."""
import importlib
import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch


class Row(dict):
    __getattr__ = dict.get


def as_date(value=None):
    return date.fromisoformat(str(value)[:10]) if value else date.today()


class WorkingHoursAndSlaMergeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        cls.frappe = MagicMock()
        cls.frappe.whitelist.side_effect = lambda **kw: lambda fn: fn
        cls.frappe._ = lambda message: message
        cls.frappe._dict = Row
        cls.frappe.utils.cint.side_effect = lambda n: int(n or 0)
        cls.frappe.utils.getdate.side_effect = as_date
        cls.frappe.utils.get_datetime.side_effect = lambda x: x if isinstance(x, datetime) else datetime.fromisoformat(str(x))
        cls.frappe.utils.add_days.side_effect = lambda d, n: d + timedelta(days=n)
        cls.mods = patch.dict(sys.modules, {"frappe": cls.frappe, "frappe.utils": cls.frappe.utils,
                                            "frappe.custom.doctype.custom_field.custom_field": MagicMock()})
        cls.mods.start()
        cls.auto = importlib.import_module("alphax_crm.crm.automation")
        cls.install = importlib.import_module("alphax_crm.setup.install")

    @classmethod
    def tearDownClass(cls):
        cls.mods.stop()
        for m in [m for m in sys.modules if m.startswith("alphax_crm.")]:
            sys.modules.pop(m, None)

    def cal(self, mode):
        return Row(days={6, 0, 1, 2, 3}, start=time(8), end=time(17), holidays=set(), mode=mode)

    # --- counting mode --------------------------------------------------------------
    def test_working_days_mode_24h_is_one_working_day(self):
        thu_10 = datetime(2026, 11, 19, 10)   # Thursday; Fri/Sat are off
        cal = self.cal("Working days (24h per day)")
        self.assertEqual(self.auto.working_hours_between(thu_10, datetime(2026, 11, 22, 10), cal), 24)   # Thu 14h + Sun 10h = 1 working day later
        self.assertGreaterEqual(self.auto.working_hours_between(thu_10, datetime(2026, 11, 23, 0), cal), 38)  # end of Sunday
        self.assertGreaterEqual(self.auto.working_hours_between(thu_10, datetime(2026, 11, 25, 0), cal), 72)  # Tue end

    def test_business_hours_mode_needs_far_longer(self):
        thu_10 = datetime(2026, 11, 19, 10)
        cal = self.cal("Business hours only")
        # a whole working week later it still has not reached 72 business hours
        self.assertLess(self.auto.working_hours_between(thu_10, datetime(2026, 11, 25, 0), cal), 72)

    def test_calendar_reads_the_setting_and_defaults_to_working_days(self):
        with patch.object(self.auto, "holiday_lists", return_value=[]):
            self.assertEqual(self.auto.calendar(Row(business_days=None)).mode, "Working days (24h per day)")
            self.assertEqual(self.auto.calendar(Row(working_hours_mode="Business hours only")).mode, "Business hours only")
            self.assertEqual(self.auto.calendar(Row(working_hours_mode="Working days (24h per day)")).mode,
                             "Working days (24h per day)")

    # --- SLA merge ---------------------------------------------------------------------
    def test_merge_on_empty_table_gives_all_defaults(self):
        self.assertEqual(len(self.install.missing_default_sla_rules([])), len(self.install._default_stage_sla_rules()))

    def test_merge_adds_only_missing_rows_and_keeps_edited_ones(self):
        existing = [Row(stage="Lead", days=1, notify="Both"),                      # old/extra row: kept, not a default
                    Row(stage="Lead", days=3, notify="Both", label="My wording"),    # default pair, customised: untouched
                    Row(stage="Contract Under Signing", days=10, notify="Lead Owner")]
        before = [dict(r) for r in existing]
        missing = {(r[0], r[1]) for r in self.install.missing_default_sla_rules(existing)}
        self.assertNotIn(("Lead", 3), missing)                    # already there, whatever its audience/label
        self.assertNotIn(("Contract Under Signing", 10), missing)
        self.assertIn(("Lead", 7), missing)
        self.assertIn(("Contract Under Signing", 4), missing)
        self.assertIn(("Interested", 3), missing)
        self.assertEqual(existing, before)                        # input never modified

    def test_merge_is_idempotent_and_case_insensitive(self):
        table = [Row(stage=r[0].upper(), days=r[1]) for r in self.install._default_stage_sla_rules()]
        self.assertEqual(self.install.missing_default_sla_rules(table), [])


if __name__ == "__main__":
    unittest.main()
