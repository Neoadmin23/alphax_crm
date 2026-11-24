"""Isolated tests for the 0.45.1 hardening changes. Run with unittest outside a bench."""
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _frappe_mock():
    f = MagicMock()
    f.whitelist.side_effect = lambda **kw: (lambda fn: fn)
    f._ = lambda m: m
    f.throw.side_effect = ValueError("throw")
    f.local.response = {}
    return f


class HardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        cls.frappe = _frappe_mock()
        rl = MagicMock()
        rl.rate_limit = lambda **kw: (lambda fn: fn)
        cls.mods = {"frappe": cls.frappe, "frappe.utils": MagicMock(), "frappe.rate_limiter": rl,
                    "alphax_crm.crm.utils": MagicMock()}
        cls.patcher = patch.dict(sys.modules, cls.mods)
        cls.patcher.start()
        for m in ("alphax_crm.api.whatsapp", "alphax_crm.api.ai_setup", "alphax_crm.api.lead_intake"):
            sys.modules.pop(m, None)
        for m in ("alphax_crm.crm.prelead", "alphax_crm.crm.smart_lead"):
            sys.modules.pop(m, None)
        cls.prelead = importlib.import_module("alphax_crm.crm.prelead")
        cls.smart = importlib.import_module("alphax_crm.crm.smart_lead")
        cls.wa = importlib.import_module("alphax_crm.api.whatsapp")
        cls.setup = importlib.import_module("alphax_crm.api.ai_setup")
        cls.intake = importlib.import_module("alphax_crm.api.lead_intake")

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        for m in ("alphax_crm.api.whatsapp", "alphax_crm.api.ai_setup", "alphax_crm.api.lead_intake",
                  "alphax_crm.crm.prelead", "alphax_crm.crm.smart_lead"):
            sys.modules.pop(m, None)

    def setUp(self):
        self.frappe.local.response = {}
        self.frappe.reset_mock(side_effect=False)
        self.frappe.throw.side_effect = ValueError("throw")

    def _settings(self, **values):
        s = MagicMock()
        s.whatsapp_enabled = 1
        s.get_password.side_effect = lambda field, **kw: values.get(field)
        for k, v in values.items():
            setattr(s, k, v)
        return s

    # --- WhatsApp -------------------------------------------------------------
    def test_whatsapp_rejects_when_no_app_secret(self):
        with patch.object(self.wa, "get_settings", return_value=self._settings()):
            self.frappe.request.get_data.return_value = b"{}"
            out = self.wa._receive()
        self.assertEqual(out["status"], "app_secret_not_configured")
        self.assertEqual(self.frappe.local.response["http_status_code"], 401)
        self.frappe.enqueue.assert_not_called()

    def test_whatsapp_rejects_bad_signature_and_accepts_good(self):
        import hashlib, hmac
        body = b'{"entry":[]}'
        good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        with patch.object(self.wa, "get_settings", return_value=self._settings(whatsapp_app_secret="s3cret")):
            self.frappe.request.get_data.return_value = body
            self.frappe.get_request_header.return_value = "sha256=deadbeef"
            self.assertEqual(self.wa._receive()["status"], "bad_signature")
            self.frappe.enqueue.assert_not_called()
            self.frappe.get_request_header.return_value = good
            self.assertEqual(self.wa._receive()["status"], "received")
            self.frappe.enqueue.assert_called_once()

    # --- AI setup token ---------------------------------------------------------
    def _register(self, token, url="http://10.0.0.5:11434", saved="tok123"):
        s = self._settings(ai_setup_token="*****")
        s.get_password.side_effect = lambda field, **kw: saved
        s.meta.has_field.return_value = False
        self.frappe.get_single.return_value = s
        return s, self.setup.register_endpoint(token=token, base_url=url)

    def test_register_wrong_token_rejected(self):
        with self.assertRaises(ValueError):
            self._register("nope")

    def test_register_bad_url_rejected(self):
        with self.assertRaises(ValueError):
            self._register("tok123", url="javascript:alert(1)")
        with self.assertRaises(ValueError):
            self._register("tok123", url="not a url")

    def test_register_success_rotates_token(self):
        self.frappe.generate_hash.return_value = "rotated"
        s, out = self._register("tok123")
        self.assertTrue(out["ok"])
        self.assertEqual(s.ai_setup_token, "rotated")
        self.assertEqual(s.ai_base_url, "http://10.0.0.5:11434")

    # --- Intake ------------------------------------------------------------------
    def test_intake_rejects_missing_or_wrong_token(self):
        s = self._settings(intake_token="abc")
        with patch.object(self.intake, "get_settings", return_value=s):
            for header in (None, "", "abd"):
                self.frappe.local.response = {}
                self.frappe.get_request_header.return_value = header
                out = self.intake.capture()
                self.assertFalse(out["ok"])
                self.assertEqual(self.frappe.local.response["http_status_code"], 401)

    # --- AI destination policy -----------------------------------------------------
    def test_destination_policy(self):
        ok = ["https://abc.trycloudflare.com", "https://ai.example.com:8443/x", "http://192.168.1.20:11434",
              "http://10.0.0.5:11434", "http://127.0.0.1:11434", "http://localhost:11434", "http://ollama-box:11434"]
        bad = ["http://example.com", "http://8.8.8.8:11434", "https://169.254.169.254/latest", "http://169.254.169.254",
               "https://user:pw@example.com", "ftp://example.com", "javascript:alert(1)", "http://", "not a url",
               "https://example.com:notaport", "http://0.0.0.0:11434"]
        for u in ok:
            self.assertIsNone(self.setup.destination_problem(u), u)
        for u in bad:
            self.assertIsNotNone(self.setup.destination_problem(u), u)

    # --- Permission policy -----------------------------------------------------------
    def _perm_denied(self):
        self.frappe.has_permission.side_effect = PermissionError("denied")

    def test_prelead_conversion_requires_create_permission_on_both_paths(self):
        self._perm_denied()
        doc = MagicMock()
        for target in ("Lead", "Smart Lead then Lead"):
            settings = MagicMock()
            settings.get.side_effect = lambda k, d=None, t=target: t if k == "prospect_convert_target" else d
            self.frappe.db.exists.return_value = True
            self.frappe.new_doc.reset_mock()
            with self.assertRaises(PermissionError):
                self.prelead._convert_to_lead(doc, settings)
            self.frappe.new_doc.assert_not_called()
        self.frappe.has_permission.assert_any_call("Lead", "create", throw=True)
        self.frappe.has_permission.assert_any_call("AlphaX Smart Lead", "create", throw=True)
        self.frappe.has_permission.side_effect = None

    def test_manual_smart_lead_sync_checks_the_specific_lead(self):
        sl = MagicMock(); sl.get.side_effect = lambda k, d=None: {"lead": "LEAD-1"}.get(k, d); sl.lead = "LEAD-1"
        lead = MagicMock(); lead.check_permission.side_effect = PermissionError("no write on LEAD-1")
        self.frappe.get_doc.side_effect = lambda dt, name=None: sl if dt == "AlphaX Smart Lead" else lead
        self.frappe.db.exists.return_value = True
        with self.assertRaises(PermissionError):
            self.smart._sync_to_lead("SL-1", check_permissions=True)
        lead.check_permission.assert_called_once_with("write")
        self.frappe.get_doc.side_effect = None

    def test_manual_smart_lead_sync_requires_create_for_new_lead(self):
        sl = MagicMock(); sl.get.return_value = None; sl.lead = None
        self.frappe.get_doc.side_effect = None
        self.frappe.get_doc.return_value = sl
        self._perm_denied()
        with self.assertRaises(PermissionError):
            self.smart._sync_to_lead("SL-1", check_permissions=True)
        self.frappe.has_permission.assert_called_with("Lead", "create", throw=True)
        self.frappe.new_doc.assert_not_called()
        self.frappe.has_permission.side_effect = None


if __name__ == "__main__":
    unittest.main()
