# Lead workflow and control review

AlphaX CRM 0.44.0 • ERPNext v15 • 24 November 2026
For sales agents, quotation approvers and the ERPNext implementation team. The attached 0.43.0 source contains all seven workflow areas. Several paths behaved differently from the approved controls. This release corrects those paths and is ready for staging acceptance.

| Audience or evidence | Responsibility or scope | Action or result |
|---|---|---|
| Sales agent | Maintain Lead Stage and record the actual client activity. | Create or submit the quotation, choose the next contact date when postponing, and approve client-facing emails. |
| Sales Manager / Approver | Receives missing-quotation escalations, loss follow-up and contract check-ins. | Review the linked document, record a comment or decision, and use the closure action only when the evidence is complete. |
| ERPNext administrator | Owns the calendar, recipients, email account, rule switches and scheduler. | Apply the release on staging, check the settings on page 8, and retain the acceptance evidence. |
| Verification completed | Reviewed hooks, settings, field setup, server validations, Desk actions, calendar, jobs, notification delivery and AI draft paths. | 32 tests passed locally. Twelve new rule tests include all 81 stage pairs, closure evidence, business hours and reminder timing. Python compiled and three changed Desk scripts passed syntax checks. |
| Verification pending | The ZIP contains historical site and browser scenarios. Their prior results belong to earlier releases. | No running ERPNext site, SMTP account, scheduler or model endpoint was available. Production readiness requires the staging scenarios on page 9. |

Read pages 2–7 as the requirement comparison. Page 8 identifies configuration that affects delivery. Page 9 gives the acceptance procedure. The source archive includes an editable Markdown copy of this guide.

Release evidence: VERSION, alphax_crm/hooks.py, tests/test_approved_workflow.py and tests/site_workflow_test.py.

# A  Approved stages and status mapping

Lead Stage is the native status field. Lead Status is custom_lead_status. The agent chooses the stage and the server derives its business status. All nine mappings existed as configurable defaults in 0.43.0. Version 0.44.0 uses the approved list in validation.

| Lead Stage | Lead Status | What the user does or sees |
|---|---|---|
| 1  Lead | Lead | New records start here. Record first contact. |
| 2  Interested | Lead | Schedule or hold a meeting and link it to the Lead. |
| 3  Qualified lead | Lead | Prepare a linked quotation. The stored stage uses a lowercase “l” in “lead”. |
| 4  Quotation | Prospect | Enter manually after qualification or advance through submission of a linked quotation. |
| 5  Postponed | Cold Lead | Choose a Next Contact Date. A blank follow-up entry becomes available for the agent. |
| 6  Contract Under Signing | Successful | Keep Contract blank. Earlier code checked Signed at Won but permitted it here. The server now blocks a nonblank Contract at this stage. |
| 7  Won | Customer | Contract must be Signed. A Customer linked to this Lead and a Won/Lost Date must exist. |
| 8  Lost with reason | Inactive Lead | Enter Lost Reason, Detailed Reason and Won/Lost Date together. |
| 9  Lost Quotation | Inactive Lead | Evidence must include a submitted linked quotation marked Lost with a reason. |

Lead, Interested and Qualified lead share the same Lead Status. Changing the stage is the clearest way to move between them. When the user edits only Lead Status, the app preserves an already matching stage or selects its first matching stage and validates the transition.

Source: crm/workflow.py, SPEC_STAGE_MAP and sync_stage_and_status. Server closure checks: crm/stage_flow.py. Paths beginning crm/, ai/, setup/ or public/ are under alphax_crm/.

# WF 01 to WF 03  Stage and quotation events

Creating a draft, submitting a quotation, and moving a Lead to Quotation are separate events. Each has its own evidence, audience and consequence.

