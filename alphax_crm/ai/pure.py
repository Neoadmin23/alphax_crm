"""Framework-free helpers for the AlphaX AI layer. Nothing here imports frappe,
so every rule can be unit-tested with plain Python (see tests/test_ai_pure.py)."""

from __future__ import annotations

import difflib
import html as html_lib
import ipaddress
import json
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w])(?:\+|00)?\d[\d\s\-()]{7,}\d(?![\w])")
URL_RE = re.compile(r"https?://[^\s<>\"']+")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ARABIC_LETTER = re.compile(r"[؀-ۿ]")
LATIN_LETTER = re.compile(r"[A-Za-z]")
WORD_CHARS = r"[^\W_]"
TAG_SPLIT = re.compile(r"(<[^>]*>|&[a-zA-Z#0-9]+;)")
HAS_DIGIT = re.compile(r"\d")


# ----------------------------------------------------------------------------- model output
def extract_json(text: str):
	"""First JSON object/array in an LLM reply (handles code fences and chatter)."""
	if text is None:
		raise ValueError("Empty AI response")
	s = strip_thinking(text).strip()
	fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S | re.I)
	if fence:
		s = fence.group(1).strip()
	try:
		return json.loads(s)
	except ValueError:
		pass
	for opener, closer in (("{", "}"), ("[", "]")):
		start = s.find(opener)
		while start != -1:
			depth, in_str, esc = 0, False, False
			for i in range(start, len(s)):
				ch = s[i]
				if in_str:
					if esc:
						esc = False
					elif ch == "\\":
						esc = True
					elif ch == '"':
						in_str = False
					continue
				if ch == '"':
					in_str = True
				elif ch == opener:
					depth += 1
				elif ch == closer:
					depth -= 1
					if depth == 0:
						try:
							return json.loads(s[start : i + 1])
						except ValueError:
							break
			start = s.find(opener, start + 1)
	raise ValueError("No JSON object found in AI response")


def strip_thinking(text: str) -> str:
	return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)


def truncate(text, limit: int) -> str:
	text = "" if text is None else str(text)
	return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


# ----------------------------------------------------------------------------- privacy
def mask_pii(text: str, masks: dict | None = None):
	"""Swap emails/phones for placeholders. Returns (masked_text, masks) where masks maps
	placeholder -> original, so unmask() can restore them in the model's answer."""
	masks = {} if masks is None else masks
	if not text:
		return text, masks
	reverse = {v: k for k, v in masks.items()}

	def _ph(kind, value):
		if value in reverse:
			return reverse[value]
		key = f"[{kind}_{sum(1 for k in masks if k.startswith('[' + kind)) + 1}]"
		masks[key] = value
		reverse[value] = key
		return key

	text = EMAIL_RE.sub(lambda m: _ph("EMAIL", m.group(0)), text)

	def _phone(m):
		digits = re.sub(r"\D", "", m.group(0))
		return _ph("PHONE", m.group(0)) if 9 <= len(digits) <= 15 else m.group(0)

	return PHONE_RE.sub(_phone, text), masks


def unmask(text: str, masks: dict) -> str:
	for key, value in masks.items():
		text = text.replace(key, value)
	return text


def is_private_host(host: str) -> bool:
	if not host:
		return False
	host = host.strip("[]").lower()
	if host == "localhost" or host.endswith((".local", ".internal", ".lan")):
		return True
	try:
		ip = ipaddress.ip_address(host)
	except ValueError:
		return False
	return ip.is_private or ip.is_loopback or ip.is_link_local


def host_allowed(host: str, allowed: list[str]) -> bool:
	host = (host or "").lower().strip()
	for entry in allowed:
		entry = entry.strip().lower()
		if entry and (host == entry or (entry.startswith("*.") and host.endswith(entry[1:]))):
			return True
	return False


# ----------------------------------------------------------------------------- language
def detect_language(text: str) -> str:
	"""'Arabic' when Arabic letters dominate, else 'English'."""
	ar = len(ARABIC_LETTER.findall(text or ""))
	en = len(LATIN_LETTER.findall(text or ""))
	return "Arabic" if ar > en else "English"


def other_language(lang: str) -> str:
	return "English" if lang == "Arabic" else "Arabic"


# ----------------------------------------------------------------------------- spelling
def word_pattern(word: str):
	return re.compile(rf"(?<!{WORD_CHARS}){re.escape(word)}(?!{WORD_CHARS})")


