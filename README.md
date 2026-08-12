# AlphaX CRM Automation

**Version 0.9.0** · Frappe / ERPNext v15 · © Neotec Integrated Solutions
See [CHANGELOG.md](CHANGELOG.md) for release history.

Compliance-grade CRM automation for **AlphaX** on Frappe/ERPNext v15.
Built by Neotec Integrated Solutions for the KSA/GCC market.

It plugs the five places a sales pipeline leaks — manual lead entry, unowned
leads, slow first response, dropped follow-ups, and dirty stage data — and adds
a local-AI assist layer plus PDPL retention controls.

---

## What it does

| Area | Capability |
|------|------------|
| **Intake** | Channel-agnostic webhook (`/api/method/...lead_intake.capture`) for web forms, Meta/Google lead ads, and WhatsApp. No human types a lead. |
| **De-dup** | Blocks or warns on duplicate email / mobile / phone before insert. |
| **Scoring** | Config-driven additive lead score (source, industry, status, territory, engagement). Hot leads auto-promote to Opportunities. |
| **Routing** | Seeds a next-contact date so follow-up SLAs have something to track. |
| **Follow-up SLA** | Daily scan for stale Leads/Opportunities → notify owner and/or least-loaded reassign. |
| **AI assist** | Local Ollama / Neotec AI Operator endpoint: lead classification (fit/urgency/intent), bilingual first-reply draft, opportunity briefs. Nothing leaves the host. |
| **PDPL** | Consent + lawful-basis tracking, consent audit trail, retention scheduler that anonymizes or deletes stale unconverted leads (Contract / Legal Obligation bases retained). |
| **Workflow** | Clean Lead stages (Lead → Contacted → Qualified → Converted / Disqualified). |

Everything is branded **AlphaX** (module, workspace, settings, notifications,
custom fields). It automates the underlying ERPNext Lead/Opportunity doctypes
rather than replacing them.

---

## Install (Frappe Cloud — no bench shell needed)

1. Push this app to a GitHub repo.
2. In Frappe Cloud → Bench → **Apps → Add App → From GitHub**, point at the repo.
3. Add the app to your site and let it migrate.

On install/migrate the app self-heals: it creates custom fields, default
settings + starter score rules, notifications, and the Lead workflow
automatically (`setup/install.py`, re-run by the `v0_1.install_defaults` patch).

CLI (if you do have bench):
```
bench get-app https://github.com/<you>/alphax_crm
bench --site <site> install-app alphax_crm
bench --site <site> migrate
```

Requires **ERPNext** (`required_apps = ["erpnext"]`).

---

## Configure

Open **AlphaX CRM Settings** (single doctype). Tune scoring rules, dedup,
follow-up days, stale thresholds/action, the local AI endpoint, and PDPL
retention. AI assist ships **off** — enable it after pointing `AI Base URL`
at your Ollama / NISA AI Operator host.

### Intake webhook

```
POST /api/method/alphax_crm.api.lead_intake.capture
Header:  X-AlphaX-Token: <Intake Webhook Token from settings>
Body (JSON):
{
  "lead_name": "Acme Co",
  "email_id": "buyer@acme.sa",
  "mobile_no": "+9665...",
  "source": "Website",
  "message": "Need ZATCA-ready POS for 12 branches",
  "consent": true,
  "lawful_basis": "Consent"
}
```
Returns `{"ok": true, "lead": "CRM-LEAD-...", "score": 40}`.

### WhatsApp Business intake

One endpoint handles Meta's verification handshake and inbound events:

```
GET/POST  /api/method/alphax_crm.api.whatsapp.webhook
```

Setup:
1. In **AlphaX CRM Settings → WhatsApp Business**, set the Phone Number ID,
   Access Token, App Secret, and a Verify Token (any secret string), then tick
   *Enable WhatsApp Intake*.
2. In the Meta App dashboard → WhatsApp → Configuration, set the **Callback URL**
   to the endpoint above and the **Verify Token** to the same value, and
   subscribe to the `messages` field.

Inbound messages are signature-verified (`X-Hub-Signature-256` against the App
Secret), de-duplicated by WhatsApp message id, resolved to an existing Lead by
phone or turned into a new one (source `WhatsApp`, lawful basis *Legitimate
Interest*), and threaded as a `Received` Communication — which feeds the same
scoring / AI pipeline. If *Send Auto-Acknowledgment* is on, a bilingual reply
goes out in the background (text within the 24-hour window, or a named template
outside it). Media can optionally be downloaded and attached to the Lead,
stored privately on the Frappe host (PDPL-local).

---

## Architecture

```
hooks.py
 ├─ doc_events
 │   Lead: before_insert (dedup, consent) · validate (score) · after_insert (promote, AI enqueue)
 │   Opportunity: validate (next activity) · after_insert (AI brief enqueue)
 │   Communication: after_insert (activity bump, rescore)
 ├─ scheduler_events.daily_long
 │   scan_stale_records · run_pdpl_retention
 └─ after_install / patch  → setup/install.py (idempotent)

api/lead_intake.py   token-secured intake endpoint
api/ai.py            local-AI client (classify / draft / summarize)  [background jobs]
crm/lead.py crm/opportunity.py crm/activity.py crm/tasks.py
doctype/alphax_crm_settings  ·  doctype/alphax_lead_score_rule
```

All AI / network work is enqueued (`frappe.enqueue`), never inline, so a slow
model never blocks a save.

---

© 2026 Neotec Integrated Solutions · support@neotec.ai
