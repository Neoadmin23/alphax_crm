# Changelog — AlphaX CRM Automation

All notable changes to `alphax_crm`. Versions follow the app version in
`alphax_crm/__init__.py`, `hooks.py` (`app_version`) and `setup.py`.

## [0.31.0] — 2026-10-01
### Fixed — WF-06 closure controls duplicated fields already on the Lead form
0.30.0's "Closure Controls (WF-06)" section added four new custom fields
(`alphax_contract_status`, `alphax_won_lost_date`, `alphax_lost_reason`,
`alphax_lost_detailed_reason`) without checking that this site's Lead
doctype already carried the same four things on native fields:
`custom_contract` (Contract), `won_or_lost_date` (Won Or Lost Date), and
the core "Lost with reason" transition's own `lost_reason` (Link to Lead
Lost Reason) / `detailed_reason`. Result: two closure sections on the Lead
form, and the "Enter details" dialog from the core Lost-with-reason
transition popping up on top of our own section asking for the same
Contract/Won-or-Lost-Date/Lost-Reason/Detailed-Reason values a second time.

- `setup/install.py`: removed the duplicate field definitions from
  `setup_custom_fields()`; `crm/stage_flow.py`'s WF-06 enforcement
  (`_enforce_won`/`_enforce_lost`) now reads the native fields
  (`custom_contract`, `won_or_lost_date`, `lost_reason`, `detailed_reason`)
  instead.
- New `retire_duplicate_closure_fields()`, run from `after_migrate`: for
  sites that already have the legacy fields, copies any data on them onto
  the native fields (creating a matching **Lead Lost Reason** record for a
  legacy free-text reason if none exists) without overwriting anything
  already filled in on the native side, then deletes the four legacy
  Custom Fields and their section/column break. Idempotent — once the
  legacy fields are gone it's a no-op on every later migrate.
- `crm/tasks.py`'s Lost Quotation digest now reads `lost_reason` instead of
  the retired `alphax_lost_reason`.
- AlphaX CRM Settings' Closure Controls (WF-06) section description updated
  to name the actual native field labels instead of "the Lead form's own
  Closure Controls section" (which no longer exists).

## [0.30.0] — 2026-09-30
### Added — WF-02/03 quotation notifications, WF-05 stage SLA engine, Postponed follow-up seeding, Lost Quotation digest
Extends Phase 1 with the pieces of WF-02/03/05 that don't depend on the
Lead↔Quotation link (still phase 2) — plus a full rework of the customer's
requested revisions to the original spec. Every rule here is configured in
AlphaX CRM Settings, not hardcoded, including one setting that resolves an
open question from the original review: **Approver Role** (default "Sales
Manager") now defines what "Approver"/"Sales Manager" means everywhere this
app notifies one, in one place.

**WF-02/03 — Quotation submit notification**
- New `crm/quotation.py`, hooked to core Quotation's `on_submit`: every
  submitted Quotation notifies every user holding the Approver role, with
  the amount, party and submitter — independent of any Lead link, so it
  works today, not after phase 2.
- Toggle: `notify_approvers_on_quotation` (default on).

**WF-05 — Configurable per-stage SLA engine**
- New child doctype `AlphaX Lead Stage SLA` (Stage, Days In Stage, Notify
  [Lead Owner / Approver / Both], Only If No Activity, Label) and a new
  `stage_sla_rules` table — one row per reminder or escalation milestone,
  any number of rows per stage. "Days in stage" is measured from the Lead's
  most recent transition into that stage (AlphaX Stage Transition Log),
  falling back to its creation date if it started there.
- New scheduled job `run_stage_sla_rules` (daily) fires each milestone
  exactly once (deduped via a Notification Log existence check, so re-runs
  never double-send — the "no duplicate reminders" control the spec's
  General Controls section asks for).
- Seeded defaults implement the customer's requested revisions directly:
  - **Lead**: two-stage reminder — Day 3, then Day 7 (4 days after the
    first), both to the Lead Owner — replacing the original Day 1
    reminder / Day 3 escalation.
  - **Interested**: Day 3 reminder (owner), Day 7 escalation (Approver) —
    unchanged from the spec.
  - **Qualified lead**: Day 5 reminder (owner), Day 10 escalation
    (Approver) — unchanged.
  - **Contract Under Signing**: Day 3/6/9 follow-ups (owner), a dedicated
    **Day 4 Approver check-in** (the customer's new addition, unconditional
    — not gated on "no activity"), and the original Day 10 escalation.

**WF-05 — Postponed handling**
- New scheduled job `run_postponed_followups`: on a Postponed Lead's Next
  Contact Date (or `postponed_default_revisit_days`, default 30, after
  entering the stage if no date was set), reminds the Lead Owner; if it's
  overdue with no activity since, also alerts the Approver — the customer's
  requested addition ("notify Sales Managers if no comment has been added").
- New `crm.lead._seed_postponed_followup`: the moment a Lead enters
  Postponed, an empty **AlphaX Follow-up** record is created automatically
  (no next-follow-up date set) so there's something to fill in and track —
  closing the gap the customer flagged ("we don't have it right now").
  Won't create a second one while a blank one is still pending.

**Daily Lost Quotation digest**
- New scheduled job `run_lost_quotation_digest`: every Approver gets one
  daily list of every Lead currently at the configured "Lost Quotation"
  stage (owner + lost reason), so a closed-lost deal doesn't just vanish
  from view. Toggle: `lost_quotation_digest_enabled`.

**Known simplification, flagged rather than silently assumed:** "activity"
for the no-activity checks above is this app's existing
`alphax_last_activity` signal (any Communication, Comment, or status
change) — not yet the fuller WF-04 qualifying-activity list (meeting/event,
CRM note, closed ToDo), which needs those integrations built out first.
Also, Frappe's `daily_long` scheduler (used here, matching every other job
in this app) runs once every 24 hours but not pinned to a specific clock
time — the spec's "08:00 Riyadh time" for quotation follow-ups isn't
enforced yet; a `cron`-based hook would be needed for that, flagged for
phase 2 alongside the Quotation link itself.

## [0.29.0] — 2026-09-30
### Added — Approved Lead Workflow, Phase 1: Stage Progression Control (WF-01) + Closure Controls (WF-06)
First phase of implementing the "A. APPROVED LEAD WORKFLOW" spec, scoped
deliberately to the two self-contained, highest-compliance-value, lowest-risk
pieces (per the earlier review): stopping a Lead Stage from skipping steps,
and requiring the right fields before a Lead can be closed Won or Lost.
Every open design question from that review is resolved as an
**admin-configurable setting**, not a hardcoded assumption — per instruction,
so AlphaX CRM Settings, not code, is what defines the actual rules.

**WF-01 — Stage Progression Control**
- New child doctype `AlphaX Lead Stage Transition` (From Stage / To Stage,
  plain Data fields — deliberately not Select, to never repeat the 0.28.0
  option-mismatch bug class) and a new `stage_transitions` table on AlphaX
  CRM Settings: only a Lead Stage change matching a listed From→To pair can
  be saved; anything else is treated as skipping a step and blocked with a
  clear message. An empty table disables the check entirely (fail-open,
  same posture as the Data Quality Gate before its first rule).
- Seeded on install/migrate with the spec's own diagram (Lead → Interested
  → Qualified lead → Quotation → Postponed / Contract Under Signing → Won /
  Lost with reason / Lost Quotation) — the *starting point*, fully editable
  afterward with no code change.
- New `stage_flow_bypass_roles` setting (default: System Manager, Sales
  Manager) lets specific roles correct a Lead directly, for the exceptions
  every approved flow eventually needs.
- Enforced in `crm.lead.validate()` (`crm/stage_flow.py`), so it can't be
  bypassed by editing the field directly — unlike a client-side check.

**WF-06 — Closure Controls**
- Four new fields on Lead (new collapsible "Closure Controls" section):
  **Contract** (Select: Blank/Signed), **Won/Lost Date**, **Lost Reason**,
  **Detailed Reason**.
