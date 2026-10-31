"""AlphaX AI writing tools for CRM text fields: Arabic + English spell check, translation
(Arabic <-> English) and rewrite helpers (improve, formal, shorten).

Safety design
* Spell check: the model only proposes word-level fixes; this module applies them, so a
  sentence can never be reworded, and numbers, codes, abbreviations, links and company
  terms are never changed (see pure.filter_spelling_changes).
* Translate / rewrite: URLs, emails, phone numbers, document and part codes, and terms
  marked "Keep as is" are swapped for tokens before the call and restored afterwards;
  the result is checked for lost tokens and changed numbers and warns the user.
  Results are previews: nothing is written to a document until the user clicks Replace.
"""

from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint

from alphax_crm.ai import pure
from alphax_crm.ai.engine import AIError, complete_json
from alphax_crm.crm.utils import get_settings

TERM_DT = "AlphaX AI Term"
MAX_CHARS = 6000
ACTIONS = ("translate", "improve", "formal", "shorten")

DEFAULT_DOCTYPES = (
	"Lead\nOpportunity\nAlphaX PreLead\nAlphaX Smart Lead\nAlphaX Follow-up\nQuotation\n"
	"Customer\nProspect\nContact\nAlphaX Email Draft\nToDo\nEvent"
)
DEFAULT_DATA_FIELDS = "description\nremarks\nnotes\nnote\ndetails\nsubject\nsummary\nterms\nreason\nmessage\ncomment\nnext_action"

SPELL_PROMPT = """You are a careful spelling corrector for business text in Arabic, English, or both mixed.

Fix ONLY spelling mistakes and obvious typos, for example:
- English: "recieve" -> "receive", "teh" -> "the", "maintainance" -> "maintenance"
- Arabic: ta marbuta vs ha (الشركه -> الشركة), alif maqsura vs ya by context (علي/على), hamza forms (اسعار -> أسعار, مسؤل -> مسؤول), missing or swapped letters.

Never change meaning, grammar, word order, style or punctuation. Never change numbers, codes, units,
emails, URLs, brand, product, people or company names, abbreviations, or any word in the company
dictionary. Do not translate. Return each correction as a pair: the exact misspelled word or short
phrase as it appears in the text, and its correction. Return an empty list if nothing needs fixing."""

SPELL_SCHEMA = {
	"type": "object",
	"properties": {"changes": {"type": "array", "items": {"type": "object",
		"properties": {"original": {"type": "string"}, "corrected": {"type": "string"}},
		"required": ["original", "corrected"]}}},
	"required": ["changes"],
}

REWRITE_INSTRUCTIONS = {
	"improve": "Improve the wording: fix grammar and spelling, make it clear and natural, keep the same meaning, length and tone.",
	"formal": "Rewrite it in a polite, formal business tone suitable for Saudi/GCC clients. Keep the same meaning and facts.",
	"shorten": "Make it shorter and more direct (about half the length) while keeping every fact, number and commitment.",
}


# ----------------------------------------------------------------------------- config
def writing_enabled(settings=None) -> bool:
	settings = settings or get_settings()
	return bool(cint(settings.ai_enabled) and cint(settings.get("ai_writing_enabled")))


def _lines(value):
	return [x.strip() for x in re.split(r"[\n,]", value or "") if x.strip()]


def boot_session(bootinfo):
	"""Send the writing-tools config to the desk once per session."""
	if frappe.session.user == "Guest":
		return
	try:
		s = get_settings()
	except Exception:
		return
	if not cint(s.ai_enabled):
		return
	bootinfo.alphax_ai = {"enabled": 1}
	if not writing_enabled(s):
		return
	bootinfo.alphax_ai_writing = {
		"enabled": 1,
		"spell_mode": s.get("ai_spellcheck_mode") or "Suggest",
		"min_chars": cint(s.get("ai_spell_min_chars")) or 4,
		"doctypes": _lines(s.get("ai_writing_doctypes") or DEFAULT_DOCTYPES),
		"data_field_patterns": [x.lower() for x in _lines(s.get("ai_writing_data_fields") or DEFAULT_DATA_FIELDS)],
	}


def _model(settings):
	return settings.get("ai_fast_model") or settings.ai_model


def _check_access():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)
	if not writing_enabled():
		frappe.throw(_("AI writing tools are turned off in AlphaX CRM Settings."))


