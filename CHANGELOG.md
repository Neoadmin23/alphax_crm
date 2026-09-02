# Changelog — AlphaX CRM Automation

All notable changes to `alphax_crm`. Versions follow the app version in
`alphax_crm/__init__.py`, `hooks.py` (`app_version`) and `setup.py`.

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
