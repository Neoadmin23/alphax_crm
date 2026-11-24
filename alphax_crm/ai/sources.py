"""Reading a lead's public website for the AI company brief (with SSRF protection)."""

from __future__ import annotations

import re
import socket
from urllib.parse import urljoin, urlparse

import frappe
import requests
from frappe import _

from alphax_crm.ai.pure import is_private_host

MAX_BYTES = 2_000_000
USER_AGENT = "Mozilla/5.0 (compatible; AlphaX-CRM/1.0)"


def _assert_public(url: str):
	"""Refuse URLs that resolve to internal addresses (protects the server's own network)."""
	parsed = urlparse(url)
	if parsed.scheme not in ("http", "https") or not parsed.hostname:
		frappe.throw(_("Only http and https web addresses can be read."))
	try:
		infos = socket.getaddrinfo(parsed.hostname, None)
	except socket.gaierror:
		frappe.throw(_("Could not find the website {0}.").format(parsed.hostname))
	for info in infos:
		if is_private_host(info[4][0]):
			frappe.throw(_("{0} points to a private network address and cannot be read.").format(parsed.hostname))


def fetch_page_text(url: str, max_chars: int = 12000) -> str:
	if not re.match(r"^https?://", url or "", re.I):
		url = "https://" + (url or "").strip()
	current = url
	for _hop in range(5):
		_assert_public(current)
		resp = requests.get(current, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
			timeout=20, allow_redirects=False, stream=True)
		if resp.status_code in (301, 302, 303, 307, 308):
			current = urljoin(current, resp.headers.get("Location", ""))
			continue
		break
	else:
		frappe.throw(_("Too many redirects while reading {0}.").format(url))
	if resp.status_code >= 400:
		frappe.throw(_("{0} returned HTTP {1}.").format(url, resp.status_code))
	raw = resp.raw.read(MAX_BYTES, decode_content=True)
	html = raw.decode(resp.encoding or "utf-8", errors="ignore")
	return html_to_text(html)[:max_chars]


def html_to_text(html: str) -> str:
	from bs4 import BeautifulSoup

	soup = BeautifulSoup(html or "", "html.parser")
	for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
		tag.decompose()
	parts = []
	if soup.title and soup.title.get_text(strip=True):
		parts.append(soup.title.get_text(" ", strip=True))
	meta = soup.find("meta", attrs={"name": "description"})
	if meta and meta.get("content"):
		parts.append(meta["content"].strip())
	parts.append(soup.get_text("\n", strip=True))
	return re.sub(r"\n{2,}", "\n", "\n".join(parts))
