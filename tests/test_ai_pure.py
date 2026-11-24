"""Unit tests for alphax_crm.ai.pure (no Frappe needed): python -m unittest tests/test_ai_pure.py"""
import importlib.util
import os
import unittest

spec = importlib.util.spec_from_file_location(
	"pure", os.path.join(os.path.dirname(__file__), "..", "alphax_crm", "ai", "pure.py"))
pure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pure)


class TestPure(unittest.TestCase):
	def test_mask_unmask_roundtrip(self):
		text = "Call +966 55 123 4567 or mail sara@acme.sa; again sara@acme.sa"
		masked, masks = pure.mask_pii(text)
		self.assertNotIn("sara@acme.sa", masked)
		self.assertNotIn("123 4567", masked)
		self.assertEqual(masked.count("[EMAIL_1]"), 2)
		self.assertEqual(pure.unmask(masked.replace("Call", "اتصل"), masks), text.replace("Call", "اتصل"))

	def test_mask_shared_across_calls(self):
		_, masks = pure.mask_pii("a@b.co")
		m2, masks = pure.mask_pii("again a@b.co and c@d.co", masks)
		self.assertEqual(m2, "again [EMAIL_1] and [EMAIL_2]")

	def test_private_hosts(self):
		for h in ("localhost", "10.0.0.5", "192.168.1.9", "ai.local", "127.0.0.1"):
			self.assertTrue(pure.is_private_host(h), h)
		for h in ("api.openai.com", "8.8.8.8", "abc.trycloudflare.com", ""):
			self.assertFalse(pure.is_private_host(h), h)
		self.assertTrue(pure.host_allowed("gpu.neotec.sa", ["*.neotec.sa"]))
		self.assertFalse(pure.host_allowed("neotec.sa.evil.com", ["*.neotec.sa"]))

	def test_extract_json(self):
		self.assertEqual(pure.extract_json('<think>x</think>```json\n{"a": 1}\n```'), {"a": 1})
		self.assertEqual(pure.extract_json('Sure! {"a": {"b": "}"}} done'), {"a": {"b": "}"}})
		with self.assertRaises(ValueError):
			pure.extract_json("no json")

	def test_language(self):
		self.assertEqual(pure.detect_language("كم عدد العملاء المحتملين هذا الشهر؟"), "Arabic")
		self.assertEqual(pure.detect_language("How many leads this month?"), "English")
		self.assertEqual(pure.other_language("Arabic"), "English")

	def test_spelling_filter(self):
		plain = "Please recieve the HP 26A order from Neotek, VAT incl. please deliver today"
		proposed = [
			{"original": "recieve", "corrected": "receive"},
			{"original": "please deliver", "corrected": "kindly ship"},
			{"original": "HP 26A", "corrected": "HP 26X"},
			{"original": "Neotek", "corrected": "Neotech"},
			{"original": "VAT", "corrected": "Vat"},
			{"original": "ghost", "corrected": "host"},
			"garbage",
		]
		out = pure.filter_spelling_changes(proposed, plain, ["Neotek"])
		self.assertEqual(out, [{"original": "recieve", "corrected": "receive"}])

	def test_apply_changes_whole_words_and_html(self):
		ch = [{"original": "الشركه", "corrected": "الشركة"}, {"original": "teh", "corrected": "the"}]
		self.assertEqual(pure.apply_changes("الشركه والشركهات teh tehran", ch), "الشركة والشركهات the tehran")
		html = '<p class="teh">teh <a href="/teh">teh</a> &amp;</p>'
		self.assertEqual(pure.apply_changes(html, ch, True), '<p class="teh">the <a href="/teh">the</a> &amp;</p>')

	def test_protect_restore(self):
		text = "Quote CRM-LEAD-2026-00042 for model HP26A, mail ops@acme.sa, see https://acme.sa/x, call 0551234567 (Neotec)"
		protected, tokens = pure.protect(text, ["Neotec"])
		for v in ("CRM-LEAD-2026-00042", "HP26A", "ops@acme.sa", "https://acme.sa/x", "0551234567", "Neotec"):
			self.assertNotIn(v, protected)
			self.assertIn(v, tokens)
		restored, missing = pure.restore(protected, tokens)
		self.assertEqual((restored, missing), (text, []))
		dropped = protected.replace("⟦1⟧", "")
		_, missing = pure.restore(dropped, tokens)
		self.assertEqual(len(missing), 1)

	def test_html_helpers(self):
		parts, idx = pure.html_segments("<p>Hello <b>world</b></p><p> </p>")
		self.assertEqual([parts[i] for i in idx], ["Hello ", "world"])
		self.assertEqual(pure.html_to_text("<p>A &amp; B</p><p>C</p>"), "A & B\nC")
		self.assertEqual(pure.text_to_html("a <b>\n\nc"), "<p>a &lt;b&gt;</p><p>c</p>")

	def test_cadence_clamp(self):
		self.assertEqual(pure.parse_cadence("1, 3 ,7"), [1, 3, 7])
		self.assertEqual(pure.parse_cadence("x"), [2, 5, 10])
		self.assertEqual(pure.clamp("45", 0, 30), 30)
		self.assertEqual(pure.clamp(None, 0, 30), 0)


if __name__ == "__main__":
	unittest.main()