| Control | Uploaded 0.43.0 | Revised 0.44.0 and expected result |
|---|---|---|
| 01 • Stage order | Configurable transitions included a manager bypass. | All roles follow Lead → Interested → Qualified lead → Quotation. Quotation branches to Postponed or Contract Under Signing. Each branch can close Won or Lost. A reasoned Lost Quotation may also close directly from Quotation. |
| 01 • Allowed stages | Custom mapping or transition rows could expand the approved list. | The stage picker and server use nine approved values. An old record can retain its legacy value during unrelated edits. Its next manual stage change follows the entry rules. |
| 02 • Quotation existence | Three link paths already checked non-cancelled quotations. | A draft or submitted quotation satisfies existence. Direct Lead, Customer created from Lead, and Opportunity originating from Lead or that Customer are supported. The reverse lookup checks the same owning Lead. |
| 02 • Missing quotation | Owner and current assignees alerted on entry. A 24-hour working day was the default clock. | Queue immediate notice, remind after 24 business hours, escalate to Sales Manager plus the Lead team after 72. The hourly check skips weekends and holidays. A queued missing-quotation alert is suppressed if resolved. |
| 02 • Agent creates quotation | Creation and submission alerts existed. | The first save alerts configured approvers, including for drafts. Submission can separately notify approvers. Creation notification is recorded in the transaction that creates the quotation. |
| 03 • Submission and contents | Confirmation existed at docstatus = 1. | Owner and creator receive “Your quotation has been created successfully” with number, date, Valid Till, amount/currency and Lead/company name. A draft cannot trigger this confirmation. |
| 03 • Stage and validity | Valid Till enforced at validation. Stage move attempted and errors could be swallowed. | A Lead-linked draft requires Valid Till. Submitting a quotation advances an earlier Lead to Quotation, synchronizes Prospect and records the move. A later stage is preserved. Failure of the stage move aborts submission. |

Business-hour example: with 08:00–17:00 and no holidays, Thursday 15:00 to Tuesday 12:00 totals 24 business hours. The hourly scan issues its alert at the next eligible run.

Source: hooks.py, crm/workflow.py, crm/automation.py, crm/stage_flow.py, crm/emails.py.

# WF 04  Quotation validity and loss follow up

At 08:00 site time on working days the app reviews submitted Open and Replied quotations. It includes Expired quotations so weekend expiry and overdue escalation remain actionable. Configure the site for Asia/Riyadh.

| Control | Uploaded 0.43.0 | Revised 0.44.0 and expected result |
|---|---|---|
| Schedule and scope | Daily job existed with a 2,000-row cap and a 60-day backward limit. | Paged scan processes qualifying quotations. Closed Leads are excluded from expiry notices. Cancelled and draft quotations are excluded. |
| Qualifying activity | Lead and quotation email, comments, follow-up logs, meetings, notes, closed ToDos and stage history were checked. Any Communication medium could be labelled email. | Checks human comments, email and closed ToDos on the Lead or quotation. Lead follow-up logs, linked events, CRM notes and stage transitions also qualify. System notices, postponed placeholders and entry into Quotation are excluded. |
| Two days before expiry | Working-day calculation and email selection could diverge from the requested date or Lead language. | Target is Valid Till minus two calendar days. If that day is closed, use the preceding working day. With activity, send a validity notice only. Without it, remind the owner and save an AI draft for review. |
| Draft prerequisites | Required quotation contact email and a working AI provider. | Use the quotation contact or linked Lead email. A generation failure leaves the internal reminder active and records Draft unavailable. Correct the issue and use Draft Expiry Reminder. |
| On Valid Till | Owner and approvers alerted if there was no activity. | Ask the owner and Sales Manager to extend, postpone or record a loss. A nonworking expiry is evaluated on the next eligible run. The most urgent applicable expiry milestone takes priority after an outage. |
| Three days after expiry | Proposed Lost Quotation after inactivity. | Escalate after three calendar days if no post-expiry action and the linked Lead remains at Quotation. This writes a proposal. Confirm Lost Quotation requires an authorized user to select a submitted quotation and a reason. |
| Daily lost follow-up | Summary used Leads in Lost Quotation, capped at 500. A lost quote on a still-open Lead could disappear from the report. | Approvers receive one reference-linked follow-up per submitted Lost quotation per working day, including where another quotation keeps the Lead open. A linked Lead gets timeline evidence. Correction-state Leads are paused. |

Acceptance example: give one Lead two submitted quotations. Mark one Lost with a reason. Keep the Lead open, include the lost quotation in the manager’s daily follow-up, and continue validity monitoring for the other.

Source: crm/workflow.py (wf04_daily, _wf04_quotation, lost_quotation_digest), crm/automation.py (activity_since), ai/sales.py.

# WF 05  Stage activity and reminder timing

Stage milestones use calendar days. Delivery waits for working hours. Day 0 means the creation or stage-entry date. The daily idle indicator and a stage’s required action answer different questions.

