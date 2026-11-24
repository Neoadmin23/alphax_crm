"""Unit tests for alphax_crm/ai/catalogue.py (plain Python: python tests/test_catalogue.py)."""
import importlib.util
import os
import unittest

spec = importlib.util.spec_from_file_location(
	"catalogue", os.path.join(os.path.dirname(__file__), "..", "alphax_crm", "ai", "catalogue.py"))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CatalogueTest(unittest.TestCase):
	def test_every_entry_complete(self):
		keys = {"key", "name", "licence", "params", "gpu", "arabic", "use", "hf", "patterns"}
		for m in c.MODELS:
			self.assertTrue(keys <= set(m), m["key"])
			self.assertIn(m["use"], c.USE_LABELS)
			self.assertIn(m["arabic"], ("Very good", "Good", "Fair"))
		self.assertEqual(len({m["key"] for m in c.MODELS}), len(c.MODELS))

	def test_match_ollama_hf_and_router_names(self):
		cases = {
			"qwen3.8:27b": "qwen3.8-27b", "hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M": "qwen3.8-27b",
			"qwen3.6:27b": "qwen3.6-27b", "Qwen/Qwen3.6-27B-AWQ": "qwen3.6-27b", "qwen3.6:35b": "qwen3.6-35b-a3b",
			"gpt-oss:20b": "gpt-oss-20b", "gpt-oss:120b": "gpt-oss-120b", "openai/gpt-oss-120b": "gpt-oss-120b",
			"gemma4:e4b": "gemma4-e4b", "llama4:scout": "llama4-scout", "mistral-small3.2": "mistral-small-3.2",
			"deepseek-ai/DeepSeek-V4-Flash": "deepseek-v4-flash", "qwen/qwen3.6-27b:free": "qwen3.6-27b",
		}
		for name, key in cases.items():
			self.assertEqual((c.match(name) or {}).get("key"), key, name)
		self.assertIsNone(c.match("llama3.1"))
		self.assertIsNone(c.match(""))

	def test_free_tier_only_on_router_free_models(self):
		self.assertTrue(c.is_free_tier("https://openrouter.ai/api/v1", "qwen/qwen3.6-27b:free"))
		self.assertTrue(c.is_free_tier("https://openrouter.ai/api/v1", "openrouter/free"))
		self.assertFalse(c.is_free_tier("https://openrouter.ai/api/v1", "qwen/qwen3.6-27b"))
		self.assertFalse(c.is_free_tier("http://10.0.0.5:11434", "something:free"))

	def test_models_url(self):
		self.assertEqual(c.models_url("http://gpu:11434/", "Ollama"), "http://gpu:11434/api/tags")
		self.assertEqual(c.models_url("http://gpu:11434/api/chat", "Ollama"), "http://gpu:11434/api/tags")
		self.assertEqual(c.models_url("http://gpu:8000/v1", "OpenAI Compatible"), "http://gpu:8000/v1/models")
		self.assertEqual(c.models_url("http://gpu:8000", "OpenAI Compatible"), "http://gpu:8000/v1/models")

	def test_parse_models(self):
		self.assertEqual(c.parse_models({"models": [{"name": "a"}, {"model": "b"}]}), ["a", "b"])
		self.assertEqual(c.parse_models({"data": [{"id": "x"}]}), ["x"])
		self.assertEqual(c.parse_models([]), [])

	def test_grade(self):
		ok, no = {"ok": True}, {"ok": False}
		self.assertEqual(c.grade([ok, ok, ok, ok]), "Passed")
		self.assertEqual(c.grade([ok, no, ok, no]), "Partial")
		self.assertEqual(c.grade([no, ok, ok, ok]), "Failed")  # structured JSON is essential
		self.assertEqual(c.grade([no, no, no, no]), "Failed")
		self.assertEqual(c.grade([]), "Not tested")

	def test_fingerprint_changes_with_server_or_model(self):
		a = c.fingerprint("Ollama", "http://gpu:11434", "/api/chat", "qwen3.8:27b")
		self.assertEqual(a, c.fingerprint("Ollama", "http://GPU:11434/", "/api/chat", "qwen3.8:27b"))
		self.assertNotEqual(a, c.fingerprint("Ollama", "http://gpu2:11434", "/api/chat", "qwen3.8:27b"))
		self.assertNotEqual(a, c.fingerprint("Ollama", "http://gpu:11434", "/api/chat", "qwen3.6:27b"))

	def test_presets(self):
		self.assertEqual(c.PRESETS["OpenRouter (hosted open models)"]["external"], 1)
		self.assertTrue(all(p["provider"] in ("Ollama", "OpenAI Compatible") for p in c.PRESETS.values()))

	def test_http_error_summary(self):
		html = "<!DOCTYPE html><html><head><title>Cloudflare Tunnel error | x.trycloudflare.com</title></head></html>"
		msg = c.http_error_summary(530, html)
		self.assertNotIn("<", msg)
		self.assertIn("Tunnel is down", msg)
		self.assertIn("not found", c.http_error_summary(404, '{"error": "model \'x\' not found"}'))
		self.assertTrue(c.is_server_problem(502) and c.is_server_problem(530) and not c.is_server_problem(404))

	def test_size_b(self):
		self.assertEqual(c.size_b("llama3.2:3b"), 3)
		self.assertEqual(c.size_b("llama3.1:8b"), 8)
		self.assertEqual(c.size_b("Qwen/Qwen3.6-35B-A3B"), 35)
		self.assertEqual(c.size_b("gemma4:e4b"), 4)
		self.assertIsNone(c.size_b("llama3.1"))


if __name__ == "__main__":
	unittest.main()
