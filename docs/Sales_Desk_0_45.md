# AlphaX CRM 0.45.0 sales desk and executive analytics

## Sales desk

Open AlphaX CRM in Desk. The Sales desk card brings together work that needs a response. The Executive analytics card opens the management reports. The existing workflow and reports remain available.

### My Sales Worklist

Shows your owned or assigned active Leads that you can read. Start with overdue items, then today’s items. Days ahead includes upcoming actions. Correction-state Leads are excluded.

### Make first contact or revisit a Lead

Select the action to log a follow-up. Record the channel, outcome and summary. When postponing again, agree a new date. The Lead’s agreed date drives the worklist and Follow-ups Due even when its placeholder follow-up has no date.

### Meetings and quotations

Schedule meeting opens a new Event linked to the Lead. Prepare quotation opens a Lead quotation. Review draft quotation and Review email draft open the actual record. Save or submit the document to complete the action, then refresh the report.

### Manager Exceptions

Filter by executive and Open or Resolved. Open the action record and choose Manage exception. Assign delegates the Lead through ERPNext and records the note. Resolve records the decision and the authenticated manager. Missing-quotation exceptions resolve against the quotation ID when a quotation is saved.

### What the owner sees

A colleague may own a Lead while you perform an action on it. Assignment and action history retain those different responsibilities. An executive’s name in a sales report can therefore differ from the name on an action.

**Example**

A colleague owns a postponed Lead due today. You are assigned to it. The item appears in your worklist. You log the call and choose the next date. The history records your user ID and the colleague’s ownership.

## Executive analytics

Open the report from Executive analytics, choose the reporting dates and select an executive when needed. Financial rows retain their own currency. The reports do not combine currencies into a single total.

### Executive Scorecard

New Leads use creation date. Open today is a current workload count. Won and Lost use Won/Lost Date. Win rate is Won divided by Won plus Lost. A blank rate means no dated closures. Lead figures use the current responsible owner, with creator as fallback.

### Who performed the work

User actions, logged follow-ups, logged emails and submitted quotations count the actual executor from the new action history. Automated actions are excluded from these columns. The detailed report shows the owner at the time of each action.

### CRM Action History

Filter by date, responsible executive or Executed by. The report shows the user ID, full name captured at the time, action source, request user when known, event time, source record and details. Manager reports respect access to the source document and linked Lead.

### Expected Close Forecast

Lists visible open Opportunities whose expected closing dates fall within the selected range. Weighted value is the Opportunity amount multiplied by probability. Set expected closing date, owner, currency, amount and probability on each Opportunity for meaningful figures.

### Forecast Movement

Select a date in a reporting week. Compare that week’s captured expected close date and weighted amount with the current close date and Opportunity status. Positive days moved means the deal slipped. Weeks start Sunday. The first daily job that runs in the week captures its baseline.

### Quotation Revisions

One row represents a visible amendment or explicit replacement family. Compare the original amount, latest version, latest submitted amount and loss reason. The date filter uses the latest version’s transaction date. Use Replaces Quotation for a separately created replacement. Only link the same company, party and currency. A later draft does not supersede the submitted value.

**Reading the figures**

A SAR 100,000 original and its SAR 95,000 submitted replacement appear as one family with a SAR 5,000 decrease. Separate, unrelated offers remain separate. Review Business unit where the site has a mapped value.

## Action history and delivery

Action history begins when v0.45.0 is installed and migrated. Older documents keep their existing ERPNext owner, modified-by, timeline and workflow evidence. The release does not infer missing historical actors.

### Action coverage

Captures Lead, Opportunity, Quotation, PreLead, Smart Lead, linked Customer, follow-up and draft lifecycle events, plus relevant comments, communications, Events, ToDos, exception decisions, delivery retries and workflow log actions. Direct SQL writes or unrelated third-party integrations require their own evidence.

### Human and automated execution

An interactive action records its authenticated user and full name. A background action records the executing service account and Automation. An in-request automated action can also retain the initiating request user. The responsible executive is captured separately. An inbound email does not earn salesperson activity credit.

### AI evidence and approval

View intent source email opens the actual Communication. Apply Suggested Stage follows normal permissions and validations. Dismiss stage suggestion records your decision. Next action evidence lists valid source records cited by the model when it returns citations. Client emails still require a user-approved draft.

### Partial notification delivery

Open AlphaX Automation Log and inspect Recipient delivery history. Each row identifies the recipient, channel, attempt time, executor and result. A System Manager can select Retry failed channel to replay just a failed handoff during working hours. Successful channels stay complete.

### Email Queue and legacy rows

Queued means ERPNext accepted the message for delivery. Email delivery status opens the accessible Email Queue entry. An SMTP failure after handoff is handled in Email Queue. Older partial logs have no recipient receipts, so inspect their queue evidence before any manual resend.

### Deployment and acceptance

Deploy the app to a staging bench, migrate the site and build assets through your normal release process. Refresh Desk. Confirm the new workspace cards, roles, default outgoing email account, Asia/Riyadh time zone, scheduler and queue workers.

**Release verification**

The packaged release passed 43 local tests, including the original workflow suite and 11 new cases using simulated data. Site migration, Desk interaction, real role permissions, SMTP delivery, AI output and weekly scheduler execution require staging acceptance.

## Staging acceptance

Use separate users for the sales executive, assigned agent, manager and system administrator. Record the actual document IDs and compare the history, report rows and recipient receipts.

### 1  Assignment and attribution

Create a Lead as user A and give ownership to B. Have assigned user C log a follow-up. Expect C’s full name and user ID in Action History, B as responsible executive, and one user follow-up under C. Later reassignment must preserve this historical ownership.

### 2  Postponed date

Postpone a Lead to today with a blank placeholder follow-up. Confirm My Sales Worklist and Follow-ups Due each show the agreed date, with one current follow-up row. Log the next date and refresh.

### 3  Manager exception

Generate a missing-quotation escalation. Create a linked quotation. Verify the resolved exception identifies it. Cancel that sole quotation while the Lead is still at Quotation and verify the exception reopens.

### 4  Targeted retry

Make one test recipient’s email handoff fail while their in-app alert succeeds. Restore the email address and retry the failed email. Expect one new email attempt, no extra in-app alert and the administrator’s identity on the retry. Check SMTP results in Email Queue.

### 5  Commercial analytics

Save an original offer and a replacement with Replaces Quotation. Confirm one family and the correct amount change. Capture a weekly baseline, change the Opportunity closing date by seven days, and verify a seven-day slip.

### 6  AI evidence and access

Process an inbound Arabic email. Open its source from the Lead, dismiss or apply the stage suggestion and review the action history. Use a restricted account to confirm source links and reports respect its permissions. Verify an unapproved client email remains a draft.

**Release scope**

No deployment or outbound email was performed in preparing this release. Use the existing CRM workflow guide for the approved stages, closure controls, working calendar and escalation timings.
