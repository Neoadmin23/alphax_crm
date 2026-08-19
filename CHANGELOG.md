# Changelog — AlphaX CRM Automation

All notable changes to `alphax_crm`. Versions follow the app version in
`alphax_crm/__init__.py`, `hooks.py` (`app_version`) and `setup.py`.

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