| Control | Uploaded 0.43.0 | Revised 0.44.0 and expected result |
|---|---|---|
| Lead • first contact | Day 3 and Day 7 rules existed. The second timer used creation, even if the first reminder arrived late. A separate due-date job could also notify on Day 1. | First contact is expected within one day. The owner receives the first reminder on Day 3 if contact is missing. Send the second at least four calendar days after the first was actually issued. An internal comment alone does not prove contact. |
| Interested • meeting | Any activity suppressed Day 3 and Day 7 notices. | An Event linked through its participants or a Meeting follow-up supplies the evidence. A comment or ordinary email leaves the owner’s Day 3 reminder and manager’s Day 7 escalation eligible. |
| Qualified lead • quotation | An unrelated note could suppress the quotation SLA. | At Day 5 remind the owner if no linked non-cancelled quotation exists. At Day 10 escalate to approvers. A draft satisfies preparation, while submission remains the WF-03 milestone. |
| Quotation | WF-02 to WF-04 already covered this stage. | Use missing-quotation alerts, submission confirmation and validity follow-up. |
| Postponed • next date | Mandatory Next Contact Date and a prefilled follow-up record existed. | Choose a current or future date when entering the stage. The Lead holds that date. A placeholder follow-up has no next-follow-up date and does not count as client contact. The owner receives the due reminder. |
| Postponed • exception | 30-day fallback existed. Any activity could suppress a missing-comment escalation. | For legacy records without a date, revisit 30 days after entry. On the first working run at least a day overdue, notify approvers if no human comment was added during the postponement. |
| Contract Under Signing | Three-day reminders and Day 4 manager check existed. General activity could suppress the Day 10 escalation. | Owner follow-up every three days. Manager check on Day 4 and escalation on Day 10 while still under signing. An overdue Expected Closing Date alerts owner and approvers. Read the Lead closing date first, then its Opportunity. |
| Idle days and correction | Monitor depended on configured statuses and captured activity. Queued reminders could outlive a correction-state change. | Refresh active pipeline idle days daily from last activity or creation. Include linked meetings, notes, closed ToDos and stage history. Check Returned for Correction at evaluation and again during queued reminder delivery. |

Example: a Day 3 reminder due Friday goes out Sunday. If contact is still missing, the second reminder first becomes eligible Thursday. For old records lacking stage history, the app uses the later of creation and the recorded workflow go-live date.

Source: crm/workflow.py (_sla_lead, postponed_daily, contract_close_daily), crm/lead.py, crm/tasks.py and crm/automation.py.

# WF 06 and WF 07  Closure and AI assistance

ERPNext validates closure evidence during save. The model produces a draft, classification or recommendation. A user action authorizes a client email or stage change.

| Control | Uploaded 0.43.0 | Revised 0.44.0 and expected result |
|---|---|---|
| 06 • Won | Checks existed, but missing site fields could silently weaken validation. | Install/migrate creates missing Lead fields without replacing existing definitions. Require Signed, a Customer whose lead_name matches the Lead, and Won/Lost Date. A same-name Customer is insufficient. |
| 06 • Lost with reason | Required fields were checked only when present. | Require Lost Reason, Detailed Reason and Won/Lost Date. Whitespace-only reasons fail. |
| 06 • Lost Quotation | Manual Lead validation checked loss evidence. The direct quotation guard and old repair path could behave differently. | Check the submitted Lost quotation and its reason. Indirect links use the same closure handler. Another active submitted quotation keeps the Lead open. Cancelling a quotation alone does not close the Lead. |
| 07 • Lead brief | AI summary used recent activity and open items. Quote context used only direct links. | Open AI Lead Brief to summarize history, latest interaction, pending tasks, follow-ups and the pending decision. Quotation context includes indirect links. Same-day interactions are ordered by timestamp. |
| 07 • Arabic or English | Some Desk dialogs defaulted to English and explicit English could be overridden by detected Arabic. | Leave Language blank for automatic choice. Explicit Lead Arabic/English takes priority, then latest inbound text, intake text, and configured default. Review recipient, language and content before approval. |
| 07 • Inbound intent | Five requested intents and suggested-stage handling already existed. | A received client email can suggest interested, revision, postpone, rejected or ready to sign. Other is the fallback. Suggested Stage is recorded separately. Apply Suggested Stage checks write permission and normal stage/closure rules. |
| 07 • Score and next action | Rule-based score with breakdown and AI next action existed. Optional automatic ToDo creation was available. | Review score (0–100), contributing rule points and engagement, then the suggested action, channel and timing. Recommendations write advisory Lead fields and issue a notification. |
| 07 • Human confirmation | Approved draft dispatch existed. A content change could retain the previous approval. | Approve the draft or use Send Now explicitly. An edit to an approved recipient, CC, subject or body returns it to Draft. The worker checks status and approver and serializes concurrent sends. The model has no stage-commit or email-send command in these paths. |

