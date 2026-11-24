"""Sales desk acceptance cases with a simulated Frappe data boundary."""
import importlib
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch


class Row(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class Log(Row):
    def append(self, field, value):
        self[field].append(Row(value))

    def save(self, **kwargs):
        pass


def day(value=None):
    return date.fromisoformat(str(value or "2026-11-24")[:10])


class SalesDeskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        cls.f = MagicMock()
        cls.f._dict = Row
        cls.f._ = lambda text:text
        cls.f.whitelist.side_effect = lambda **kwargs: lambda fn:fn
        cls.f.utils.getdate.side_effect = day
        cls.f.utils.nowdate.return_value = "2026-11-24"
        cls.f.utils.add_days.side_effect = lambda dt,n:day(dt)+timedelta(days=n)
        cls.f.utils.date_diff.side_effect = lambda a,b:(day(a)-day(b)).days
        cls.f.utils.cint.side_effect = lambda n:int(n or 0)
        cls.f.utils.flt.side_effect = lambda n:float(n or 0)
        cls.f.utils.now_datetime.return_value = datetime(2026,11,24,9)
        cls.f.utils.get_fullname.side_effect = lambda u:"Name of "+u
        cls.f.throw.side_effect = ValueError("Rejected")
        cls.mods=patch.dict(sys.modules,{"frappe":cls.f,"frappe.utils":cls.f.utils})
        cls.mods.start()
        for key in ["sales_desk","commercial","action_history","delivery"]:
            setattr(cls,key,importlib.import_module("alphax_crm.crm."+key))

    @classmethod
    def tearDownClass(cls):
        cls.mods.stop()
        sys.path.pop(0)

    def test_postponed_due_from_lead_without_followup_row(self):
        lead=Row(name="L",status="Postponed",alphax_next_contact_date="2026-11-23")
        self.assertEqual(list(self.sales_desk.lead_tasks(lead,day(),Row()))[0],
                         ("Contact postponed Lead",day("2026-11-23"),"Lead","L"))

    def test_legacy_postponed_uses_stage_entry(self):
        with patch.object(self.sales_desk.auto,"stage_entry_datetime",return_value=day("2026-11-01")):
            self.assertEqual(self.sales_desk.postponed_date(Row(name="L"),30),day("2026-12-01"))

    def test_due_report_uses_authoritative_date_once(self):
        report=importlib.import_module("alphax_crm.alphax_crm.report.alphax_follow_ups_due.alphax_follow_ups_due")
        old=Row(reference_doctype="Lead",reference_name="L",agent="old",channel="Call",outcome=None,
                next_action="",next_follow_up_date="2026-11-10",follow_up_datetime="2026-11-11")
        lead=Row(name="L",lead_owner="new",owner="creator",alphax_next_contact_date="2026-11-22")
        self.f.get_list.side_effect=lambda dt,**kw:[lead] if dt=="Lead" else [old]
        self.f.has_permission.return_value=True
        with patch("alphax_crm.crm.automation.is_paused",return_value=False), patch("alphax_crm.crm.utils.get_settings",return_value={}):
            data=report.execute({"agent":"new"})[1]
        self.assertEqual([(r["agent"],r["overdue_days"]) for r in data],[("new",2)])
        self.f.get_list.side_effect=None

    def test_missing_quote_resolution_references_exact_quote(self):
        q=Row(name="Q2",docstatus=0)
        with patch.object(self.sales_desk.auto,"lead_for_quotation",return_value="L"),patch.object(self.action_history,"record"):
            self.f.get_all.return_value=["A"]
            self.sales_desk.resolve_missing_quote(q)
            values=self.f.db.set_value.call_args.args[2]
            self.assertEqual((values["resolution"],values["resolution_reference"]),("Resolved","Q2"))

    def test_cancelling_only_quote_reopens(self):
        with patch.object(self.sales_desk.auto,"lead_for_quotation",return_value="L"),patch.object(self.sales_desk.auto,"quotations_for_lead",return_value=[]):
            self.f.get_all.return_value=["A"]
            self.f.db.get_value.return_value="Quotation"
            self.sales_desk.reconcile_cancelled_quote(Row(name="Q"))
            self.assertIsNone(self.f.db.set_value.call_args.args[2]["resolution"])

    def test_revision_family(self):
        quotes=[Row(name="original"),Row(name="amend",amended_from="original"),Row(name="revision",alphax_replaces_quotation="amend"),Row(name="other")]
        groups=self.commercial.families(quotes)
        self.assertEqual([q.name for q in groups["original"]],["original","amend","revision"])
        self.assertEqual(len(groups),2)

    def test_sunday_baseline(self):
        self.assertEqual(self.commercial.snapshot_week("2026-11-28"),day("2026-11-22"))
        self.assertEqual(self.commercial.snapshot_week("2026-11-29"),day("2026-11-29"))

    def test_actions_use_real_executor_and_background_source(self):
        self.f.session.user="rep@example.com"
        self.f.local.request=object()
        self.assertEqual(self.action_history.identity(),dict(actor_user="rep@example.com",actor_name="Name of rep@example.com",
                         action_source="User",initiated_by="rep@example.com"))
        self.assertEqual(self.action_history.identity(True)["action_source"],"Automation")
        self.f.local.request=None
        self.f.session.user="Administrator"
        self.assertIsNone(self.action_history.identity()["initiated_by"])
        self.assertEqual(self.action_history.identity()["action_source"],"Automation")

    def test_only_failed_address_retried(self):
        log=Log(lead="L",recipients="owner\nmanager",send_email=1,log_on_timeline=1,delivery_attempts=[
            Row(recipient="owner",channel="Email",result="Queued"),Row(recipient="manager",channel="Email",result="Failed"),
            Row(recipient="owner",channel="In-app",result="Sent"),Row(recipient="manager",channel="In-app",result="Sent")])
        with patch.object(self.sales_desk.auto,"_send_email",return_value="COMM") as send,patch.object(self.sales_desk.auto,"user_emails",return_value={"manager":"mgr@local"}):
            self.delivery.deliver_channels(log,("manager","Email"))
            self.delivery.deliver_channels(log,("manager","Email"))
            send.assert_called_once_with(log,["mgr@local"])
        self.assertEqual(len(log.delivery_attempts),5)
        self.assertEqual(log.status,"Sent")

    def test_failed_channel_does_not_claim_success(self):
        log=Log(lead=None,recipients="owner",send_email=1,delivery_attempts=[])
        with patch.object(self.sales_desk.auto,"user_emails",return_value={}):
            self.delivery.deliver_channels(log)
        self.assertEqual(log.status,"Partly Sent")
        self.assertEqual([(r.channel,r.result) for r in log.delivery_attempts],[("In-app","Sent"),("Email","Failed")])

    def test_scorecard_separates_owner_and_actor(self):
        leads=[Row(lead_owner="owner",owner="creator",creation=day("2026-11-02"),status="Won",won_or_lost_date=day("2026-11-20"))]
        acts=[Row(actor_user="agent",action_source="User",action="Quotation Submitted"),
              Row(actor_user="Administrator",action_source="Automation",action="WF-03")]
        with patch.object(self.sales_desk,"visible",return_value=leads),patch.object(self.sales_desk,"action_report",return_value=([],acts)):
            data={r["executive"]:r for r in self.sales_desk.scorecard(Row())[1]}
        self.assertEqual(data["owner"]["win_rate"],100)
        self.assertEqual(data["agent"]["quotations"],1)
        self.assertNotIn("Administrator",data)
