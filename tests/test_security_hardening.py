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
        cls.wa = importlib.import_module("alphax_crm.api.whatsapp")
        cls.setup = importlib.import_module("alphax_crm.api.ai_setup")
        cls.intake = importlib.import_module("alphax_crm.api.lead_intake")

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        for m in ("alphax_crm.api.whatsapp", "alphax_crm.api.ai_setup", "alphax_crm.api.lead_intake"):
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


if __name__ == "__main__":
    unittest.main()