def filter_spelling_changes(proposed, plain: str, dictionary) -> list[dict]:
	"""Keep only genuine, local spelling fixes that really occur in the text."""
	dict_lower = {w.lower() for w in dictionary}
	seen, out = set(), []
	for c in proposed or []:
		if not isinstance(c, dict):
			continue
		orig = (c.get("original") or "").strip()
		new = (c.get("corrected") or "").strip()
		if not orig or not new or orig == new or orig in seen:
			continue
		if len(orig.split()) > 3 or len(new.split()) > len(orig.split()) + 1:
			continue  # a rewrite, not a spelling fix
		if HAS_DIGIT.search(orig.translate(ARABIC_DIGITS)) or HAS_DIGIT.search(new.translate(ARABIC_DIGITS)):
			continue  # numbers and codes are never touched
		if orig.lower() in dict_lower or any(w.lower() in dict_lower for w in orig.split()):
			continue
		if re.search(r"[@/\\]|https?:", orig):
			continue
		if orig.isupper() and len(orig) <= 6:
			continue  # abbreviations: VAT, PO, KSA
		if difflib.SequenceMatcher(None, orig.lower(), new.lower()).ratio() < 0.5:
			continue  # too different to be a typo
		if not word_pattern(orig).search(plain):
			continue  # the model invented text that is not there
		seen.add(orig)
		out.append({"original": orig, "corrected": new})
	return out[:50]


def apply_changes(text: str, changes, is_html=False) -> str:
	"""Whole-word replacements; in HTML only inside text, never in tags or entities."""
	if not changes:
		return text
	parts = TAG_SPLIT.split(text) if is_html else [text]
	for i, part in enumerate(parts):
		if is_html and i % 2 == 1:
			continue
		for c in changes:
			part = word_pattern(c["original"]).sub(lambda m, r=c["corrected"]: r, part)
		parts[i] = part
	return "".join(parts)


def html_to_text(html: str) -> str:
	text = re.sub(r"<(br|/p|/div|/li|/h\d)[^>]*>", "\n", html or "", flags=re.I)
	text = re.sub(r"<[^>]+>", " ", text)
	text = html_lib.unescape(text)
	text = re.sub(r"[ \t]+", " ", text)
	text = "\n".join(line.strip() for line in text.split("\n"))
	return re.sub(r"\n{2,}", "\n", text).strip()


def text_to_html(text: str) -> str:
	paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]
	return "".join(f"<p>{html_lib.escape(p)}</p>" for p in paras)


# ----------------------------------------------------------------------------- translation safety
PROTECT_RE = re.compile(
	r"https?://[^\s<>\"']*[^\s<>\"'.,;:!?)\]]"                # URLs (no trailing punctuation)
	r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"        # emails
	r"|(?<![\w])(?:\+|00)?\d[\d\s\-()]{7,}\d(?![\w])"         # phone numbers
	r"|\b[A-Z]{1,6}-[A-Z0-9][A-Z0-9\-./]*\b"                  # document codes: CRM-LEAD-2026-0001, INV-42
	r"|\b(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9-]{1,}\b"  # model/part numbers: HP26A, X1
)


def protect(text: str, keep_terms=()):
	"""Replace things that must survive translation unchanged with numbered tokens ⟦n⟧."""
	tokens = []

	def _tok(value):
		tokens.append(value)
		return f"⟦{len(tokens)}⟧"

	for term in sorted({t for t in keep_terms if t and t.strip()}, key=len, reverse=True):
		text = re.sub(rf"(?<!{WORD_CHARS}){re.escape(term)}(?!{WORD_CHARS})", lambda m: _tok(m.group(0)), text)
	text = PROTECT_RE.sub(lambda m: _tok(m.group(0)), text)
	return text, tokens


def restore(text: str, tokens: list) -> tuple[str, list]:
	"""Put protected values back. Returns (text, missing_values)."""
	missing = []
	for i, value in enumerate(tokens, start=1):
		token = f"⟦{i}⟧"
		if token in text:
			text = text.replace(token, value)
		else:
			missing.append(value)
	text = re.sub(r"⟦\d+⟧", "", text)
	return text, missing


def html_segments(html: str):
	"""Split HTML into (parts, text_indexes): tags kept as-is, translatable text by index."""
	parts = re.split(r"(<[^>]*>)", html or "")
	idx = [i for i, p in enumerate(parts) if i % 2 == 0 and html_lib.unescape(p).strip()]
	return parts, idx


# ----------------------------------------------------------------------------- sales helpers
def parse_cadence(value: str, default=(2, 5, 10)) -> list[int]:
	try:
		days = [int(x) for x in re.split(r"[,\s]+", (value or "").strip()) if x]
	except ValueError:
		return list(default)
	days = [d for d in days if 0 <= d <= 90][:6]
	return days or list(default)


def clamp(value, low=0, high=30) -> int:
	try:
		v = int(float(value))
	except (TypeError, ValueError):
		v = low
	return max(low, min(high, v))