- A Lead cannot be saved at the configured "Won" stage unless Contract is
  the configured signed value, Won/Lost Date is set, and — unless turned
  off — a Customer record exists linking back to this Lead (created via the
  Lead's own "Create > Customer").
- A Lead cannot be saved at a configured "Lost" stage (default: "Lost with
  reason", "Lost Quotation") unless Lost Reason, Detailed Reason and
  Won/Lost Date are all filled in.
- Which stage value means "Won", which mean "Lost", and what "signed"
  means are all settings (`won_stage_value`, `lost_stage_values`,
  `contract_signed_value`) — renaming a stage later doesn't need a patch.
- The "linked Quotation must be marked Lost" half of the "Lost Quotation"
  rule is intentionally NOT included yet — there's no Lead↔Quotation link
  in the app at all (that's WF-02/03/04, phase 2). Closure still requires a
  reason today; the quotation cross-check follows once that link exists.

Not yet built (next phases, as scoped in the original review): the
Quotation link (WF-02–04), the shared business-hours/SLA engine (WF-05),
and the AI intent/scoring additions (WF-07).

## [0.28.0] — 2026-09-30
### Fixed — Lead save blocked past "Qualified lead" / on "Won" (production, irsaa.muftaah.com)
Root cause, confirmed live from the exact error text (`Lead Stage cannot be
"Qualified lead". It should be one of "Lead", "Open", "Replied",
"Opportunity", "Quotation", "Lost Quotation", "Interested", "Converted", "Do
Not Contact"`): `setup/install.py`'s seeded default Lead Status -> Lead
Stage mapping (`_default_lead_stage_map`) names Lead Stage values —
"Qualified lead", "Postponed", "Contract Under Signing", "Won", "Lost with
reason" — that were never added as options on Lead's native `status` Select
field. The automation in `crm.lead._sync_stage_from_status` tries to write
one of these into `status` the moment an agent's Lead Status choice maps to
one of them, and Frappe's own core Select validation rejects it outright —
this is what was surfacing as "the system refuses to save," for every user,
for every Lead Status past the first couple of pipeline stages.

- New `crm.utils.ensure_select_option(doctype, fieldname, value)`: adds a
  value to a Select field's allowed options via a Property Setter (the same
  mechanism Customize Form itself uses) if it's missing, and clears the
  doctype cache. No-ops once the option already exists.
- `crm.lead.sync_lead_stage_options(settings)`: walks every row of Lead
  Stage Map and ensures each target value is a legal `status` option.
  - Runs on `after_install/after_migrate`, right after the map is seeded —
    fixes this on every existing site the next time it deploys/migrates.
  - Runs on every **AlphaX CRM Settings** save (new `on_update` hook) — so
    typing a brand-new stage name into the mapping table just works
    immediately, with no separate Customize Form step and no waiting for a
    migrate. This is the general fix, not a one-off patch: it's what makes
    Lead Stage Map safely admin-configurable at all.
  - Also runs defensively inside `_sync_stage_from_status` itself, right
    before every automatic stage write, as a last-line guard against the
    mapping and the field ever drifting apart again.
- The new Property Setter is added to `hooks.py`'s exported `fixtures`
  (scoped narrowly to `Lead.status`'s options — not every Property Setter on
  the site).

No mapping values changed — "Qualified lead", "Won", etc. are exactly what
was configured; they just needed to actually be legal `status` values, which
they now are, automatically, on this deploy's migrate.

## [0.27.0] — 2026-09-29
### Added — Secure Remote Access for AI Assist (named tunnel + Cloudflare Access)
0.26.0 fixed "Ask AI" so it reliably opens; testing it live then surfaced the
next real gap: the AI backend call itself was failing, because there is no
network path from Frappe Cloud into a machine on an office LAN — reaching a
laptop/network-hosted Ollama instance necessarily means *something* is
reachable from the internet. The quick tunnel (`*.trycloudflare.com`, already
generated by the existing setup script in `api/ai_setup.py`) is fine to prove
that out, but it's a bare, unauthenticated public URL that rotates on every
restart — not something to run AI traffic through long-term.

Added a "Secure Remote Access" section to **AlphaX CRM Settings > AI Assist**
for the production upgrade path already flagged as a follow-up in the
existing setup script's own output message: a **named Cloudflare Tunnel**
(fixed address) locked down with **Cloudflare Access** service-auth, so
Cloudflare rejects any request at its edge — before it ever reaches the
tunnel — unless it carries a valid Service Token. Two new fields,
**CF-Access-Client-Id** and **CF-Access-Client-Secret**, are sent as request
headers on every call to the AI endpoint (`CF-Access-Client-Id` /
`CF-Access-Client-Secret`), stacking with the existing optional API-key
Authorization header rather than replacing it.

- New shared helper `alphax_crm.crm.utils.ai_request_headers()` builds these
  headers once; `api/ai.py`, `api/ai_query.py` and `api/ai_setup.py`'s
  connection tester all call it now instead of each building headers by
  hand, so the three call sites can no longer drift out of sync on auth.
- `AlphaX CRM Settings` gets a new collapsible "Secure Remote Access" section
  with step-by-step instructions (tunnel creation, DNS route, Access
  application + Service Token) and the two new credential fields.
- **Test AI Connection** now exercises these headers too (an unsaved Client
  Id can be tried before Save; the Client Secret, like the API key, is only
  ever read from the saved settings, since Password fields never reach the
  browser).

## [0.26.0] — 2026-09-29
### Changed — "Ask AI" moved from a floating button to toolbar buttons
Requested directly, after three straight releases fighting a floating
"Ask AI" circle that depended on `frappe.ready()` to know when it was safe
to touch the page — and `frappe.ready` turned out to simply not exist on
this site at all (0.25.4's finding). Rather than keep hardening a
self-injecting floating button against a boot sequence it can't reliably
observe, "Ask AI" now lives where every other AlphaX action already lives:
the list view's and form's own toolbar, using the exact same
`add_inner_button`/`add_custom_button` mechanism as "Log Follow-up",
"Import Logs" and "Executive Dashboard" already use successfully.
- This isn't just a workaround — it's a strictly better fit: a toolbar
  button only ever runs from a click, by which point the page is
  unquestionably loaded and `frappe`/jQuery/session are all available. There
  is no readiness race left to depend on, at all, on any site.
- **AlphaX PreLead**: "Ask AI" inner button on the list, next to Smart
  Import and Import Logs; "Ask AI" custom button on the form, in the
  AlphaX group.
- **Lead**: same — a new `lead_list.js` adds the list button (Lead is a
  core ERPNext doctype, so this goes through the `doctype_list_js` hook
  rather than the doctype-folder convention AlphaX PreLead's list uses),
  and the form button sits next to "Check Data Quality".
- **Opportunity**: "Ask AI" custom button added to the form toolbar.
- `alphax_ai_assistant.js` no longer self-injects anything on page load —
  it now just defines `window.alphax_open_ai_assistant(context)` plus two
  small helpers (`alphax_ai_form_context`, `alphax_ai_list_context`) that
  every doctype's own list/form script calls into, the same pattern already
  used for `window.alphax_log_followup`/`alphax_log_call` in `alphax_call.js`.
  All the dialog/table/chart logic itself is unchanged.

## [0.25.4] — 2026-09-29
### Fixed — `frappe.ready` doesn't exist at all on this site, not a timing race
0.25.3 assumed `frappe.ready` would show up eventually and polled for it for
20 seconds. Live evidence says otherwise: the console log showed 100+ retry
attempts, the full 20-second budget, and then "Gave up waiting for
frappe.ready" — while the rest of the desk (dialogs, forms, other buttons)
worked normally the entire time. `frappe.ready` isn't merely late on this
build, it's absent.
- Replaced the `frappe.ready` dependency with jQuery's own `$(fn)`
  DOM-ready, which this file already hard-depends on anyway (the button
  itself is built with `$(...)`). Once the DOM is ready, it polls briefly
  for `frappe.session.user` (written into the page inline as part of
  `frappe.boot`, so normally already present by then) before injecting the
  button — no dependency on any Frappe-specific readiness hook at all now.
- Verified with a simulation where `frappe.session` appears but
  `frappe.ready` never exists anywhere, matching the exact bug reported:
  the button now injects correctly.

## [0.25.3] — 2026-09-29
### Fixed — Ask AI button crash: `frappe.ready is not a function`
Root cause found from the browser console, using the diagnostic log added
in 0.25.2 — the very next line after "loaded" threw:
`Uncaught TypeError: frappe.ready is not a function`, at the top of the
script. On this site, `app_include_js` scripts can apparently execute
before Frappe's own core library has finished setting `frappe.ready` up —
so the very first line of real code in this script crashed immediately,
and the floating button was never injected. Not a deployment/caching
problem after all (that was a reasonable first guess, ruled out directly by
the console showing the "loaded" line every time).
- The script now waits for `frappe.ready` to actually exist (polling every
  100ms, up to ~20s) before using it, instead of assuming it's already
  there the instant this file runs. Verified with a standalone simulation:
  the button now injects correctly whether `frappe.ready` is available
  immediately or only appears later.
- If `frappe.ready` never shows up within ~20s (a genuinely broken page),
  it now logs `[AlphaX CRM] Gave up waiting for frappe.ready` instead of
  failing silently forever.

## [0.25.2] — 2026-09-29
### Investigating — global "Ask AI" button not appearing
Reported directly: the Executive Dashboard crash (fixed in 0.25.1, see
below — same report) was accompanied by "I am not finding the AI button
anywhere." The button's own code hasn't changed: `alphax_ai_assistant.js`
unconditionally injects a floating circular button on every desk page for
any logged-in user, via `app_include_js` (added in 0.23.0). Nothing in this
codebase gates it on a setting, a role, or Ollama being configured — it
should simply always be there. Given the 0.25.1 finding just above (a
version string that hadn't been current since 0.18.1 despite the code
itself being current), the most likely explanation is the same kind of gap
between "the file exists in the app" and "the browser actually received
it": a new entry in `app_include_js` needs the site's JS assets rebuilt
(`bench build`) and the browser cache cleared/hard-refreshed to pick it up
— dropping the file into the app's folder alone isn't enough.
- Added a console log at the very top of `ai_assistant.js`, outside every
  other check, so opening the browser console (F12) gives an immediate,
  unambiguous answer: if `[AlphaX CRM] ai_assistant.js loaded` is
  **missing**, the asset never reached the browser — a deploy/build/cache
  problem, not a bug in the script, and the fix is a fresh `bench build` +
  `bench migrate` + hard refresh (Ctrl/Cmd+Shift+R). If it's present but
  `[AlphaX CRM] Ask AI button injected` never follows, the console will now
  show the actual JavaScript error instead of a silent no-op.
- No functional change to the button or the AI Assistant itself — this is
  purely a diagnostic aid to find out which of the two situations it is.

## [0.25.1] — 2026-09-29
### Fixed — Executive Dashboard crash, and version-reporting mismatch
Both found from a real production error report (500 on opening the
Executive Dashboard) rather than testing in isolation.
- **`AttributeError: module 'frappe' has no attribute 'has_role'`** —
  `api/dashboard.py`'s `_require_management()` called a function that
  doesn't exist on the `frappe` module; role membership is checked with
  `frappe.get_roles()` (defaults to the current session user) instead. This
  broke the Executive Dashboard entirely for every user, including Sales
  Manager/System Manager, since the check ran (and crashed) before it could
  ever say yes.
- **App version reporting was stuck at 0.18.1** — every release since has
  bumped `VERSION` and `hooks.py`'s `app_version`, but never
  `alphax_crm/__init__.py`'s `__version__`, which is the value Frappe's own
  error pages and "App Versions" panel actually read. Purely a diagnostic
  accuracy fix — the installed code itself was current — but it's exactly
  why a traceback reported "0.18.1" long after 0.24.0's features (the
  dashboard itself) were already live. All three now move together.

## [0.25.0] — 2026-09-29
### Added — Smart Import: update existing records, content-aware column detection, multi-mobile combine
Requested directly: an "update existing" mode matched on company name, a
smarter Smart Import that understands column *content* (not just header
text) to name columns itself, and combining multiple mobile-number columns
instead of keeping only the first. All three run automatically on every
import — none of this is an opt-in step to remember, except "update
existing" itself, which is a deliberate choice per import (like "skip
duplicates") since it changes existing data rather than only adding to it.

- **Update existing records, matched by company name** — a new "Update
  existing records" checkbox in the import dialog. When a row's company
  name matches a record already in the system (company_name on
  Lead/PreLead, organization on Smart Lead), Smart Import fills in only the
  fields that record is currently missing — it never overwrites data
  that's already there. Matched rows get a new "Updated" status (own color
  in the result Excel, own count on the AlphaX Import Log, own line in the
  summary dialog), distinct from "Merged" (which is specifically for two
  rows of the *same import file* landing on the same contact).
- **Content-based column detection** — when a column's header text doesn't
  match anything Smart Import recognizes (wrong language, unexpected
  wording — "Cell #", "رقم١"), it now looks at a sample of the column's
  actual values: values that are unmistakably email addresses, phone
  numbers or website URLs get mapped automatically, at a 70% match
  threshold over at least 2 samples so a single odd value in an unrelated
  column can't hijack it. Deliberately narrow: company name and person name
  are NOT guessed from content — those value shapes are too easy to guess
  wrong, so they stay header/alias-based only. Wired into both the
  automatic import path and the "Correct Columns" dialog's pre-filled
  suggestions.
- **Multiple mobile-number columns combined, not first-wins** — a file with
  two (or three) mobile-labeled columns used to keep only the first
  non-blank value per row and silently drop the rest. Now every distinct
  number survives: the first goes to Mobile No as before, and any further
  distinct numbers spread into Phone / WhatsApp No (whichever of those the
  target doctype has and doesn't already have its own dedicated source
  column). The same number typed in two different formats in two columns is
  recognized as one number, not duplicated across two fields.
- Verified with a stubbed-Frappe test harness: content sniffing correctly
  guessing email/phone columns and correctly declining a below-threshold
  column; three-way mobile/phone/whatsapp distribution with dedup; and the
  update-existing path filling only blank fields, never touching populated
  ones, across both the `company_name` and `organization` company-field
  spellings.

## [0.24.0] — 2026-09-29
### Added — four analytic reports and an Executive Dashboard
Requested directly: analytic reports with required filters, plus a
management-quality dashboard, aimed at the bar set by Salesforce/Zoho. The
app already had operational reports (follow-ups due, idle/activity
monitoring, stage-transition day-gaps); this adds the management-analytics
layer on top: pipeline value, source ROI, win/loss, and a leaderboard, all
restricted to Sales Manager / System Manager.

**New Script Reports** (all require a From/To date range filter):
- **AlphaX Sales Pipeline & Forecast** — open Opportunity value by sales
  stage, plus a probability-weighted forecast, filterable by territory/owner.
- **AlphaX Lead Source Performance** — PreLead capture and conversion, and
  Lead win rate, per source — two funnel halves shown separately since a
  source that captures well but converts poorly is a different problem from
  one that converts well but barely captures anything.
- **AlphaX Win/Loss Analysis** — won vs lost deals and win rate, grouped by
  month, territory or owner.
- **AlphaX Sales Leaderboard** — per salesperson: deals won and value in the
  selected period, win rate, average deal size, an approximate average
  sales-cycle length, alongside their CURRENT open pipeline (a live
  snapshot, deliberately not bounded by the same date filter, since "what
  did you close" and "what are you carrying right now" are both real
  questions a manager asks).
- None of these hardcode which Opportunity status means "won" or "lost" —
  both are read from two new AlphaX CRM Settings fields (Sales Analytics
  section: `won_status`/`lost_status`, defaulting to "Converted"/"Lost")
  since that vocabulary is configured per install, not fixed. The AI
  Assistant's conversion-funnel question (v0.23.0) was quietly relying on a
  hardcoded "Closed Won" that likely never matched anything on this site —
  fixed to read the same setting.
- Lead Source Performance goes further: it treats whichever Lead Stage(s)
  in the existing Lead Stage Automation mapping contain the word "won" as
  the win signal, rather than assuming the installed default's exact
  wording — verified directly with a customized mapping in a test harness.

**New: AlphaX Executive Dashboard** (`Page`, route
`alphax-executive-dashboard`, linked from the PreLead list's AlphaX menu for
Sales Manager/System Manager) — one screen: 9 KPI tiles (new PreLeads/Leads,
conversion rate, deals won, won value, win rate, open pipeline, average
cycle days, overdue follow-ups), open pipeline by stage, top lead sources,
a 6-month trend (new PreLeads vs deals won), and a top-5 leaderboard.
Built as a custom Desk Page with its own styling (gradient KPI tiles, a red
variant when follow-ups are overdue) rather than assembled from stock
Number Card/Dashboard Chart widgets, so it reads as a distinct product
surface rather than a generic Frappe dashboard — charts use Frappe's own
bundled charting library, no external script loaded.

New files: `alphax_crm/api/dashboard.py`,
`alphax_crm/alphax_crm/page/alphax_executive_dashboard/`, four new
`alphax_crm/alphax_crm/report/…` folders. Settings gained a "Sales
Analytics" section (`won_status`, `lost_status`,
`dashboard_default_range_days`).

## [0.23.0] — 2026-09-29
### Added — global AI Assistant: ask anything, anywhere, with tables and charts
Requested directly after confirming the AI connection worked: more AI
support at every screen, plus a global query box, with reports and
graphical output. Added a floating "Ask AI" button available on every desk
page (form, list, report — anywhere), backed by the same local AI server
already configured in Settings.
- New `alphax_crm/api/ai_query.py`. A question is never turned into raw SQL
  or handed to the model to run freely — the model only ever picks a
  *capability name* plus a few parameters from a small, explicit allow-list
  (doctype by doctype, field by field, declared in `ALLOWED`), and every
  parameter it returns is re-validated against that allow-list in Python
  before it touches a query. An invented or injected fieldname is dropped,
  not executed — verified directly (disallowed doctype, disallowed
  group-by field, and a non-scalar filter value are all rejected before
  reaching any query).
- Every query runs through `frappe.get_list` with the ASKING USER'S OWN
  permissions (never `ignore_permissions`) — the assistant is a faster way
  to ask, not a way around a Sales User only seeing their own records.
- Six built-in capabilities covering the questions this kind of CRM gets
  asked most: `aggregate` (count/sum/avg any allow-listed field, grouped —
  "how many leads by source this month"), `list_records` (a filtered list),
  `pipeline_value` (Opportunity amount by stage/status/territory),
  `conversion_funnel` (PreLead → converted → Opportunity → Won),
  `overdue_followups` (from the existing AlphaX Follow-up doctype), and
  `stage_durations` (from the existing Lead Stage Automation day-gap
  tracking — so a question like "which stage transition is slowest" now has
  a direct answer instead of only a script report).
- A question that isn't about CRM data at all (a how-to, a definition) gets
  a plain conversational answer instead of a forced, wrong query.
- The final sentence the user reads is written by a *second* model call
  that is only shown the actual queried rows — it cannot invent a number
  that isn't in that result set.
- Answers can include a data table (first 20 rows shown) and, where it
  makes sense, a bar chart rendered with Frappe's own bundled charting
  library (no external script loaded).
- The assistant knows what you're looking at: opened from a Lead/
  Opportunity/PreLead form or a list view, the current record/list is sent
  as context so "summarize this" or a follow-up question doesn't need you
  to repeat which record you mean.
- New file: `public/js/alphax_ai_assistant.js`, added to `app_include_js`
  so it loads on every desk page. Reuses the existing `ai_enabled`/
  `ai_base_url`/etc. settings — no separate on/off switch to configure.

## [0.22.3] — 2026-09-28
### Fixed — cloudflared install failed on a freshly-opened PowerShell window
Reported directly from a live run: Ollama installed and the model pulled
fine (`llama3.1:8b`, 4.9GB, verified), then it failed at
`Start-Process -FilePath "cloudflared" ...` with "The system cannot find
the file specified."
- Root cause: `winget install ... Cloudflare.cloudflared` updates the
  Machine/User PATH in the registry, but the PowerShell process already
  running (the one executing this very script) keeps the PATH it started
  with — it has no way to see that update until a *new* window is opened.
  So the very next line, still in the same process, couldn't find
  `cloudflared` even though winget had just reported success.
- Fixed by downloading `cloudflared.exe` directly to the same config folder
  the script already uses (`C:\AlphaX\AI\cloudflared.exe`) instead of going
  through winget, and always invoking it by that full path — no PATH
  dependency at all. Also refreshed `$env:Path` right after an Ollama
  install for the same reason, protecting the equivalent first-run case
  (Ollama not previously installed) that this test run happened not to hit.
- `alphax_crm/api/ai_setup.py`: Windows script only — macOS/Linux install
  cloudflared to locations already on PATH by default (Homebrew's bin dir,
  `/usr/local/bin`) so they were not affected.

## [0.22.2] — 2026-09-28
### Added — setup script checks RAM/disk before installing anything
Requested directly: check whether the target machine can actually handle
the chosen model size before running the install. Each setup script (all
three OSes) now starts with a resource check, not the AlphaX CRM Settings
GUI — the browser downloading the script is often an admin's own laptop,
not the machine the script will actually run on, so the check has to happen
on the real target to mean anything.
- Reads actual total RAM and free disk space on the machine (Windows:
  `Get-CimInstance Win32_ComputerSystem` / `Get-PSDrive`; macOS: `sysctl
  hw.memsize` / `df`; Linux: `/proc/meminfo` / `df`) and compares against
  conservative minimums per model (`AlphaX CRM Settings` GUI dropdown now
  shows them too): Small (llama3.2:3b) wants 8GB RAM / 5GB disk, Medium
  (llama3.1:8b) wants 16GB RAM / 10GB disk.
- If the machine falls short, prints exactly which resource is short and by
  how much, and asks for an explicit "type YES to continue" before doing
  anything further — machines that meet spec (the common case) sail through
  with no prompt at all, so this doesn't reintroduce the "stuck waiting for
  input" problem v0.22.1 just removed.
- `alphax_crm/api/ai_setup.py`: `MODEL_SIZES` now carries `min_ram_gb`/
  `min_disk_gb` alongside each model tag, substituted into the generated
  script the same way the model itself already was.

## [0.22.1] — 2026-09-28
### Changed — Ollama setup script is now a double-click, not a terminal session
Feedback from actually running v0.22.0's script live: PowerShell's own
copy/paste handling reversed multi-line pastes and the interactive "Enter 1
or 2" model prompt was an easy place to get stuck (running the raw text
instead of the file, forgetting the execution-policy flag, etc.). Moved
everything that used to be a terminal interaction into the AlphaX CRM
Settings GUI instead:
- **Download AI Server Setup Script** now opens a small dialog asking for
  model size (Small/Medium) *before* the file downloads — the choice is
  baked directly into the generated script, so the machine that runs it is
  never asked anything.
