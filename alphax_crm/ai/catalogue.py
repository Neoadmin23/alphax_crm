"""Open models guide, provider presets and free-tier rules for AlphaX AI (pure Python, no Frappe).

The catalogue is guidance for choosing a model, not a download: a model is tens of gigabytes of weights
and runs on its own GPU server (Ollama or vLLM). AlphaX connects to that server.

Facts were checked in October/November 2026 (model cards, vendor posts). "arabic" is an indicative rating
for Saudi business text; the model self-test (Settings > AI Assist > Test Model) is the real check on your
own server. Ollama tags and Hugging Face ids change: "Find Models on Server" reads what is really installed.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# use -> how the model fits AlphaX
MAIN, LIGHT, DATACENTRE = "main", "light", "datacentre"
USE_LABELS = {
	MAIN: "All AI features (main model)",
	LIGHT: "Light use (Fast Model: spell check, translate)",
	DATACENTRE: "Data centre (multi-GPU)",
}

MODELS = [
	{
		"key": "qwen3.8-27b", "name": "Qwen3.8 27B", "vendor": "Alibaba Qwen", "licence": "Apache 2.0",
		"params": "27B dense", "released": "2026-08-14", "context": "256K",
		"gpu": "1 x 24 GB (4-bit, ~14 GB weights) · 80 GB for full precision (~54 GB)",
		"arabic": "Very good", "use": MAIN, "recommended": 1,
		"ollama": "qwen3.8:27b", "hf": "Qwen/Qwen3.8-27B", "vllm_tool_parser": "qwen3_coder",
		"note": "Current default pick for a single 24 GB GPU. Successor of Qwen3.6 27B.",
		"patterns": [r"qwen3[.\-_]?8.*27b"],
	},
	{
		"key": "qwen3.6-27b", "name": "Qwen3.6 27B", "vendor": "Alibaba Qwen", "licence": "Apache 2.0",
		"params": "27B dense", "released": "2026 (spring)", "context": "256K",
		"gpu": "1 x 24 GB (4-bit, ~17 GB)", "arabic": "Very good", "use": MAIN, "recommended": 1,
		"ollama": "qwen3.6:27b", "hf": "Qwen/Qwen3.6-27B", "vllm_tool_parser": "qwen3_coder",
		"note": "Proven previous generation; AWQ builds exist for vLLM.",
		"patterns": [r"qwen3[.\-_]?6.*27b"],
	},
	{
		"key": "qwen3.6-35b-a3b", "name": "Qwen3.6 35B-A3B (MoE)", "vendor": "Alibaba Qwen", "licence": "Apache 2.0",
		"params": "35B total / 3B active", "released": "2026 (spring)", "context": "256K",
		"gpu": "1 x 24 GB (4-bit, ~20 GB)", "arabic": "Very good", "use": MAIN, "recommended": 0,
		"ollama": "qwen3.6:35b", "hf": "Qwen/Qwen3.6-35B-A3B", "vllm_tool_parser": "qwen3_coder",
		"note": "Mixture of experts: large in total, only ~3B run per word, so it answers fast.",
		"patterns": [r"qwen3[.\-_]?6.*35b"],
	},
	{
		"key": "gpt-oss-20b", "name": "gpt-oss 20B", "vendor": "OpenAI (open weights)", "licence": "Apache 2.0",
		"params": "21B total / 3.6B active", "released": "2025-08", "context": "128K",
		"gpu": "1 x 16 GB", "arabic": "Fair", "use": MAIN, "recommended": 0,
		"ollama": "gpt-oss:20b", "hf": "openai/gpt-oss-20b", "vllm_tool_parser": "openai",
		"note": "Good structured output on a 16 GB card; Arabic is weaker than Qwen or Gemma.",
		"patterns": [r"gpt-?oss\W*20b"],
	},
	{
		"key": "gpt-oss-120b", "name": "gpt-oss 120B", "vendor": "OpenAI (open weights)", "licence": "Apache 2.0",
		"params": "117B total / 5.1B active", "released": "2025-08", "context": "128K",
		"gpu": "1 x 80 GB (H100 class)", "arabic": "Good", "use": DATACENTRE, "recommended": 0,
		"ollama": "gpt-oss:120b", "hf": "openai/gpt-oss-120b", "vllm_tool_parser": "openai",
		"note": "Strongest reasoning that still fits one data-centre GPU.",
		"patterns": [r"gpt-?oss.*120b"],
	},
	{
		"key": "gemma4-26b-a4b", "name": "Gemma 4 26B A4B (MoE)", "vendor": "Google", "licence": "Apache 2.0",
		"params": "26B total / 3.8B active", "released": "2026", "context": "256K",
		"gpu": "1 x 24 GB (4-bit)", "arabic": "Good", "use": MAIN, "recommended": 0,
		"ollama": "gemma4:26b", "hf": "google/gemma-4-26b-a4b-it", "vllm_tool_parser": "check model card",
		"note": "Best Gemma 4 balance on a 24 GB card. Gemma 4 moved to Apache 2.0.",
		"patterns": [r"gemma-?4.*26b"],
	},
	{
		"key": "gemma4-31b", "name": "Gemma 4 31B", "vendor": "Google", "licence": "Apache 2.0",
		"params": "31B dense", "released": "2026", "context": "256K",
		"gpu": "1 x 24 GB at 32K context (tight) · 48 GB recommended", "arabic": "Good", "use": MAIN, "recommended": 0,
		"ollama": "gemma4:31b", "hf": "google/gemma-4-31b-it", "vllm_tool_parser": "check model card",
		"note": "Highest Gemma 4 quality; needs more memory for long context.",
		"patterns": [r"gemma-?4.*31b"],
	},
	{
		"key": "gemma4-e4b", "name": "Gemma 4 E4B", "vendor": "Google", "licence": "Apache 2.0",
		"params": "~4B effective", "released": "2026", "context": "128K",
		"gpu": "8 GB GPU or CPU", "arabic": "Fair", "use": LIGHT, "recommended": 1,
		"ollama": "gemma4:e4b", "hf": "google/gemma-4-e4b-it", "vllm_tool_parser": "check model card",
		"note": "Small and quick: fine as Fast Model for spell check and translation, not for Ask AI.",
		"patterns": [r"gemma-?4.*e4b"],
	},
	{
		"key": "llama4-scout", "name": "Llama 4 Scout", "vendor": "Meta", "licence": "Llama 4 Community Licence",
		"params": "109B total / 17B active", "released": "2025-04", "context": "10M",
		"gpu": "~55 GB at 4-bit (2 x 24 GB or 1 x 80 GB)", "arabic": "Good", "use": DATACENTRE, "recommended": 0,
		"ollama": "llama4:scout", "hf": "meta-llama/Llama-4-Scout-17B-16E-Instruct", "vllm_tool_parser": "llama4_pythonic",
		"note": "Arabic is an officially supported language. Licence has use restrictions: read it before commercial use.",
		"patterns": [r"llama-?4.*scout"],
	},
	{
		"key": "mistral-small-4", "name": "Mistral Small 4", "vendor": "Mistral AI", "licence": "Apache 2.0",
		"params": "119B total / 6B active", "released": "2026-03", "context": "256K",
		"gpu": "4 x H100 or 2 x H200 (vendor minimum)", "arabic": "Fair", "use": DATACENTRE, "recommended": 0,
		"ollama": "", "hf": "mistralai (Mistral Small 4 collection)", "vllm_tool_parser": "mistral",
		"note": "Despite the name it is a data-centre model. On one 24 GB GPU use Mistral Small 3.2 24B.",
		"patterns": [r"mistral-?small-?4"],
	},
	{
		"key": "mistral-small-3.2", "name": "Mistral Small 3.2 24B", "vendor": "Mistral AI", "licence": "Apache 2.0",
		"params": "24B dense", "released": "2025-06", "context": "128K",
		"gpu": "1 x 24 GB (4-bit)", "arabic": "Fair", "use": MAIN, "recommended": 0,
		"ollama": "mistral-small3.2", "hf": "mistralai/Mistral-Small-3.2-24B-Instruct-2506", "vllm_tool_parser": "mistral",
		"note": "Single-GPU Mistral. Solid structured output; Arabic weaker than Qwen.",
		"patterns": [r"mistral-?small-?3"],
	},
	{
		"key": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "vendor": "DeepSeek", "licence": "MIT",
		"params": "284B total / 13B active", "released": "2026-07-31", "context": "1M",
		"gpu": "8 x B200 class (data centre)", "arabic": "Good", "use": DATACENTRE, "recommended": 0,
		"ollama": "", "hf": "deepseek-ai (DeepSeek V4 collection)", "vllm_tool_parser": "check model card",
		"note": "V4 Pro is 1.6T parameters (multi-node). Not supported on A100/Ampere GPUs in vLLM.",
		"patterns": [r"deepseek.*v4"],
	},
]

# ------------------------------------------------------------------------------------------- presets
PRESETS = {
	"Ollama (self-hosted)": {
		"provider": "Ollama", "base_url": "http://ai-server.local:11434", "chat_path": "/api/chat", "external": 0,
		"help": "Ollama on your own server. Inside the Kingdom and on a private network it passes KSA Data Residency Mode.",
	},
	"vLLM (self-hosted)": {
		"provider": "OpenAI Compatible", "base_url": "http://ai-server.local:8000/v1", "chat_path": "/chat/completions",
		"external": 0, "help": "vLLM on your own GPU server (OpenAI-compatible API). Best throughput for many users.",
	},
	"AlphaX GPU server kit": {
		"provider": "Ollama", "base_url": "https://ai.your-company.sa", "chat_path": "/api/chat", "external": 0,
		"needs_key": 1, "help": "The deploy/gpu-server kit (Ollama or vLLM behind Caddy with an API key). Put the "
			"kit's AI_API_KEY in API Key and the host in Allowed AI Hosts.",
	},
	"OpenRouter (hosted open models)": {
		"provider": "OpenAI Compatible", "base_url": "https://openrouter.ai/api/v1", "chat_path": "/chat/completions",
		"external": 1, "needs_key": 1, "fixed_url": 1, "help": "Hosted open models outside the Kingdom: External. Models ending in "
			"\":free\" are a free tier whose hosts may keep or train on prompts; AlphaX always treats them as External.",
	},
}
PRESET_NAMES = ["Custom"] + list(PRESETS)
PRESET_PLACEHOLDERS = {p["base_url"] for p in PRESETS.values()}

FREE_TIER_HOSTS = ("openrouter.ai",)


def _norm(model_id: str) -> str:
	# "Qwen/Qwen3.6-27B-AWQ", "hf.co/unsloth/Qwen3.6-27B-GGUF:Q4_K_M", "qwen3.6:27b" -> last segment
	return (model_id or "").strip().lower().split("/")[-1].replace("_", "-")


def match(model_id: str):
	"""Catalogue entry for an installed model name (Ollama tag, Hugging Face id, OpenRouter slug), or None."""
	m = _norm(model_id)
	if not m:
		return None
	for entry in MODELS:
		if any(re.search(p, m) for p in entry["patterns"]):
			return entry
	return None


def host_of(base_url: str) -> str:
	return (urlparse(base_url or "").hostname or "").lower()


def is_free_tier(base_url: str, model: str) -> bool:
	"""A free hosted tier (OpenRouter ':free' models and its free router)."""
	host = host_of(base_url)
	if not any(host == h or host.endswith("." + h) for h in FREE_TIER_HOSTS):
		return False
	m = (model or "").strip().lower()
	return m.endswith(":free") or m in ("openrouter/free",)


def is_known_external(base_url: str) -> bool:
	"""Hosts AlphaX knows to be hosted services outside your network."""
	host = host_of(base_url)
	return any(host == h or host.endswith("." + h) for h in FREE_TIER_HOSTS)


def models_url(base_url: str, provider: str) -> str:
	"""Where a server lists its installed models."""
	base = (base_url or "").rstrip("/")
	for suffix in ("/api/chat", "/v1/chat/completions", "/chat/completions"):
		if base.endswith(suffix):
			base = base[: -len(suffix)]
	if provider == "Ollama":
		return base + "/api/tags"
	return base + "/models" if base.endswith("/v1") else base + "/v1/models"


def parse_models(data) -> list[str]:
	"""Model names from an Ollama /api/tags or OpenAI-style /models answer."""
	if not isinstance(data, dict):
		return []
	if isinstance(data.get("models"), list):
		return [m.get("name") or m.get("model") for m in data["models"] if isinstance(m, dict) and (m.get("name") or m.get("model"))]
	if isinstance(data.get("data"), list):
		return [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]
	return []


def describe(model_id: str, base_url: str = "") -> dict:
	"""What the guide knows about an installed model (for the discovery list)."""
	entry = match(model_id)
	free = is_free_tier(base_url, model_id)
	return {
		"model": model_id,
		"known": entry["name"] if entry else None,
		"key": entry["key"] if entry else None,
		"use": USE_LABELS.get(entry["use"]) if entry else None,
		"use_code": entry["use"] if entry else None,
		"arabic": entry["arabic"] if entry else None,
		"gpu": entry["gpu"] if entry else None,
		"licence": entry["licence"] if entry else None,
		"free_tier": free,
	}


def grade(checks: list[dict]) -> str:
	"""Self-test verdict. The structured-output check is essential: without it nothing works."""
	if not checks:
		return "Not tested"
	passed = [c for c in checks if c.get("ok")]
	if len(passed) == len(checks):
		return "Passed"
	if not passed or not checks[0].get("ok"):
		return "Failed"
	return "Partial"


def fingerprint(provider: str, base_url: str, chat_path: str, model: str) -> str:
	"""Identity of a tested setup: changing server address or model resets the result."""
	import hashlib

	raw = "|".join([(provider or "").strip(), (base_url or "").strip().rstrip("/").lower(), (chat_path or "").strip(),
		(model or "").strip()])
	return hashlib.sha1(raw.encode()).hexdigest()[:16]


# ------------------------------------------------------------------------------------------- server errors
HTTP_HINTS = {
	401: "the server refused the API key (check API Key / Cloudflare Access)",
	403: "access denied (check API Key / Cloudflare Access)",
	404: "address or model not found (check AI Base URL, server type and model name)",
	502: "the gateway lost the AI machine (the tunnel or Ollama stopped, or the model took too long to load)",
	503: "the AI server is busy or still loading the model",
	504: "the gateway timed out waiting for the model",
	524: "Cloudflare timed out after about 100 seconds (the model took too long)",
	530: "the Cloudflare Tunnel is down: cloudflared on the AI machine stopped, or the quick-tunnel address changed",
}


def http_error_summary(status: int, body: str) -> str:
	"""One readable line for an HTTP error from the AI server (no raw HTML pages in messages)."""
	import json as _json

	body = body or ""
	detail = ""
	try:
		data = _json.loads(body)
		err = data.get("error") if isinstance(data, dict) else None
		detail = (err.get("message") if isinstance(err, dict) else err) or ""
	except ValueError:
		m = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
		detail = re.sub(r"\s+", " ", m.group(1)).strip() if m else ("" if "<html" in body.lower() else body.strip())
	hint = HTTP_HINTS.get(int(status), "")
	parts = [f"HTTP {status}"] + [x for x in (str(detail)[:160], hint) if x]
	return " — ".join(parts)


def is_server_problem(status: int) -> bool:
	"""Errors that say nothing about the model's quality (outage, gateway, overload)."""
	return int(status) >= 500 or int(status) in (401, 403, 408, 429)


def is_quick_tunnel(base_url: str) -> bool:
	return host_of(base_url).endswith("trycloudflare.com")


def size_b(model: str):
	"""Billions of parameters from a model name such as 'llama3.1:8b' or 'Qwen3.6-35B-A3B' (largest number)."""
	sizes = [float(x) for x in re.findall(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)b(?![a-z0-9])", _norm(model).replace(":", "-"))]
	entry = match(model)
	if not sizes and entry:
		sizes = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)B", entry["params"])]
	return max(sizes) if sizes else None