Quotation submission under WF-03 is a user-confirmed ERP transaction. Its deterministic stage update is the explicit exception to manual no-skip progression. Scoring uses configured rules so the salesperson can explain the result without interpreting model output.

Source: crm/stage_flow.py, crm/quotation.py, ai/sales.py, api/ai.py, crm/lead.py and doctype/alphax_email_draft.

# C  Notification and audit controls

Use the Automation Log for workflow decisions, the Lead timeline for the sales record, and Email Queue for transport status. These records answer different operational questions.

| Control | Uploaded 0.43.0 | Revised 0.44.0 and expected result |
|---|---|---|
| C1 • Both channels | Central notifications supported both channels. WF-07 could explicitly request in-app only. | WF-07 intent and next-action notifications now use the same channels and hours as the workflow. Keep Notify by Email, each rule and each email row enabled. Email uses the ERPNext outgoing account. |
| C1 • Timeline | Lead-specific messages linked an automated Communication. A global loss digest had no Lead reference. | Lead-linked notifications create a Communication and timeline note. Daily losses carry a quotation reference and the resolved Lead. If a quotation has no Lead, its quotation and log are the available references. |
| C2 • Working calendar | Site time zone and calendar were configurable. Some AI alerts bypassed the hours check. | Use Asia/Riyadh, Sunday–Thursday, configured business hours and Holiday List. Out-of-hours notifications queue. The five-minute outbox checks opening hours. The exact email arrival time depends on workers and mail transport. |
| C3 • Duplicate prevention | Automation Log used a unique dedupe key. Parallel delivery of an already queued row was unguarded. | A database-unique notification identity covers Lead + Rule/milestone + Reference + Trigger Date. Prior release keys continue to suppress historical duplicates. Row locking protects queued dispatch. Re-running a scan should yield one notification for the same milestone. |
| C4 • AI writes | Optional AI ToDos and background Opportunity brief writes extended beyond the requested Lead scope. | Lead AI stores its own advisory fields, system comments and notifications. Reviewed drafts and audit records are app-owned support records. The old AI ToDo path is removed. Opportunity briefs are now on demand and returned for display. |
| C5 • Action history | An in-app failure could still be counted as successful. Some draft and placeholder actions lacked explicit workflow audit rows. | Rule records hold Lead/reference, recipients when applicable, time, result and delivery status. Draft creation, unavailable drafts and postponed placeholders have explicit entries. Stage changes also have a transition history. AI request diagnostics use the AI log. |
| C5 • Delivery evidence | Internal “Sent” could be mistaken for an SMTP receipt. | Check Queued, Sent, Partly Sent, Failed or Skipped in AlphaX Automation Log. Match Communication to Email Queue and the test mailbox. An accepted queue entry establishes handoff to ERPNext. Mailbox receipt is a separate test. |

Implementation boundary: these checks cover the packaged Lead workflow, AI methods and their notifications. A separately provisioned API user, other installed apps, third-party integrations and SMTP transport require site-level verification. Do not give the external AI service a general ERP write credential.

Source: crm/automation.py (notify, deliver, flush_outbox, log_action), crm/emails.py, ai/sales.py, ai/engine.py and hooks.py.

# Site configuration and release decisions

Use a staging copy with representative Lead customizations before promoting the release. Existing site settings and customized email templates can change what people receive.

