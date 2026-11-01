# AlphaX CRM 0.41 — compliance with the approved Lead workflow

Status per requirement after the 0.41 audit. "Before" is what 0.39/0.40 did. Every "Now" item is covered by an
automated scenario test on an ERPNext v15 site (`tests/site_workflow_test.py`, 92 checks incl. the independent-review regressions; browser test
`tests/ui_workflow_test.py`).

Legend: ✅ met · ⚠️ met with a note · 🔧 site setup needed

## A. Approved workflow and stage mapping

| Requirement | Before | Now |
|---|---|---|
| Flow Lead → Interested → Qualified lead → Quotation → Postponed / Contract Under Signing → Won / Lost | Transitions seeded | ✅ Seeded + *Quotation → Lost Quotation* added (needed by WF-04). Only these stages are selectable. |
| 9-row Stage → Status mapping | 6 rows, one direction (Status → Stage); "Lead" mapped to *Qualified lead* | ✅ 9 approved rows, both directions. Changing the stage sets Lead Status; changing Lead Status picks the matching stage. |
| Contract: Blank (Contract Under Signing) / Signed (Won) | Won checked | ✅ Won requires Contract = Signed (WF-06). |

## B. Workflows and controls

| Requirement | Before | Now |
|---|---|---|
| **WF-01** stages cannot be skipped | Checked on form saves only | ✅ Also list-view quick edits and Kanban; ERPNext core can no longer change the stage behind the user's back. |
| WF-01 no stages outside the flow | Not enforced | ✅ Blocked; new/imported leads start at *Lead*; legacy values (Open, Replied…) continue from *Lead*. ⚠️ System Manager can bypass (setting). |
| **WF-02** quotation must exist at stage *Quotation* (direct link; also via Customer / Opportunity) | Missing | ✅ Immediate alert to owner + assigned users; reminder after 24 working hours; escalation to Sales Manager after 72. |
| WF-02 approvers notified when an agent creates a quotation | Only on submit, in-app only | ✅ On creation and on submission, email + in-app. |
| **WF-03** confirmation on submit to Lead Owner + creator (No., Date, Valid Till, Amount, Lead/Company) | Missing | ✅ Email + in-app, logged on the Lead timeline. |
| WF-03 move earlier-stage Lead to *Quotation* + timeline log | Core moved it silently (and also from later stages) | ✅ Only from earlier stages, logged; later stages are kept. |
| WF-03 Valid Till mandatory on Lead quotations | Missing | ✅ Enforced. |
| **WF-04** daily 08:00 Sun–Thu, Open/Replied quotations | Missing | ✅ Also follows quotations ERPNext has already marked *Expired* (needed for T0 on weekend expiries and T+3). T-2 counted in working days. |
| WF-04 qualifying activity (email, comment/follow-up, meeting, CRM note, closed ToDo, stage change) | — | ✅ All counted; AlphaX's own notes and automated emails are not. |
| WF-04 T-2: reminder + AI draft (no activity) / notice (activity) | — | ✅ AI draft saved for review, never sent automatically. |
| WF-04 T0: owner + Sales Manager | — | ✅ |
| WF-04 T+3: escalate and propose Lost Quotation, user confirms (if no action) | — | ✅ Proposal shown on the Lead; **Confirm Lost Quotation** marks the quotation Lost with a reason. |
| WF-04 daily lost-quotation follow-up to Sales Manager | Full list every day, in-app | ✅ New since last working day + total + top reasons, email + in-app. |
| **WF-05** Lead: reminders day 3 and 4 days later (day 7) | Second reminder suppressed by AlphaX's own note | ✅ |
| WF-05 Interested day 3 / 7, Qualified day 5 / 10 | Day counted from Lead creation | ✅ Counted from entering the stage. |
| WF-05 Postponed: Next Contact Date mandatory; next follow-up created; reminder on the date; 30-day default; Sales Managers told if no comment | Date not enforced; placeholder counted as activity | ✅ Date chosen when postponing (form prompt); follow-up created with that date; overdue + no comment → Sales Managers. |
| WF-05 Contract Under Signing: every 3 days, day 4 approver, day 10 escalation, Expected Closing Date passed | Fixed days 3/6/9; no closing-date alert | ✅ Repeats every 3 days; closing-date alert (Lead field or the Lead's Opportunity). Milestones missed over a weekend/holiday are sent on the next working day. |
| WF-05 idle days recalculated daily | ✅ | ✅ Repeated reminders measure idle time from the previous reminder. Leads already in a stage at go-live start counting from installation (no reminder flood). |
| WF-05 pause while *Returned for Correction* | Missing | ✅ All reminders (WF-02/04/05). |
| **WF-06** Won: Contract Signed, Customer created, Won/Lost Date | ✅ but core then forced *Converted* | ✅ |
| WF-06 Lost with reason: reason, details, date | ✅ | ✅ |
| WF-06 Lost Quotation: linked quotation marked Lost with reason | Checked Lead fields instead | ✅ |
| **WF-07** lead brief (history, last interaction, open items) | Partial (classification on creation) | ✅ **AI Lead Brief**. |
| WF-07 follow-up drafts in the lead's language | Language chosen by user | ✅ Defaults to the client's latest message language. |
| WF-07 intent detection with suggested stage | Missing | ✅ interested / revision / postpone / rejected / ready to sign → suggested stage; user applies it. |
| WF-07 lead score with explanation + next best action | ✅ (0.40) | ✅ |
| WF-07 AI never changes stage / sends emails / modifies transactions without confirmation | ✅ | ✅ Verified in tests. |

## C. General controls

| Requirement | Before | Now |
|---|---|---|
| In-app + email via the ERPNext email account, logged on the Lead timeline | In-app only | ✅ 🔧 needs a default outgoing Email Account (health check). |
| Working days and business hours only (Asia/Riyadh) | Ran at any time incl. weekends | ✅ Daily rules run as long-queue jobs (large pipelines). Sun–Thu 08:00–17:00 by default, optional Holiday List; queued outside hours. 🔧 System time zone must be Asia/Riyadh (health check). |
| No duplicates: Lead + Rule + Reference + Trigger Date | Subject text match | ✅ Unique key on AlphaX Automation Log. |
| AI write access limited to AI/activity fields, timeline comments, notifications | Next best action created ToDos | ✅ Notification by default (ToDo optional). AI email drafts are saved for review only. |
| Every automated action logged (rule, lead, recipients, time, result) | Partly | ✅ AlphaX Automation Log, including stage changes caused by cancel / Set as Lost. |

## Site setup checklist (run the Health Check after deploying)

1. A default **outgoing Email Account**.
2. **System Settings → Time Zone = Asia/Riyadh**; scheduler enabled; background workers running.
3. Users with the **Sales Manager** role (Approvers) have email addresses.
4. Optional: a **Holiday List** for Eid / National Day in *Working Days & Notifications*.
5. Lead fields used by the spec exist (Lead Status, Contract, Won Or Lost Date, Lost Reason, Detailed Reason).