- **Windows**: the download is now a single `.bat` file. Double-click it —
  no PowerShell window to open, no execution-policy command to type. (The
  PowerShell logic is embedded as a base64 `-EncodedCommand`, so there's
  still just one file and no quoting issues from the script's own braces.)
- **macOS**: the download is now a `.command` file, which double-clicks to
  open Terminal and run itself (right-click → Open the first time, since
  macOS blocks unsigned downloaded scripts on a plain double-click).
- **Linux** stays a terminal `bash file.sh` run — no universal double-click
  convention across desktop environments — but the model prompt is gone
  there too.
- `alphax_crm/api/ai_setup.py`: `download_setup_script` now takes
  `model_size` ("small"/"medium"); Windows path returns the `.bat` wrapper.

## [0.22.0] — 2026-09-28
### Added — Smart Import now keeps a permanent, downloadable result log
Every Smart Import run (sync or background) now creates an **AlphaX Import
Log** record and attaches a result Excel to it: the original file's own
columns, in the original row order, plus two new columns — **Import
Status** (Imported / Merged / Skipped / Failed) and **Error Message** — with
each row shaded green/yellow/red for quick scanning. A failed row can be
fixed directly in that downloaded file and re-uploaded.
- New doctypes: `AlphaX Import Log` (one per run — counts, source file name,
  who ran it, the attached result Excel) and its child table `AlphaX Import
  Log Row` (per-row status/reference/message, browsable in the desk without
  opening the Excel).
- The Smart Import result dialog now includes a "Download Result Excel"
  link, and the PreLead list view has a new "Import Logs" button that opens
  the full history (`alphax_crm/api/lead_import.py`, `alphax_prelead_list.js`).
- Log creation never blocks or fails an import — a problem building the log
  is caught and written to the Error Log doctype, not surfaced to the user,
  since the rows have already been committed by that point.

### Added — one-click setup for a shared local AI (Ollama) server
AlphaX CRM Settings already had an "AI Assist" section that talks to a
self-hosted, Ollama-compatible endpoint so no lead data reaches a
third-party AI vendor — what was missing was the setup step. Note on scope:
a web page cannot reach into an arbitrary PC and install software on it —
that's a deliberate browser/OS security boundary, not a gap here. What it
*can* do is generate a complete, ready-to-run setup script for the one
machine chosen to act as the office's shared AI server.
- New "AI Assist" buttons in AlphaX CRM Settings: **Download AI Server Setup
  Script** (Windows / macOS / Linux) and **Test AI Connection**.
- Each generated script installs Ollama if missing, lets the person choose a
  model size interactively (small/3B or medium/8B), configures Ollama to
  listen on all interfaces, installs `cloudflared` and opens a secure quick
  tunnel (no Cloudflare account needed) so this Frappe Cloud site can reach
  a machine sitting behind an office router/firewall, and finally calls back
  to the new `alphax_crm.api.ai_setup.register_endpoint` (guest-accessible,
  gated by a per-site random token embedded only in that script) to fill in
  **AI Base URL** and **Model** on the Settings form automatically — no
  copy/paste step left. A "Revoke Old Scripts" button rotates the token,
  invalidating every previously downloaded script.
- **Test AI Connection** runs from the server (the same side that actually
  calls the AI endpoint in real use) against whatever's currently in the
  form, even unsaved, and reports back the model's reply or the exact
  connection error.
- New files: `alphax_crm/api/ai_setup.py`, `public/js/crm_settings.js`.
  New Settings field: `ai_setup_token` (hidden, auto-generated).
- Scope note left for a deliberate follow-up, not bundled here: the quick
  tunnel's URL changes if the tunnel process restarts — fine to get running
  today, but a permanent setup uses a named Cloudflare Tunnel (needs a free
  Cloudflare account) for a fixed URL.

## [0.21.1] — 2026-09-27
### Fixed — one bad row cascaded into dozens of confusing, identical failures
Reported directly from a real Smart Import run: 39 rows all failed with an
error naming the exact same record, `[AlphaX PreLead, PLD-2026-00160]:
prospect_name`, as if all 39 rows had somehow collided with one existing
document. None of them had — none of the 39 were ever created.
- Root cause: on a failed row, `_execute()` rolls back to a per-row
  savepoint (`frappe.db.rollback(save_point=...)`), and that rollback also
  undoes the naming-series counter's increment for `naming_series:`-autonamed
  doctypes (AlphaX PreLead's own naming). The *next* row then gets handed
  the exact same next-available name the failed row never actually got to
  keep — so if the underlying problem (e.g. a required field the row
  genuinely can't supply) repeats across a run of rows, every one of them
  fails under that same reused name, and the failure list reads like one
  record breaking 39 times instead of 39 different rows each missing the
  same thing.
- Fixed by checking required fields **before** ever calling
  `doc.insert()`: a row missing a required field now fails immediately with
  a plain-language reason (`"Missing required field(s): PreLead / Contact
  Name"`) and never touches the naming series at all, so there's nothing
  for the next row to collide with.
- Extended the "correct it so it imports" fallback (v0.20.0 added
  prospect_name ← company_name) one step further: if a row has *no* company
  name either, prospect_name now also falls back to the row's email or
  phone number before giving up — a row with a real contact method is
  still a usable lead even with no name attached to it. Only a row with
  none of company name, email, mobile or phone is ever reported as missing
  the field, and only that row.
- Verified with a stubbed-metadata harness: a row missing an unfillable
  required field fails once with a specific, correct reason and inserts
  nothing; a row with only an email/phone still successfully imports using
  that as the name; a completely empty row is silently skipped rather than
  reported as a confusing failure.

## [0.21.0] — 2026-09-27
### Added — the manual fixes from the last two Excel corrections, built into Smart Import itself
Prompted by having to hand-correct two of the customer's real files (a blank
"Agent" column header, two columns both literally named "Comments", and
duplicate companies split across two rows with complementary data) before
they were importable — the request was to put that same correction logic
into the app so it happens automatically, not by hand each time.
- **No column can silently overwrite another one anymore.** `_read_rows`
  now runs every header through `_dedupe_headers()`: a blank header becomes
  "Column N" (its position), and a repeated header becomes "Comments (2)",
  "Comments (3)", etc., before it's ever used as a dict key. Previously
  `{header: value for header, value in zip(headers, row)}` meant a second
  column named "Comments" silently clobbered the first on every row — this
  was a real, generic data-loss bug, not specific to one file. `scan_file`
  now returns `header_notices` describing exactly what was renamed, shown
  as a warning in the Smart Import confirmation dialog, with a pointer to
  Correct Columns to point the renamed column at the right field.
- **Duplicate rows within the same file are merged, not just skipped.**
  Two rows for the same contact — matching on email, mobile, *or* landline
  phone (whichever they share; previously only email/mobile were checked at
  all, so two rows sharing just a landline weren't caught) — used to insert
  the first and silently skip the second, dropping whatever unique data the
  second row had. Now the second row's non-blank fields are merged into the
  first row's newly-inserted record instead, and the result summary reports
  a new `merged` list (row → the record it was folded into) alongside
  `inserted`/`skipped`/`failed`. A match against a record that already
  existed *before* this import still just skips, unchanged — merging into
  older, unrelated data during a bulk import is a bigger decision than
  merging two rows of the same file a human clearly meant as one entry.
- Verified with a stubbed-metadata harness: blank/duplicate/whitespace
  headers all get distinct, non-colliding keys; two rows sharing only a
  phone number (one has email, the other doesn't) merge into a single
  record with both fields populated and the required-name fallback still
  applied; a genuinely unrelated row still inserts normally.

## [0.20.0] — 2026-09-27
### Fixed — Smart Import couldn't recognize (or let you correct) non-English headers
Root cause: `_normalize_header()`, the function every alias/label match runs
through, stripped anything outside `[a-z0-9]` — which is *all* of an Arabic
(or any non-Latin) header. Every Arabic column in a file normalized to the
same empty string and collided with every other one, so auto-detection
could never reliably match a non-English export, and there was no fallback
in the app to say "this column is actually Company Name" — it would just
come back as an ignored column with nothing you could do about it short of
editing the file outside the app. Confirmed against the customer's own
Arabic commercial-registry export (26 columns, none in English except
"Status"/"Comments"/"Agent"/"DATE").
- `_normalize_header()` now uses a Unicode-aware `\w` match instead of
  `[a-z0-9]`, so Arabic (and any other script) normalizes to a distinct key
  per header instead of colliding into `""`.
- Added Arabic aliases for the fields most export sheets actually carry
  (company/establishment name, phone, mobile, email, website, city) to
  `FIELD_ALIASES`, so a similarly-shaped Arabic export auto-maps out of the
  box going forward.
- **New: "Correct Columns…" step**, right in the Smart Import confirmation
  dialog. Opens a dialog listing every column in the file with a dropdown
  of every field on the chosen target doctype (required fields marked `*`),
  pre-filled with AlphaX's best guess (or your last correction), plus a
  sample value from the file so you can tell what a column actually holds.
  Fix a wrong guess or map a column nothing auto-detects, click "Apply &
  Re-check", and the confirmation dialog re-scans against your corrected
  mapping — missing-master-data detection and the "N rows found" summary
  all update to match. This is the option that was missing: previously
  "Mapped fields" / "Ignored columns" were read-only text with no way to
  fix either.
- `AlphaX PreLead`'s required "PreLead / Contact Name" is now backfilled
  from Company Name when a file has no individual contact name at all — a
  B2B registry/company-list export never will, and failing all 2,000+ rows
  on a required field the source data structurally can't supply helps no
  one.
- Backend: `scan_file` and `run_import` both take an optional `column_map`
  (header → fieldname, `""` = skip, `__full_name__` = split into
  First/Last at import time) that overrides auto-detection entirely for
  that run; `scan_file` also always returns `raw_headers`,
  `column_suggestions`, `column_samples` and `importable_fields` so
  "Correct Columns" can be opened even on a file that auto-mapped
  perfectly, not only when something was left unmapped.
- Verified with a stubbed-metadata harness against the real Arabic file's
  actual header row: correct per-header suggestions, explicit
  column-map application (including the skip + full-name-split paths and
  phone normalization), and the prospect_name-from-company_name fallback.

## [0.19.0] — 2026-09-20
### Added — first pass at "AI-automation of the human gaps"
Three concrete, requested pieces of the wider automation ask. Nothing
here is AI/ML-based yet (no model calls); it's config-driven automation
that removes three specific places a human step was assumed but nothing
enforced it. `alphax_crm/api/ai.py` (lead classification/reply drafting)
is unrelated existing functionality and untouched.

- **Auto-set Lead Stage from Lead Status.** Confirmed against the real
  production Lead: **"Lead Status"** (label) is the customer's own
  Customize Form field `custom_lead_status` (Lead / Prospect / Cold Lead
  / Inactive Lead / Successful / Customer) — a coarse, human-picked
  bucket. **"Lead Stage"** (label) is actually the *native* `status`
  field (Qualified lead / Quotation / Postponed / Lost with reason /
  Contract Under Signing / Won / ...) — the field ERPNext's own pipeline
  logic, kanban and the Data Quality Gate all key off. The two had no
  link between them, so Lead Stage could silently drift out of step with
  what the salesperson actually picked as Lead Status.
  Now, whenever Lead Status changes, Lead Stage is set automatically
  from a configurable mapping table (**AlphaX CRM Settings → Lead Stage
  Automation → Lead Status → Lead Stage Mapping**, doctype `AlphaX Lead
  Stage Map`), seeded on install/migrate with the exact mapping
  confirmed with the customer:
  | Lead Status | Lead Stage |
  |---|---|
  | Lead | Qualified lead |
  | Prospect | Quotation |
  | Cold Lead | Postponed |
  | Inactive Lead | Lost with reason |
  | Successful | Contract Under Signing |
  | Customer | Won |
  Seeding only ever fills the table if it's empty, so a customized
  mapping is never overwritten on a later migrate. A toggle (**"Auto-set
  Lead Stage from Lead Status"**, default on) can turn the whole thing
  off; a Lead Status with no configured mapping row is left alone rather
  than guessed at. Implemented in `crm/lead.py::_sync_stage_from_status`,
  wired into the existing `validate()` hook (after the Data Quality Gate,
  so a blocked save never logs a stage change that didn't actually
  happen). Defensive throughout: does nothing if either field doesn't
  exist on a given site (`meta.has_field` checks), consistent with the
  project's running rule of never assuming a field name from ERPNext
  defaults.
- **"Day gap between actions" tracking.** New doctype `AlphaX Stage
  Transition Log` records every Lead Status, Lead Stage and approval
  Workflow State change on Lead / AlphaX PreLead / Opportunity, each row
  carrying `days_since_previous` — the elapsed time since *that same
  record* last changed *that same field* — computed automatically at
  the moment of the next change (`crm/activity.py::record_transition`),
  no separate cron pass needed to backfill it. New report **"AlphaX
  Stage Duration Report"** aggregates the log into avg/min/max day-gap
  per (record type, tracked field, from-value, to-value), sorted slowest
  first, so a stalled step in the pipeline (e.g. "Pending Approval →
  Approved averaging 9.4 days") is visible as a number instead of
  something someone eventually notices by hand. Gated by a new setting,
  **"Track day-gap between stage changes"** (`track_stage_durations`,
  default on).
- **Schedule monitoring.** New daily scheduled job
  `crm.tasks.notify_overdue_schedules` checks every record's latest
  Log Follow-up "Next Follow-up Date" (the same field the existing
  "AlphaX Follow-ups Due" report already reads) and sends each agent
  with overdue items a single grouped Notification Log entry (not one
  per record) listing what's overdue and by how many days. Gated by a
  new setting, **"Notify agents of overdue schedules"**
  (`schedule_reminders_enabled`, default on). This sits alongside the
  existing "AlphaX Follow-ups Due" report and the stale-record scan
  rather than replacing either — the report is pull (someone opens it),
  the stale scan watches idle *records*, this watches missed *promised
  dates* and pushes a nudge.
- Verified with a stubbed-`frappe` harness covering: a brand-new Lead
  created with a Lead Status already set; an existing Lead's Lead Status
  changing (mapping applied, day-gap logged); an unrelated save where
  Lead Status did not change (must NOT re-fire or log again); a Lead
  Status value with no configured mapping row (Lead Stage left
  untouched, nothing guessed); and a second transition a simulated day
  later (day-gap correctly computed as 1.0). All 5 scenarios pass.
- Refactored `_active_lead_workflow_field()` (previously private to
  `crm/prelead.py`) into a shared `crm.utils.active_lead_workflow_field()`
  since Lead's new workflow-transition logging needed the same "which
  workflow is actually active on this site" lookup; `prelead.py` keeps a
  thin back-compat wrapper so nothing else needed to change.
### Known gaps (flagged, not yet built)
- The newer 7-transition "Lead Approval -CRM" workflow JSON (with the
  two added Sales-Manager-only Approve shortcuts from Draft/Returned for
  Correction, and `allow_edit: "All"` on Returned/Approved) has not yet
  been reconciled into `setup_lead_approval_workflow()`, which still
  provisions the original 5-transition version.
- The broader "what else should AI check" question (near-duplicate/fuzzy
  matching beyond exact-field dedup, inbound-message triage, stalled-lead
  nudges informed by the new day-gap data) is advisory only so far — no
  code yet, pending confirmation of which of these to build next.

## [0.18.1] — 2026-09-14
### Fixed
- Lead's "Source PreLead" field (`alphax_prospect`) existed on-site but
  wasn't visible on the form — found via Customize Form that `Hidden` was
  checked. The field definition in `setup_custom_fields()` never
  explicitly listed `hidden` either way, so a generic sync only reliably
  touches properties it's explicitly given — it never had a reason to
  flip an existing `hidden: 1` back to `0`. Now sets `"hidden": 0`
  explicitly in the definition, and additionally forces it directly via
  `frappe.db.set_value` right after the sync runs, so this can't
  silently stay invisible again regardless of how the generic property
  sync behaves.

## [0.18.0] — 2026-09-14
### Fixed / Changed
- **The Data Quality Gate never actually fired on this site.** It gated
  on status moving *into* a hardcoded pair (`"Opportunity"`,
  `"Converted"`) — ERPNext's out-of-box status names — but this site's
  real Lead status list is entirely custom (Lead, Open, Replied,
  Opportunity, Quotation, Interested, Qualified lead, Proposal sent,
  Won, ...), so that condition never matched and the gate silently never
  triggered, regardless of completeness score. Matches exactly what the
  screenshot showed: a Lead at 60% completeness moved from "Lead" to
  "Interested" with no block at all.
### Added
- **New setting: "Gate When Leaving Status"** (`dq_gate_from_statuses`,
  comma-separated, default `"Lead"`). The gate now fires based on the
  status being **left**, not a hardcoded status being entered — so it
  works with any custom status list without code changes. Default
  behavior: nothing blocks while a Lead stays at "Lead", but moving it to
  *any other* status requires the configured required fields to be
  complete first. This is the "provision to define the value" asked for
  — the gated status is fully configurable, not hardcoded, including to
  more than one status at once (comma-separated).
- Verified against the exact reported scenario plus variations, using a
  stubbed `enforce()` run: (1) Lead → Interested at 60% completeness now
  correctly blocks, naming the missing field; (2) staying at "Lead"
  triggers nothing; (3) reconfiguring the gate to a different status
  (e.g. "Qualified lead") correctly moves where the check applies,
  confirming it's genuinely configurable and not just re-hardcoded to a
  different value.

## [0.17.2] — 2026-09-08
### Added
- **A converted PreLead is now read-only, enforced both client- and
  server-side.** Previously a PreLead stayed fully editable after
  converting to a Lead — including its Status, which could trigger
  another (nonsensical) conversion attempt or automation on a record
  that's already done its job.
  - **Client-side**: `frm.disable_form()` locks the whole form once
    `converted` is set, with a blue banner naming the Lead. The
    "Log Follow-up" and "Log a Call" actions are hidden too (further
    activity belongs on the Lead now); "Follow-up History", "Call
    History", and "Open Lead" remain available since they're read-only
    or navigate away.
  - **Server-side**: `validate()` now throws if a PreLead was already
    converted before this save, so the lock can't be bypassed via API
    calls, scripts, or bulk edit — only the UI enforcing it wouldn't be
    enough. Verified all three cases with a stubbed `validate()` run: a
    brand-new record is unaffected, the save that performs the actual
    not-yet-converted → converted transition is correctly still allowed
    (this check would otherwise block itself), and a second edit attempt
    on an already-converted record is correctly blocked with a clear
    message naming the Lead.
  - Confirmed no internal automation could be broken by this: every
    place that mutates a PreLead after creation (status revert,
    conversion-failure flag, clearing that flag) already uses direct
    `frappe.db.set_value`/`db_set`, never a full `.save()` — so none of
    it passes through the new `validate()` guard at all.

## [0.17.1] — 2026-09-08
### Changed
- **Both cross-reference fields between PreLead and Lead changed from Link
  to Data**, to let either record be deleted independently: PreLead's
  `Created Lead` and Lead's `Source PreLead`. Only converting one side
  (the one visible on the PreLead form) would have solved deleting the
  Lead but not the PreLead — Frappe blocks deleting a document if *any*
  Link field anywhere points at it, so the PreLead's own Link was what
  blocked deleting the Lead, and Lead's *reverse* Link
  (`alphax_prospect`/"Source PreLead") was what blocked deleting the
  PreLead. Both needed to change for both directions to actually work.
- No data migration involved: Link and Data fields are both stored as
  plain text in Frappe, so existing values on both sides remain valid
  as-is — this only removes the referential-integrity check, it doesn't
  touch how the values are stored.
- Deliberately no cascade logic added: deleting either side leaves the
  other completely untouched, including its status — there's nothing to
  "keep in sync" because nothing here writes to the other document at
  all anymore. If a Lead is deleted after conversion, the PreLead's
  "Created Lead" text simply names a record that no longer exists;
  nothing auto-clears it.

## [0.17.0] — 2026-09-01
### Added
- Two new fields on AlphaX PreLead, in the previously-empty gap in the
  identity section (right column, below Status):
  - **Created By** (`owner`, read-only, Link → User) — Frappe's own
    built-in record-creator tracking, exposed on the form. Deliberately
    distinct from the existing **PreLead Owner (Sales Person)** field:
    Owner can be reassigned later (via Assigned To or a bulk edit); this
    can't, since it's who actually created the record.
  - **Company Website** (`website`, Data).
- Wired `website` through both conversion paths in `crm/prelead.py`
  (direct to Lead, and via Smart Lead — Lead and Smart Lead both already
  have their own `website` field) so it isn't a dead-end form field.
  Also: Smart Import's column-alias table already had a `website` entry
  (LinkedIn Profile / linkedin / website url) from 0.10.3 that silently
  did nothing for Prospect/PreLead imports because the field didn't
  exist — it now activates automatically, no code change needed there.

## [0.16.1] — 2026-09-01
### Changed
- **PreLead Owner (Sales Person)** is now read-only on the form. It's
  still set automatically to the creator on a new PreLead (that happens
  in server-side code, which `read_only` doesn't block — only manual
  editing through the form UI is disabled). To reassign, use the
  Assigned To sidebar or a bulk edit.

## [0.16.0] — 2026-09-01
### Removed
- **Territory** field removed from AlphaX PreLead (native field, not one of
  the dynamically-injected accounting-dimension fields). Also removed the
  now-dead territory-copy code in both conversion paths in `crm/prelead.py`
  — harmless to leave (the field just always reads empty) but pointless to
  keep. Lead's own Territory field is untouched; this only affects PreLead.

### Added
- **PreLead can now belong to multiple cost centers.** Previously Cost
  Center on PreLead (when the opt-in Accounting Dimensions feature is
  enabled) was a single flat Link — no way to represent one PreLead
  spanning more than one cost center. Rather than invent a new mechanism,
  reused the exact pattern AlphaX Smart Lead already has for this same
  problem: when "cost_center" is in the enabled dimension fields, PreLead
  now gets a **Cost Center Splits** table (Business Line + Cost Center +
  split %) instead of a single dropdown — the same `AlphaX Service
  Dimension` child doctype Smart Lead already uses, not a second one.
  Other dimension fields (Department, Business Division, Employee Cost
  Center) are unaffected and remain flat Links, since only Cost Center was
  flagged as needing this.
  On conversion to Lead (both the direct path and via Smart Lead), the
  splits resolve to a single "primary" cost center — highest split % wins
  — using the identical resolution Smart Lead already uses for its own
  splits. Going via Smart Lead, the PreLead's splits are carried into the
  new Smart Lead's own `service_dimensions` table first, so Smart Lead's
  existing sync-to-Lead logic picks it up with no special-casing needed
  there at all.
  Verified in isolation: the split-resolution logic (highest % wins, empty
  and None cases) and the field-injection special-casing (`cost_center` →
  Table, other dimension fields → unaffected Links, `insert_after` chain
  intact) both behave as designed.

## [0.15.1] — 2026-09-01
### Changed — supersedes 0.15.0's rename, before it was ever deployed
- 0.15.0 renamed `AlphaX Prospect` \u2192 `AlphaX Lead Entry Point`, but
  that version was never actually deployed to the live site (confirmed
  from a screenshot still showing the original `AlphaX Prospect` label).
  Renamed again, this time to the final name: **`AlphaX PreLead`** /
  **`AlphaX PreLead Status`**. Same full scope as 0.15.0's rename
  (doctype folders, JSON `name`, controller classes now `AlphaXPreLead` /
  `AlphaXPreLeadStatus`, the business-logic module now `crm/prelead.py`,
  the form script now `public/js/prelead.js`, the list-view script and
  filename, every `hooks.py` registration, `DIM_TARGETS`/dimension
  anchors, the Lead-side Link field's target and label, and every
  workspace/report/settings label and description) \u2014 plus two
  additional stale references caught this time that the 0.15.0 pass had
  left behind: the list view's bulk-convert call still pointed at the old
  `crm.lead_entry_point` module path, and a docstring in
  `api/lead_import.py` still named the old list-view filename. Naming
  series is now `PLD-.YYYY.-`.
- Since 0.15.0 was never live, the deployment path is simpler than what
  0.15.0's own notes described: rename directly from `AlphaX Prospect` to
  `AlphaX PreLead` on the site (see Deployment note below) \u2014 no
  intermediate `AlphaX Lead Entry Point` state to pass through.
- Also corrected my own earlier framing: 0.15.0's changelog said
  historical `patches/*` files were left untouched to preserve history.
  That's true for descriptive comments/docstrings, but
  `patches/v0_6/add_dimensions_and_backfill.py` passes a doctype name as
  a literal function argument (`backfill_activity_monitor([...,
  "AlphaX Prospect"])`) \u2014 since Frappe replays all historical patches
  in sequence on a brand-new install, that argument has to match the
  *current* doctype name to actually work, so it was updated both times
  (correctly, if not for the reason originally stated).
- Full-tree verification repeated: `py_compile`, JSON/JS syntax, a
  repo-wide grep confirming zero references to either old name
  (`AlphaX Prospect` or `AlphaX Lead Entry Point`) remain, folder/JSON
  `name`/controller-class agreement for both doctypes, and that
  `hooks.py`'s function references match what's actually defined in
  `crm/prelead.py`.

### Deployment note
Same as 0.15.0's, updated for the final name. An app update alone doesn't
touch existing `AlphaX Prospect` records or the underlying table. To
rename the live doctype after deploying this version:

**Via Desk UI:** DocType list \u2192 open **AlphaX Prospect** \u2192
**\u22ef menu \u2192 Rename** \u2192 `AlphaX PreLead`. Repeat for
**AlphaX Prospect Status** \u2192 `AlphaX PreLead Status`.

**Via bench:**
```
bench --site <site> execute frappe.rename_doc --args "['DocType','AlphaX Prospect','AlphaX PreLead']"
bench --site <site> execute frappe.rename_doc --args "['DocType','AlphaX Prospect Status','AlphaX PreLead Status']"
```

Take a backup first and rehearse on staging if possible \u2014 same
caveats as 0.15.0. Existing records keep their old `PROS-...` names;
only new records use the `PLD-...` series.

## [0.15.0] — 2026-08-24
### Changed — BREAKING: doctype rename, requires a manual site-side step
- **Renamed `AlphaX Prospect` \u2192 `AlphaX Lead Entry Point`**, and
  **`AlphaX Prospect Status` \u2192 `AlphaX Lead Entry Point Status`**,
  to resolve a real naming collision: ERPNext ships its own native
  `Prospect` doctype (aggregates Leads/Opportunities under a company
  account, via a `Prospect Lead` child table) which is a *different*
  concept sitting *after* Lead in ERPNext's real funnel \u2014 while ours
  sits *before* Lead as the pre-qualification calling list. Confirmed via
  ERPNext's own source before renaming. The funnel is now:
  **Lead Entry Point \u2192 Lead \u2192 (ERPNext's native) Prospect \u2192
  Opportunity**, which rides on ERPNext's real pipeline instead of
  shadowing it with a lookalike name.
- Scope of the rename: doctype folders, JSON `name`, controller classes
  (`AlphaXLeadEntryPoint`, `AlphaXLeadEntryPointStatus`), the business-logic
  module (`crm/prospect.py` \u2192 `crm/lead_entry_point.py`), the form
  script (`public/js/prospect.js` \u2192 `public/js/lead_entry_point.js`),
  the list-view script and its filename, every `hooks.py` registration
  (`doctype_js`, `doc_events`), `DIM_TARGETS`/`DIM_ANCHOR`, the Lead-side
  Link field's target doctype and label, all workspace/report/settings
  labels and descriptions, and the naming series (`PROS-.YYYY.-` \u2192
  `LEP-.YYYY.-`, new records only).
- Deliberately **not** renamed: internal fieldnames (`prospect_name`,
  `prospect_owner`, the Settings fields `prospect_autoconvert` etc.,
  Lead's `alphax_prospect` link fieldname) and historical `patches/*`
  files. Fieldnames are live database columns with real data in them on
  every existing record \u2014 renaming those needs `frappe.rename_field`
  data migration, which is a separate, bigger decision than a display-name
  rename and wasn't part of what was asked. Old patch files are a record
  of what actually ran historically and rewriting them after the fact
  would misrepresent that history.
- **Found and fixed, opportunistically, a genuinely pre-existing bug**
  encountered while working in the list-view file: the "Convert to Lead"
  bulk action called `alphax_crm.api.prospect.convert_to_lead`, a method
  that has never existed in this app (no `api/prospect.py` ever existed;
  the real logic was always a private, unexposed `_convert_to_lead`). That
  button has silently done nothing since before this session started. Added
  a proper whitelisted `bulk_convert_to_lead()` wrapping the same
  conversion logic the automatic status-driven path uses, and pointed the
  list view at it.
- Full-tree verification: `py_compile` across every `.py` file, JSON/JS
  syntax checks, a repo-wide grep confirming zero remaining references to
  the old doctype names anywhere, and an explicit check that folder name /
  JSON `name` / controller class agree for both renamed doctypes (the
  exact mismatch class that caused the AlphaX Business Unit install
  failure earlier in this app's history).

### Deployment note
Existing `AlphaX Prospect` / `AlphaX Prospect Status` records are **not**
touched by installing this app version \u2014 an app update alone only
changes code, not existing document names or the underlying database
table. To actually rename the live doctype (its table, and every Link
field pointing at it) on a site that already has data, run this **after**
deploying this app version, not before (the renamed controller files need
to already be in place):

**Easiest \u2014 via Desk UI** (recommended if you're not comfortable with
bench console): go to the DocType list, open **AlphaX Prospect**, use the
**\u22ef menu \u2192 Rename**, and rename it to `AlphaX Lead Entry Point`.
Repeat for **AlphaX Prospect Status** \u2192 `AlphaX Lead Entry Point Status`.

**Or via bench**, if you prefer the command line:
```
bench --site <site> execute frappe.rename_doc --args "['DocType','AlphaX Prospect','AlphaX Lead Entry Point']"
bench --site <site> execute frappe.rename_doc --args "['DocType','AlphaX Prospect Status','AlphaX Lead Entry Point Status']"
```
(There's no `bench rename-doctype` command \u2014 `frappe.rename_doc` is
the actual mechanism; both paths call the same thing under the hood.)

Either way: **take a site backup first**, and ideally rehearse this on a
staging copy before touching production \u2014 renaming a DocType with
existing data is a well-known rough edge in Frappe (it also tries to
rename controller files on disk, which is exactly why deploying this
app version *first* matters, so it finds the renamed files already
correct rather than clashing with them). Existing records keep their old
`PROS-...` names regardless \u2014 the naming series change only affects
newly created records going forward.

## [0.14.1] — 2026-08-24
### Changed
- Renamed the doctype introduced in 0.14.0 from **AlphaX Lead Intake** to
  **AlphaX Lead Initiation** (folder, JSON `name`, controller class
  `AlphaXLeadInitiation`, naming series `INIT-.YYYY.-`, both `_log_intake`
  call sites in `api/lead_intake.py` / `api/whatsapp.py`, and the workspace
  shortcut label). Safe as a clean rename rather than a live migration,
  since this doctype was never deployed. Verified no stray references to
  the old name remain anywhere in the app, and that folder name / JSON
  `name` / controller class all agree — a mismatch there is exactly the
  kind of thing that fails silently until Frappe tries to load the module.
- Removed the descriptive help text from AlphaX Prospect's `Job Title`
  field (the "Reuses the standard Designation master..." note added in
  0.13.0) — the field itself is unchanged, just the on-form description.

## [0.14.0] — 2026-08-20
### Added
- **AlphaX Lead Intake**, a new doctype logging every inbound Lead-capture
  attempt through the two webhook-driven channels that previously left no
  visible record at all: `alphax_crm.api.lead_intake.capture()` (website
  forms, Meta/Google lead ads, generic API) and the WhatsApp handler's own
  Lead resolution. Each record captures channel, outcome (Success /
  Duplicate / Failed), the resulting Lead if one was created, a contact
  identifier, consent flag, error detail on failure, and the raw payload
  for audit. Deliberately scoped to just these two paths — Smart Import
  and manual entry already have their own visibility (import summaries,
  standard doc metadata), so aren't duplicated here.
  Added as a workspace shortcut ("Lead Intake", ahead of Prospect) for
  discoverability. Verified end-to-end with a stubbed run of `capture()`
  covering all three outcomes plus WhatsApp's separate logging call, and
  the channel-detection heuristic (meta/google/whatsapp/website/other).

## [0.13.4] — 2026-08-20
### Fixed
- Frappe Cloud rejected the previous release with "Invalid release" /
  `SyntaxError: invalid decimal literal` pointing at lines like
  `>>>>>>> 7b84d8994af65258f09478dcce5943e2659c1538` in `__init__.py`,
  `crm/followup.py`, `crm/prospect.py`, `hooks.py`, `setup/install.py`,
  and `setup.py`. Those are literal unresolved git merge-conflict markers,
  not something introduced by this app's own source — these release zips
  are full snapshots written directly, not incremental patches, and
  contain no conflict markers anywhere (checked). This most likely
  happened applying a prior zip via `git merge`/`git apply` against
  diverging history and committing before resolving the conflict.
  This release is a clean re-verified snapshot of the current app state
  (identical content to 0.13.3) with no merge markers of any kind —
  confirmed via `py_compile` across every `.py` file and a repo-wide grep
  for `<<<<<<<` / `=======` / `>>>>>>>`. Recommend replacing the app
  directory wholesale from this zip (or re-cloning) rather than merging
  it on top of the corrupted commit, to avoid re-introducing the same
  conflict.

## [0.13.3] — 2026-08-20
### Fixed
- Prospect → Lead auto-conversion failed with "Workflow State transition
  not allowed from Draft to Pending Review". Root cause: `_convert_to_lead`
  still force-set `lead.alphax_review_status = "Pending Review"` — the
  field governed by the now-superseded "AlphaX Lead Review" workflow
  (deactivated in 0.12.0). With "Lead Approval -CRM" active instead (field
  `workflow_state`, entry state "Draft", and no "Pending Review" state at
  all), that stale assignment tripped the new workflow's own transition
  validation. Both conversion paths (direct, and via Smart Lead) now check
  which workflow is actually active on Lead via a new
  `_active_lead_workflow_field()` helper, and only set
  `alphax_review_status` when that's genuinely the field the active
  workflow governs. Otherwise it's left untouched, so the Lead lands in
  its real entry state — currently "Draft" — the way it should. Verified
  against all three cases (new workflow active, old workflow active, no
  workflow active) via a stubbed run of the guard logic.

## [0.13.2] — 2026-08-20
### Changed
- The conversion-failure message from 0.13.1 was a one-time toast that
  vanished once dismissed. It's now **persistent**: two new fields on
  AlphaX Prospect, `Conversion Failed` (Check, shown in the list view and
  filterable) and `Conversion Error` (the actual message, shown on the
  form only while the flag is set). Both stay set — and a red banner stays
  on the form — until conversion actually succeeds, at which point they're
  cleared automatically. Covers both conversion paths, same as 0.13.1.
  Verified with an end-to-end simulation: a forced failure sets the flag
  and message and reverts the status; a subsequent successful retry
  clears both while leaving the (now-valid) status alone.

## [0.13.1] — 2026-08-20
### Fixed
- Setting a Prospect to a status configured to auto-convert (e.g.
  "Interested") would leave the status changed even when conversion
  failed (e.g. a required Lead field like Job Title was missing) —
  `on_update` runs after the Prospect's own status change is already
  committed, and the conversion attempt was wrapped in a try/except that
  only logged the error, silently. The Prospect was left showing
  "Interested" with no Lead behind it and no visible reason why.
  `on_update` now reverts the status back to what it was before the save
  (or the default status, if there was no "before" state) when conversion
  fails, and shows a clear red message explaining both that it reverted
  and the actual underlying error, instead of the failure only being
  visible in the Error Log. Covers both conversion paths (direct to Lead,
  and Prospect → Smart Lead → Lead), since the Smart Lead path is called
  from inside the same function and any failure there propagates through
  the same try/except. Verified end-to-end with a stubbed `on_update` run:
  a forced conversion failure correctly reverts the status and produces
  the expected message.

## [0.13.0] — 2026-08-19
### Changed
- **AlphaX Prospect "City"** changed from free-text Data to a Link against
  the **City** doctype (the same tree-structured master already used
  elsewhere on the site).
- **AlphaX Prospect "Job Title"** changed from free-text Data to a Link
  against the standard **Designation** master (reused rather than creating
  a new AlphaX-specific list, matching the "Business Domain" precedent set
  in 0.11.0). Seeded via a new idempotent `seed_job_titles()` (runs on
  install/migrate) with the 45 job titles supplied — kept verbatim,
  including a couple of likely typos ("Sales manger", "partener") and a
  literal "unknown" entry, since they may already be in use on existing
  records. Say the word and I'll clean those up.

### Added
- **Accounting Dimensions on Prospect are now opt-in and independently
  restricted**, via two new `AlphaX CRM Settings` fields:
  `Enable Accounting Dimensions on Prospect` (off by default) and
  `Prospect Dimension Fields` (comma list, default `cost_center` only).
  Lead and Opportunity are untouched — they keep getting every active
  Accounting Dimension unconditionally, exactly as before. Previously
  Prospect was already technically in the list of doctypes this
  mechanism could target, gated only by one global on/off switch shared
  with Lead/Opportunity — so turning it on for Prospect would have dumped
  all 4 active dimensions (Business Division, Employee Cost Center, Cost
  Center, Department) onto the calling-list form at once. Verified the
  filtering logic in isolation: enabling with the default setting yields
  Cost Center only; Lead/Opportunity are unaffected either way.
- **Meeting Type** (Online Meeting / On-site Meeting) on the Log Follow-up
  flow — new field on `AlphaX Follow-up`, shown (and required) only when
  Channel = "Meeting", threaded through `log_followup()`, the logged
  Communication's content, the activity-timeline summary, and the
  Follow-up History view.

## [0.12.2] — 2026-08-18
### Fixed
- Install failed on Frappe Cloud with "Module import failed for AlphaX
  Business Unit ... No module named
  'alphax_crm.alphax_crm.doctype.alphax_business_unit.alphax_business_unit'".
  The 0.12.0 child doctype only shipped its `.json` — missing the
  `alphax_business_unit.py` controller and `__init__.py` every doctype
  folder needs, so Frappe's sync step (which imports the controller module
  right after inserting the DocType) had nothing to import. Added both.
  Audited every other doctype folder in the app for the same gap (missing
  controller `.py` or `__init__.py`) — none found.

## [0.12.1] — 2026-08-18
### Fixed
- Deploy failed on Frappe Cloud / bench with "Could not find a compatible
  Frappe version in pyproject.toml" — `[tool.bench.frappe-dependencies]`
  declared a version constraint for `erpnext` but not for `frappe` itself,
  which Frappe Cloud requires. Added `frappe = ">=15.0.0,<16.0.0"`,
  matching the existing `erpnext` constraint and the site's actual
  versions (frappe 15.118.0 / erpnext 15.119.0).

## [0.12.0] — 2026-08-17
### Changed
- **Smart Lead's "Business & Service Dimensions" reworked**: the flat
  fields added in 0.11.0 (Business Division, Department, Employee Cost
  Center, Sub Services, Quoted Value, Contract Duration, Expected Closing
  Date) didn't match the real production data model and are **removed**.
  Replaced with a new **Business Units** child table
  (`AlphaX Business Unit`) mirroring production Lead's `Lead Business Unit`
  table field-for-field (Business Unit, Lead Description, Business Contact
  & Mobile, Business Contact Email, Expected Order Value, Payment Type,
  Expected Close Date) — a Lead can have several business units, each with
  its own contact and commercial terms, which the flat fields couldn't
  represent at all.
  `crm/smart_lead.py`'s default field map updated to match: rows copy
  straight into Lead's `custom_business_lead_unit` table on sync (same
  fieldnames on both sides, so Frappe's own table-field copy semantics
  handle it with no per-row transform code needed). Not independently
  re-verified against a live site since the maintainer doesn't have one
  available here — worth a spot-check in staging.
- **Approval workflow replaced**: "AlphaX Lead Review" (this app's own
  provisioned workflow, `alphax_review_status`-driven) is now deactivated
  in favor of **"Lead Approval -CRM"**, the customer's own process
  (Draft → Pending Approval → Approved, with a Returned for Correction
  loop; roles CRM Initiator / Sales Manager; field `workflow_state`).
  Provisioned by a new `setup_lead_approval_workflow()` in
  `setup/install.py`, following the exact same idempotent
  create-if-missing / reactivate-if-inactive pattern already used for
  "AlphaX Lead Review" — including the same supersession approach used
  when "AlphaX Lead Review" itself replaced the earlier "AlphaX Lead
  Workflow". Runs automatically via the existing `after_install` /
  `after_migrate` hooks — no manual script needed, just `bench migrate`.
  `setup_lead_workflow()` (the old provisioning function) is no longer
  called from either hook, so it won't fight the deactivation by
  re-enabling itself, but is left defined rather than deleted.

## [0.11.0] — 2026-08-12
### Added
- **Business & Service Dimensions on AlphaX Smart Lead**, brought over from
  production Lead: Business Division, Department, Employee Cost Center
  (Links), Sub Services (Select, copied verbatim from Lead — see note
  below), Quoted Value, Contract Duration, and Expected Closing Date.
  **Not** copied: Won/Lost Date (inapplicable to a pre-decision intake
  record), and a duplicate top-level "Business Line" field — Business Line
  is already captured per row in the existing `service_dimensions` child
  table, and adding a second, disconnected one would recreate the exact
  duplication problem this doctype exists to avoid. If Business Line is
  later configured as a shared Accounting Dimension, it applies to Smart
  Lead automatically with no code change.
- The existing `AlphaX Service Dimension` child table's `Business Line`
  field is now a Select using AlphaX's real business-line list (from
  Lead's `custom_business_line_`), instead of free text.
- New **Business Domain** field (`industry`, Link → Industry Type) on Smart
  Lead — reuses the same global, pre-seeded master already used by Prospect
  and Lead (rather than inventing a separate list), so values carry through
  the whole pipeline and "Create a New Industry Type" is available inline
  from the dropdown per standard Frappe Link behavior.
- `crm/smart_lead.py`'s default Smart Lead → Lead field map extended to
  cover all of the above (`industry`, `business_division`, `department`,
  `employee_cost_center`, `sub_services`→`sub_services_`, `quoted_value`,
  `contract_duration`→`custom_contract_duration`, `expected_closing_date`).
  **Note:** this default only applies if `AlphaX CRM Settings → Smart Lead →
  Field Map` is empty — if it's already been customized on your site, add
  matching rows there for the new fields to actually carry through to Lead.
- Two "smart" additions (my own judgment, not explicitly requested):
  - **Live duplicate check** — a new whitelisted `check_duplicate()` looks
    up Lead / Prospect / Smart Lead by email or mobile as soon as either is
    entered on the Smart Lead form, and writes a short match summary into
    a new read-only "Possible Duplicate(s)" field (non-blocking — the agent
    decides). Reuses the exact per-doctype email-field mapping fixed in
    Smart Import (`email_id` on Lead/Prospect, `email` on Smart Lead) so it
    doesn't repeat that bug.
  - **Data Completeness %** — Smart Lead now reuses the existing,
    config-driven Data Quality engine (`crm/data_quality.py`, the same one
    Lead uses) to show a live, non-blocking completeness score and report.
    Shows 100% until rules referencing Smart Lead's own fieldnames are
    added in Settings — Lead-only rules (e.g. `email_id`) are silently
    skipped for Smart Lead since the engine matches by fieldname presence.

## [0.10.3] — 2026-08-12
### Changed
- Smart Import's header matching was, throughout its entire history (0.3.2
  through the port in 0.10.0), a fixed, hand-maintained alias list — it only
  auto-corrected headers someone had explicitly anticipated, and silently
  dropped everything else (this is what caused 0.10.1/0.10.2's bugs). Added
  a generic normalization pass to `_field_map` and to alias/name matching:
  headers are now also compared case/spacing/punctuation-insensitively
  against target fieldnames and labels, so formatting variants like
  `Company_Name`, `EMAIL-ID`, `mobile no`, `Job_Title` map automatically
  without needing an alias entry. `FIELD_ALIASES`/`NAME_ALIASES` are still
  needed, and still used, for genuinely different vocabulary (e.g. "Work
  Email" for `email_id`) — that's a wording difference, not a formatting
  one, and can't be inferred generically.
  Verified against 6 deliberately mangled headers (mixed case, underscores,
  dashes, extra spaces): all 6 now map with zero unmapped columns.

## [0.10.2] — 2026-08-12
### Fixed
- Smart Import silently dropped every row's name (`Value missing for AlphaX
  Prospect: Prospect / Contact Name` on every row) whenever the source file
  used a raw fieldname-style header for the contact's name — e.g.
  `lead_name`, as produced by Lusha-style exports — rather than a human
  label like "Contact Name". `NAME_ALIASES` only recognized labels, so on a
  target whose own name field is spelled differently (`prospect_name` on
  Prospect, `first_name`/`last_name` on Lead/Smart Lead), the name column
  had no alias to match and was silently ignored. Verified against the
  actual reported file (`AlphaX_Leads_Import_Lusha.xlsx`): `lead_name` now
  correctly derives `prospect_name` on Prospect and `first_name`/`last_name`
  on Lead and Smart Lead.

## [0.10.1] — 2026-08-12
### Fixed
- Smart Import crashed with `Unknown column 'tabAlphaX Smart Lead.email_id'`
  whenever duplicate-checking ran against Smart Lead while importing into
  Prospect or Lead (its dedup filter reused the source doctype's field name
  — `email_id` — instead of Smart Lead's own `email` field, and the
  remap only fired when the row happened to carry an `email` key rather
  than being based on which target doctype was actually being queried).
  `_is_duplicate` now looks up the correct email field per doctype
  (`email_id` for Lead/Prospect, `email` for Smart Lead) before building
  each query.

## [0.10.0] — 2026-08-12
### Added
- **Smart Import**, back from the 0.4.1/0.4.3 line and ported onto the
  current schema. A "Smart Import" button (group: AlphaX) on the AlphaX
  Prospect list view uploads a CSV/TSV/XLSX, auto-scans and maps columns
  (including known aliased export headers — "Work Email", "Contact Name",
  etc.), and imports into **any of the three data-entry targets**: AlphaX
  Prospect, Lead, or AlphaX Smart Lead. Switching the target in the dialog
  re-scans the file against that doctype's own fields.
- **Generic missing-master handling** on import: any Link field on the
  chosen target (Lead Source, Territory, Industry Type, AlphaX Prospect
  Status, Branch, ...) that references a value not yet in the system can be
  auto-created or left blank, per master doctype — this now also covers
  Prospect and Smart Lead's Link fields, not just Lead's, since both gained
  Link-typed fields after 0.4.x.
- Duplicate detection (email/mobile) on import now also checks AlphaX Smart
  Lead, not just Lead and Prospect.
- `alphax_skip_ai` is now actually honored on Lead `after_insert` (previously
  set by the importer but never read) so the "Run AI classification" import
  toggle genuinely suppresses per-row AI jobs when left unchecked.
- New hidden `import_batch` field on AlphaX Prospect, stamped on rows created
  via Smart Import for traceability.

## [0.9.0] — 2026-08-11
### Added
- **Smart Lead** (`AlphaX Smart Lead`): a clean, canonical data-entry doctype
  that maps into the (over-customized) ERPNext Lead on save via a **configurable
  field map** (`AlphaX Smart Lead Map` in Settings) with transforms (normalize
  mobile, title/upper/lower/trim). One field per concept, ERPNext masters as
  Links (Branch, User, Territory, Lead Source, Cost Center).
- **Multi cost-center** service dimensions child table (one lead → many
  businesses, with split %); primary maps to the Lead's Cost Center dimension.
- **Saudi National Address** block + a Verify action (SPL API creds in Settings;
  stub until credentials are wired). Combined address written to the Lead.
- **Prospect convert target** now honoured: a Prospect can convert directly to a
  Lead, or via a Smart Lead that maps to the Lead.
- Lead custom fields: Smart Lead link, National Address. Default field map seeded.

## [0.8.2] — 2026-08-11
### Fixed
- Install error `NameError: name 'seed_default_settings' is not defined`. An
  earlier edit had merged that function's body into `setup_accounting_dimensions`
  and dropped its `def` header; restored it as a separate function. Added an AST
  audit so any function called by install/migrate/patches must be defined.

## [0.8.1] — 2026-08-11
### Fixed
- Install error `No module named 'alphax_crm.alphax_crm.doctype.alphax_follow_up'`.
  Frappe scrubs hyphens to underscores, so the `AlphaX Follow-up` doctype folder
  must be `alphax_follow_up` (and the `AlphaX Follow-ups Due` report folder
  `alphax_follow_ups_due`). Renamed both folders/files to match; doctype/report
  names unchanged.

## [0.8.0] — 2026-08-11
### Added
- **Complete follow-up mechanism** (`AlphaX Follow-up`): every touch records
  channel, direction, outcome, duration, summary, next action and next
  follow-up date. On save it threads a Communication into the activity timeline
  (full history), stamps last-activity, pushes the next date onto the record and
  raises a ToDo reminder. Works on Lead, Prospect and Opportunity.
- **Log Follow-up** and **Follow-up History** actions on all three forms.
- **Follow-ups Due** report: latest next-step per record, overdue flagged.

## [0.7.0] — 2026-08-11
### Added
- **Configurable report fields & filters**: a Settings table
  (`AlphaX Monitor Field`) to add any field (dimensions like Cost Center /
  Business Unit, Territory, etc.) as a **column** and/or **filter** in the
  Activity Monitor and Owner Summary reports — no code. Dimension filters are
  rendered dynamically (Link where possible). Seeded from active dimensions.
- **Prospect convert target** setting: convert a Prospect either directly to a
  Lead, or (forward-compatible) via a Smart Lead data-entry doc that maps into
  the ERPNext Lead on submit.

## [0.6.0] — 2026-08-11
### Added
- **Accounting dimensions on CRM documents**: auto-adds Link fields for whatever
  dimensions are activated in ERPNext (Cost Center, Department, and any active
  Accounting Dimension such as Business Unit) to Lead, Prospect and Opportunity.
  Values carry over on Prospect → Lead conversion. Toggle in Settings.
- **Activity monitor extended to Prospect and Opportunity**: last activity
  (who/what/when) + idle days now tracked on all three documents, including
  status-change capture; daily idle refresh covers all three.
- **Owner Activity Summary report** (Lead / Opportunity / Prospect): per
  salesperson open count, average idle, max idle, overdue count and %.
- **Backfill**: one-time seeding of last-activity from each record's newest
  existing Communication/Comment (runs via the v0_6 patch; re-runnable).

## [0.5.0] — 2026-08-11
### Added
- **Lead Activity Monitor** (configurable): tracks last activity per lead —
  when, who, and what (calls, emails, WhatsApp, comments, status/review changes)
  — plus idle days on open leads. New Lead fields: Last Activity By / Type /
  Summary and Idle Days, with a form headline indicator.
- **Configurable monitored statuses** in Settings (`AlphaX Monitored Status`):
  choose which statuses are monitored, mark one as **Default**, and set a per-
  status idle threshold (fallback: default threshold). Daily scheduler refreshes
  idle days.
- **On-screen tool**: `AlphaX Lead Activity Monitor` script report with a Status
  multiselect (defaults to the configured default), owner and idle-over filters,
  overdue highlighting; plus a Lead-form status selector that opens it.

## [0.4.1] — 2026-08-03
### Added
- **Log a Call** action on Prospect and Lead (provider-independent): records
  each call as a phone `Communication` — direction, outcome, duration, notes,
  optional next follow-up — so it appears in the activity timeline as call
  history. Updates last-contacted / last-activity. Adds a **Call History** view
  (Communications filtered to phone) on both forms.

## [0.4.0] — 2026-07-08
### Added
- **Prospect (pre-lead) layer** — `AlphaX Prospect` doctype owned by the
  creating salesperson, with contact and follow-up fields.
- **Configurable status labels** — `AlphaX Prospect Status` master; add/remove
  labels as records, each mapped to a behavior (Convert to Lead, Close,
  Mark Unreachable, Schedule Follow-up, None). Ships 6 seeded labels.
- **Prospect → Lead automation** — setting a Prospect to an "Interested"
  (Convert to Lead) status auto-creates a Lead keeping the **same owner** and
  entering the review workflow at *Pending Review*; idempotent.
- **Lead review workflow** — `AlphaX Lead Review`: Pending Review →
  Approve / Return for Correction / Reject, with Return → Resubmit loop. Runs on
  a dedicated `alphax_review_status` field; legacy status workflow auto-deactivated.
- **AlphaX Lead Reviewer** role and three review notifications (pending review,
  returned for correction, approved).
- Settings: *Prospect → Lead* section (auto-convert, send-for-review toggles).

## [0.3.1] — 2026-07-06
### Fixed
- Moved the data-quality patch to the `[post_model_sync]` phase so the
  `dq_rules` table field exists before seeding (fixes `NoneType ... options`
  on migrate). Seeders hardened to no-op if invoked before schema sync.

## [0.3.0] — 2026-07-06
### Added
- **Data Quality Gate** — per-field completeness + correctness rules
  (`AlphaX Data Quality Rule`), KSA-aware validators (Saudi mobile, VAT,
  National ID/Iqama, CR, email, URL, regex, min-length), consolidated blocking
  message at qualify/convert, completeness score, and live client feedback on
  the Lead form.

## [0.2.0] — 2026-07-01
### Added
- **WhatsApp Business (Cloud API) intake** — single webhook for Meta
  verification + inbound events, `X-Hub-Signature-256` validation, message
  de-duplication, resolve-or-create Lead, threaded Communication, bilingual
  auto-acknowledgment (text/template), optional media download.

## [0.1.0] — 2026-06-30
### Added
- Channel-agnostic token-secured lead intake webhook.
- Lead de-duplication, rule-driven lead scoring, hot-lead auto-Opportunity.
- Assignment/routing seed, follow-up SLA, daily stale-deal detection
  (notify / least-loaded reassign).
- PDPL consent tracking + retention scheduler (anonymize / delete).
- Notifications, workspace, and a single `AlphaX CRM Settings` configuration
  doctype. Self-installing on migrate.

[0.9.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.9.0
[0.8.2]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.8.2
[0.8.1]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.8.1
[0.8.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.8.0
[0.7.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.7.0
[0.6.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.6.0
[0.5.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.5.0
[0.4.1]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.4.1
[0.4.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.4.0
[0.3.1]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.3.1
[0.3.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.3.0
[0.2.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.2.0
[0.1.0]: https://github.com/jamunachi08/alphax_crm/releases/tag/v0.1.0
