"""Isolated rule tests. Run with unittest discovery outside a Frappe bench."""
import importlib
import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch


class Row(dict):
    __getattr__ = dict.get

    def set(self, field, value):
        self[field] = value


def as_date(value=None):
    return date.fromisoformat(str(value)[:10]) if value else date.today()


class ApprovedWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        cls.frappe = MagicMock()
        cls.frappe.whitelist.side_effect = lambda **kw: lambda fn: fn
        cls.frappe._ = lambda message: message
        cls.frappe.throw.side_effect = ValueError("validation")
        cls.frappe.utils.escape_html.side_effect = str
        cls.frappe.utils.cint.side_effect = lambda n: int(n or 0)
        cls.frappe.utils.getdate.side_effect = as_date
        cls.frappe.utils.date_diff.side_effect = lambda a, b: (as_date(a) - as_date(b)).days
        cls.frappe.utils.get_datetime.side_effect = lambda x: datetime.fromisoformat(str(x))
        cls.frappe.utils.add_days.side_effect = lambda d, n: d + timedelta(days=n)
        cls.mods = patch.dict(sys.modules, {"frappe": cls.frappe, "frappe.utils": cls.frappe.utils,
                                            "frappe.custom.doctype.custom_field.custom_field": MagicMock()})
        cls.mods.start()
        cls.w = importlib.import_module("alphax_crm.crm.workflow")
        cls.sf = importlib.import_module("alphax_crm.crm.stage_flow")

    @classmethod
    def tearDownClass(cls):
        cls.mods.stop()
        sys.path.pop(0)

    def test_all_approved_transitions_and_forbidden_pairs(self):
        allowed = {"Lead": ["Interested"], "Interested": ["Qualified lead"], "Qualified lead": ["Quotation"],
                   "Quotation": ["Postponed", "Contract Under Signing", "Lost Quotation"],
                   "Postponed": ["Won", "Lost with reason", "Lost Quotation"],
                   "Contract Under Signing": ["Won", "Lost with reason", "Lost Quotation"]}
        settings = Row(stage_flow_bypass_roles="Sales Manager")
        self.frappe.get_roles.return_value = ["Sales Manager"]
        for old in self.w.SPEC_FLOW:
            for new in self.w.SPEC_FLOW:
                with self.subTest(old=old, new=new):
                    self.frappe.db.get_value.return_value = old
                    doc = Row(name="L", doctype="Lead", status=new, flags={}, is_new=lambda: False,
                              meta=Row(has_field=lambda _: True))
                    if new == old or new in allowed.get(old, []):
                        self.sf.enforce_stage_flow(doc, settings)
                    else:
                        with self.assertRaises(ValueError):
                            self.sf.enforce_stage_flow(doc, settings)

    def test_mapping(self):
        self.assertEqual([self.w.status_for_stage(s) for s in self.w.SPEC_FLOW],
                         ["Lead"]*3 + ["Prospect", "Cold Lead", "Successful", "Customer", "Inactive Lead", "Inactive Lead"])

    def test_notification_identity_scope(self):
        identity = self.w.auto.notification_identity
        args = ["WF-04 lost", "L", ("Quotation", "Q"), "2026-11-24", None]
        initial = identity(*args)
        self.assertEqual(initial, identity(*args))
        for index, other in enumerate(["WF-04 due", "L2", ("Quotation", "Q2"), "2026-11-25", "second"]):
            changed = list(args)
            changed[index] = other
            self.assertNotEqual(initial, identity(*changed))

    def test_contract_cannot_be_signed_early(self):
        doc = Row(status="Contract Under Signing", custom_contract="Signed", flags={}, meta=Row(has_field=lambda _: False))
        with self.assertRaises(ValueError):
            self.w.lead_validate(doc, {"protect_lead_stage": 0, "stage_flow_enabled": 0})

    def test_won_needs_all_three_fields(self):
        for field in ("custom_contract", "won_or_lost_date", "customer"):
            doc = Row(name="L", custom_contract="Signed", won_or_lost_date=date.today())
            doc[field] = None
            self.frappe.db.exists.return_value = field != "customer"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.sf._enforce_won(doc, {})

    def test_loss_needs_all_fields(self):
        for field in ("won_or_lost_date", "lost_reason", "detailed_reason"):
            doc = Row(won_or_lost_date=date.today(), lost_reason="Price", detailed_reason="Budget reduced")
            doc[field] = ""
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.sf._enforce_lost(doc, {})

    def test_24_business_hours(self):
        cal = Row(days={6,0,1,2,3}, start=time(8), end=time(17), holidays=set(), mode="Business hours only")
        thu = datetime(2026,11,19,15)
        self.assertEqual(self.w.auto.working_hours_between(thu, datetime(2026,11,24,12), cal), 24)
        cal.holidays.add(as_date("2026-11-22"))
        self.assertEqual(self.w.auto.working_hours_between(thu, datetime(2026,11,24,12), cal), 15)

    def run_sla(self, stage, days, evidence=(), first_sent=None, quote=False):
        lead = Row(name="L", owner="owner", lead_owner="rep")
        entry = datetime(2026,11,1,9)
        today = entry.date() + timedelta(days=days)
        from alphax_crm.setup.install import _default_stage_sla_rules
        keys = ("stage","days","notify","require_no_activity","label","repeat_every_days")
        rules = [Row(zip(keys, v)) for v in _default_stage_sla_rules() if v[0] == stage]
        self.frappe.db.get_value.return_value = first_sent
        self.frappe.db.exists.return_value = False
        with patch.object(self.w, "auto") as auto:
            auto.is_paused.return_value = False
            auto.stage_entry_datetime.return_value = entry
            auto.already_done.side_effect = lambda k: bool(first_sent) and "#3." in k
            auto.activity_since.return_value = list(evidence)
            auto.approvers.return_value = ["mgr"]
            auto.quotations_for_lead.return_value = ["Q"] if quote else []
            self.w._sla_lead(lead, stage, rules, today, {})
            return [(call.args[1], call.kwargs["context"]["label"]) for call in auto.notify.call_args_list]

    def test_second_reminder_waits_four_days_after_actual_first(self):
        self.assertEqual(len(self.run_sla("Lead", 8, first_sent=date(2026,11,6))), 0)
        self.assertEqual(len(self.run_sla("Lead", 9, first_sent=date(2026,11,6))), 1)

    def test_missed_first_reminder_delivers_first_only(self):
        self.assertIn("First", self.run_sla("Lead", 10)[0][1])
        self.assertEqual(len(self.run_sla("Lead", 10)), 1)

    def test_interested_needs_meeting(self):
        self.assertTrue(self.run_sla("Interested", 3, ["comment","email"]))
        self.assertFalse(self.run_sla("Interested", 7, ["meeting"]))

    def test_qualified_needs_quote(self):
        self.assertTrue(self.run_sla("Qualified lead", 5, ["meeting","note"]))
        self.assertFalse(self.run_sla("Qualified lead", 10, quote=True))

    def test_contract_approver_milestones(self):
        self.assertIn(["mgr"], [p for p,_ in self.run_sla("Contract Under Signing", 4)])
        self.assertTrue(any("Escalation" in label for _,label in self.run_sla("Contract Under Signing", 10, ["email"])))