# ----------------------------------------------------------------------------- glossary
def terms():
	"""[{term, arabic, english, keep_as_is}] from AlphaX AI Term (cached)."""
	rows = frappe.cache.get_value("alphax_ai_terms", expires=True)
	if rows is None:
		rows = []
		if frappe.db.table_exists(TERM_DT):
			rows = frappe.get_all(TERM_DT, fields=["term", "arabic", "english", "keep_as_is"], limit=2000)
		rows = [dict(r) for r in rows]
		frappe.cache.set_value("alphax_ai_terms", rows, expires_in_sec=3600)
	return rows


def clear_terms_cache(doc=None, method=None):
	frappe.cache.delete_value("alphax_ai_terms")


def dictionary_words():
	words = set()
	for t in terms():
		for k in ("term", "arabic", "english"):
			if t.get(k):
				words.add(t[k].strip())
	return sorted(words)


@frappe.whitelist()
def add_term(word, keep_as_is=1):
	"""'+ dictionary' from the spelling box: the word is correct and must not be changed."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)
	word = (word or "").strip()
	if not word or len(word) > 140:
		frappe.throw(_("Invalid word"))
	if not frappe.db.exists(TERM_DT, {"term": word}):
		frappe.get_doc({"doctype": TERM_DT, "term": word, "keep_as_is": cint(keep_as_is)}).insert()
	clear_terms_cache()
	return word


# ----------------------------------------------------------------------------- spell check
@frappe.whitelist()
@rate_limit(limit=240, seconds=60)
def spell_check(text, is_html=0, doctype=None, docname=None):
	"""Return {"changes": [{original, corrected}], "corrected": str}."""
	_check_access()
	s = get_settings()
	text = text or ""
	is_html = cint(is_html)
	plain = pure.html_to_text(text) if is_html else text
	if (len(plain.strip()) < (cint(s.get("ai_spell_min_chars")) or 4) or len(plain) > MAX_CHARS
			or not re.search(pure.WORD_CHARS, plain)):
		return {"changes": [], "corrected": text}

	words = dictionary_words()
	model = _model(s)
	key = "alphax_spell:" + hashlib.sha1(json.dumps([plain, model, words[:500]], ensure_ascii=False).encode()).hexdigest()
	proposed = frappe.cache.get_value(key, expires=True)
	if proposed is None:
		user = (f"Company dictionary (always correct): {', '.join(words[:300])}\n\n" if words else "") \
			+ "Text to check:\n<<<\n" + plain + "\n>>>"
		try:
			data = complete_json(SPELL_PROMPT, user, schema=SPELL_SCHEMA, feature="spell_check",
				reference=(doctype, docname) if doctype and docname else None, model=model,
				max_tokens=800, timeout=cint(s.get("ai_writing_timeout")) or 30, temperature=0)
			proposed = [c for c in (data or {}).get("changes") or [] if isinstance(c, dict)]
		except AIError:
			return {"changes": [], "corrected": text}  # AI down: never block typing
		frappe.cache.set_value(key, proposed, expires_in_sec=7 * 24 * 3600)

	changes = pure.filter_spelling_changes(proposed, plain, words)
	return {"changes": changes, "corrected": pure.apply_changes(text, changes, is_html)}


# ----------------------------------------------------------------------------- translate / rewrite
@frappe.whitelist()
@rate_limit(limit=120, seconds=60)
def transform(text, action, target_language=None, is_html=0, doctype=None, docname=None):
	"""Preview a translation or rewrite. Returns {result, target_language, warnings}."""
	_check_access()
	if action not in ACTIONS:
		frappe.throw(_("Unknown writing action {0}").format(action))
	text = text or ""
	is_html = cint(is_html)
	plain = pure.html_to_text(text) if is_html else text
	if not plain.strip():
		frappe.throw(_("The field is empty."))
	if len(plain) > MAX_CHARS:
		frappe.throw(_("Text is too long for the AI writing tools ({0} characters max).").format(MAX_CHARS))

	source = pure.detect_language(plain)
	if action == "translate":
		target = target_language if target_language in ("Arabic", "English") else pure.other_language(source)
	else:
		target = source
	ref = (doctype, docname) if doctype and docname else None

	key = "alphax_xform:" + hashlib.sha1(json.dumps([text, action, target, is_html, len(terms())],
		ensure_ascii=False).encode()).hexdigest()
	cached = frappe.cache.get_value(key, expires=True)
	if cached:
		return cached
	try:
		if action == "translate" and is_html:
			result, warnings = _translate_html(text, target, ref)
		elif action == "translate":
			result, warnings = _translate_plain(plain, target, ref)
		else:
			result, warnings = _rewrite(plain, action, ref)
			if is_html:
				result = pure.text_to_html(result)
	except AIError as e:
		frappe.throw(str(e), title=_("AlphaX AI"))
	out = {"result": result, "target_language": target, "source_language": source, "warnings": warnings}
	frappe.cache.set_value(key, out, expires_in_sec=24 * 3600)
	return out


def _glossary_lines(target):
	lines = []
	for t in terms():
		if cint(t.get("keep_as_is")):
			continue
		src, dst = (t.get("english"), t.get("arabic")) if target == "Arabic" else (t.get("arabic"), t.get("english"))
		src = src or t.get("term")
		if src and dst:
			lines.append(f"- {src} => {dst}")
	return lines[:150]


def _keep_terms():
	return [t["term"] for t in terms() if cint(t.get("keep_as_is")) and t.get("term")]


def _translate_system(target):
	glossary = _glossary_lines(target)
	lang = "Modern Standard Arabic suitable for Saudi business readers" if target == "Arabic" else "clear, professional English"
	return (
		f"You are a professional business translator. Translate the user's text into {lang}.\n"
		"Rules: translate the meaning faithfully; keep the tone; do not add or remove information; "
		"keep every placeholder like ⟦1⟧ exactly as it is, in a sensible position; keep numbers as written; "
		"keep brand, product and company names in their original form; output only the translation."
		+ ("\nAlways use this company glossary:\n" + "\n".join(glossary) if glossary else "")
	)


def _translate_plain(plain, target, ref):
	protected, tokens = pure.protect(plain, _keep_terms())
	data = complete_json(_translate_system(target), protected,
		schema={"type": "object", "properties": {"translation": {"type": "string"}}, "required": ["translation"]},
		feature="translate", reference=ref, model=_model(get_settings()), max_tokens=2500, temperature=0.1)
	result, missing = pure.restore(str((data or {}).get("translation") or ""), tokens)
	return result.strip(), _warnings(plain, result, missing)


def _translate_html(html, target, ref):
	parts, idx = pure.html_segments(html)
	keep = _keep_terms()
	segments, token_sets = [], []
	for i in idx:
		seg, tokens = pure.protect(pure.html_lib.unescape(parts[i]), keep)
		segments.append(seg)
		token_sets.append(tokens)
	user = ("Translate each string in this JSON array. Return the same number of strings, in the same order.\n"
		+ json.dumps(segments, ensure_ascii=False))
	data = complete_json(_translate_system(target), user,
		schema={"type": "object", "properties": {"translations": {"type": "array", "items": {"type": "string"}}},
			"required": ["translations"]},
		feature="translate", reference=ref, model=_model(get_settings()), max_tokens=3000, temperature=0.1)
	out = (data or {}).get("translations") or []
	if len(out) != len(segments):
		raise AIError(_("The AI returned an incomplete translation. Please try again."))
	missing_all = []
	for n, i in enumerate(idx):
		restored, missing = pure.restore(str(out[n]), token_sets[n])
		missing_all += missing
		lead = re.match(r"^\s*", parts[i]).group(0)
		trail = re.search(r"\s*$", parts[i]).group(0)
		parts[i] = lead + pure.html_lib.escape(restored.strip(), quote=False) + trail
	result = "".join(parts)
	return result, _warnings(pure.html_to_text(html), pure.html_to_text(result), missing_all)


def _rewrite(plain, action, ref):
	protected, tokens = pure.protect(plain, _keep_terms())
	system = (
		"You are a writing assistant for a B2B sales team in Saudi Arabia. " + REWRITE_INSTRUCTIONS[action]
		+ " Write in the same language as the input (Arabic stays Arabic, English stays English, mixed stays mixed)."
		" Keep every placeholder like ⟦1⟧ exactly as it is. Keep numbers as written. Do not invent facts,"
		" prices or commitments. Output only the rewritten text."
	)
	data = complete_json(system, protected,
		schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
		feature=f"rewrite_{action}", reference=ref, model=_model(get_settings()), max_tokens=2000, temperature=0.3)
	result, missing = pure.restore(str((data or {}).get("text") or ""), tokens)
	return result.strip(), _warnings(plain, result, missing)


def _numbers(text):
	return sorted(re.findall(r"\d+(?:[.,]\d+)*", (text or "").translate(pure.ARABIC_DIGITS).replace(",", "")))


def _warnings(source, result, missing):
	warnings = []
	if not result.strip():
		raise AIError(_("The AI returned an empty result. Please try again."))
	if missing:
		warnings.append(_("These values were dropped by the AI and are missing from the result: {0}").format(
			", ".join(missing[:5])))
	if _numbers(source) != _numbers(result):
		warnings.append(_("The numbers in the result differ from the original. Please check them."))
	return warnings