| Control | Uploaded 0.43.0 | Revised 0.44.0 and expected result |
|---|---|---|
| 1 • Install and migrate | Deploy the extracted alphax_crm app on the staging bench. Take a site backup and retain the current app revision. | Run bench --site SITE migrate, build the app assets through the normal deployment process, then reload Desk. On managed hosting, use the equivalent deploy/migrate action. |
| 2 • Business calendar | In System Settings set Asia/Riyadh. In AlphaX CRM Settings set Sun–Thu, business start/end and Holiday List. | 08:00–17:00 is the supplied default. The 24/72 clocks accrue only inside business windows. Confirm the team’s hours, especially holiday and seasonal schedules. |
| 3 • Routing and mail | Set Approver Role to Sales Manager or the actual approver role. Assign active users with email addresses. Configure the default outgoing account. | Enable the scheduler, long and short workers, in-app notifications, business-hours-only delivery, workflow rules and rule email rows. Run AlphaX CRM Settings → Health Check. |
| 4 • Fields and rules | Verify the nine Lead stages, status mapping, required closure fields, next-contact and expected-close dates. Enable stage flow, stage protection and closure controls. | Compare the installed SLA rows with page 5. Turn on scoring and activity capture. Existing custom rules, holiday lists and site scripts need review on upgrade. |
| 5 • AI configuration | Configure the provider, model, credentials and enabled AI features, including quotation drafts and inbound intent. Enable AI request logging. | Use a test mailbox and model endpoint for UAT. Ensure both languages work. Keep AI write credentials separate from user credentials. Review custom templates for WF-05 wording and both-channel delivery. |
| 6 • Business interpretations | The request named three quotation links and specified the direct one. The app already uses Customer and Opportunity as the other two. | Retained those links. A draft satisfies existence and preparation. Submission triggers confirmation. A due date that falls outside working time follows the calendar policy described on pages 4–5. |
| 7 • Other decisions | The request asks for daily loss follow-up, a blank Postponed follow-up and a second Lead reminder four days after the first. | One daily manager notice per Lost quotation provides its own timeline trail. The mandatory agreed date is on the Lead. The blank placeholder is separate. The second reminder is anchored to internal dispatch of the first. |

Rollback: keep the staging backup and matching 0.43.0 source together. A code-only downgrade can leave migrated fields, templates, scheduled jobs and audit records in the database. Use the organization’s tested site restoration process if rollback is needed.

Primary administrator entry points: AlphaX CRM Settings, Health Check, System Settings, Email Account, Email Queue, Scheduled Job Type, AlphaX Automation Log.

# Staging acceptance and evidence

Use a sales user, an assigned colleague, a separate quotation creator, an approver and controlled test mailboxes. Capture document IDs, timestamps, log rows and actual received messages for the following cases.

| Control | Uploaded 0.43.0 | Revised 0.44.0 and expected result |
|---|---|---|
| A / WF-01 | Walk every permitted branch. Attempt Lead → Won through Desk, list edit and ordinary REST save as both agent and manager. | Verify each status mapping, rejection of the skip, the blank Contract rule and preservation of a later stage after saving a linked Customer or quotation. |
| WF-02 / WF-03 | Try direct Lead, Customer and Opportunity links. Enter Quotation without a quote. Add a draft, submit it, then cancel a separate test quote. | Check owner and assignees, 24/72 business hours, approver notice on creation, confirmation only on submit, all five detail fields, and timeline entry. Missing Valid Till must block save. |
| WF-04 | Use separate quotations for T−2 with and without activity, expiry, T+3 and a weekend expiry. Try each qualifying activity. Repeat the jobs. | Verify correct channel, recipients and draft language. Confirm no automatic client email or loss. Resolve an expiry by extension, postponement or explicit loss. A second open quote preserves the Lead. |
| WF-05 • Early stages | Simulate a Day 3 reminder delayed to Sunday. Add a comment but no meeting to Interested. Add a meeting but no quote to Qualified lead. | Check second Lead reminder on Thursday, meeting reminder/escalation on Days 3/7, and quotation reminder/escalation on Days 5/10. Then add the required evidence and repeat. |
| WF-05 • Later stages | Postpone with and without a date. Check an old dateless record at 30 days. Add email only, then a real comment. Let a contract remain unsigned for ten days. | Confirm blank follow-up, missing-comment escalation, Days 3/6/9 owner notices, Day 4 manager notice, Day 10 escalation and expected-close warning. Test correction pause with a queued reminder. |
| WF-06 / WF-07 | Remove each Won or Lost prerequisite in turn. Process Arabic and English inbound test emails. Review an AI draft, approve, edit it, and approve again. | Closure must fail until evidence is complete. Capture brief, intent, suggestion, score explanation and next action. Verify the edit requires fresh approval and only an explicitly approved email leaves the queue. |
| C • Delivery and isolation | Run the same milestone twice and dispatch a queued row from two workers. Trigger after closing, on a holiday and before opening. Check actual service-account permissions. | Expect one audit identity per milestone, correct timeline and channels during business hours, no duplicate email, and accurate failure results when the account is unavailable. Verify access with real role assignments. |

Release decision: promote after the sales owner accepts workflow behavior and the ERPNext administrator records successful site tests. Historical tests in the archive change settings and create test data. Run them only on a disposable staging site.

Test evidence in this release: tests/test_approved_workflow.py and the standalone test suite. Site and browser scenarios are included for the implementation team.
