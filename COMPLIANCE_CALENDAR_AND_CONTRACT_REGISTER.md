# Compliance Calendar And Contract Register

This document explains how the Compliance Calendar and Contract Register currently work in OrgOS, what creates them, how they connect to the rest of the system, and whether the current implementation matches the intended behaviour.

The short version is:

- Compliance Calendar tracks regulatory, statutory, licensing, and certification obligations.
- Contract Register tracks parent contracts, their owners, counterparties, expiry/review dates, and standards relevance.
- Both are Tier 1 foundation registers.
- Both currently work as basic registers with calculated date status.
- Both are not yet fully connected to extraction, Gap Analysis, Document Lifecycle, Control Register, and Evidence Tracker in the way the intended governance model requires.

---

## 1. What These Registers Are For

### Compliance Calendar

Compliance Calendar answers:

> What external or recurring compliance obligation must Dragnet perform, by when, for which authority, and who owns it?

Examples:

- PAYE remittance
- VAT filing
- PenCom return
- NDPC notification or filing
- Licence renewal
- ISO surveillance audit
- Annual regulatory report
- Statutory filing

The Compliance Calendar is not mainly a document register and not mainly a control register. It is a deadline and obligation register.

It should make sure that recurring duties do not live only in people’s heads or scattered email reminders.

### Contract Register

Contract Register answers:

> What contracts exist, who owns them, when do they expire or need review, and what obligations or controls do they create?

Examples:

- Client master service agreement
- Vendor contract
- Data processing agreement
- NDA
- SLA
- Partner agreement
- Employment agreement
- Cloud service contract

The Contract Register is the parent record for agreements. A contract can contain clauses that later become controls, evidence requirements, renewal actions, or risk obligations.

---

## 2. Current Code Locations

### Shared Backend

Both modules are implemented inside the shared Tier 1 `grc` module.

- `grc/schemas.py`
  - Defines the data contracts for Compliance Calendar and Contract Register.

- `grc/service.py`
  - Handles SharePoint reads/writes.
  - Calculates status from due dates and expiry dates.

- `grc/router.py`
  - Exposes API endpoints.

- `grc/constants.py`
  - Maps Python field names to SharePoint column names.

### Frontend

Compliance Calendar:

- `frontend/src/pages/ComplianceCalendar/index.jsx`
- `frontend/src/pages/ComplianceCalendar/CalendarForm.jsx`

Contract Register:

- `frontend/src/pages/ContractRegister/index.jsx`
- `frontend/src/pages/ContractRegister/ContractForm.jsx`

Shared hooks/API:

- `frontend/src/hooks/useGrc.js`
- `frontend/src/api/grcApi.js`

---

## 3. Compliance Calendar Current Behaviour

### API Endpoints

The Compliance Calendar endpoints live under:

```text
/api/v1/grc/compliance
```

Current endpoints:

```text
GET   /api/v1/grc/compliance
GET   /api/v1/grc/compliance/overdue
GET   /api/v1/grc/compliance/due-soon
GET   /api/v1/grc/compliance/{id}
POST  /api/v1/grc/compliance
PATCH /api/v1/grc/compliance/{id}
```

There is no delete endpoint in the current router section inspected.

### Fields

Current Compliance Calendar fields:

- `obligation_name`
- `type`
- `authority`
- `due_date`
- `recurrence`
- `owner`
- `status`
- `created`
- `modified`

### Obligation Types

Current valid types:

- `Statutory`
- `Licensing`
- `Certification`
- `Regulatory`

### Recurrence

Current valid recurrence values:

- `Monthly`
- `Quarterly`
- `Annual`
- `Once`

### Status

The schema defines:

- `Overdue`
- `Due Soon`
- `Upcoming`
- `Completed`

But in the current service logic, status is calculated only from the due date.

Current status calculation:

```text
due_date < today                     -> Overdue
today <= due_date <= today + 30 days -> Due Soon
due_date > today + 30 days           -> Upcoming
```

Important:

Status is not manually stored or updated by users. It is recalculated every time the API reads the item.

This is good for date-based status because the system does not need a background job to flip `Upcoming` to `Due Soon` or `Overdue`.

### Frontend Behaviour

The Compliance Calendar page currently:

- lists obligations
- sorts by urgency
- lets users search obligations
- shows detail view
- allows adding a new obligation

The add form collects:

- obligation name
- type
- authority
- due date
- recurrence
- owner

The detail page tells the user:

```text
Status is calculated automatically from the due date. It cannot be manually set.
```

That matches the current backend behaviour.

---

## 4. Is Compliance Calendar In The Intended Behaviour?

Partially yes.

The current implementation is aligned with the intended behaviour in these areas:

- It exists as a Tier 1 register.
- It tracks statutory, licensing, certification, and regulatory obligations.
- It assigns each obligation to a person.
- It has due dates.
- It calculates status automatically.
- It supports overdue and due-soon views.

But it is not fully aligned yet.

### Intended Behaviour Not Fully Implemented

#### 1. Completion Workflow

The schema includes `Completed`, but the backend does not currently provide a real completion flow.

Today, if an obligation is due yesterday, it becomes:

```text
Overdue
```

There is no proper action like:

```text
Mark completed
```

There is also no completion evidence, completion note, completed date, or completed by.

For recurring obligations, completion should roll the due date forward.

Example:

```text
Monthly PAYE remittance due 2026-06-10
Completed on 2026-06-09
Next due date becomes 2026-07-10
```

#### 2. Recurrence Is Stored But Not Applied

The system stores recurrence, but does not use it to calculate the next obligation date after completion.

Intended behaviour should be:

- Monthly obligations roll forward by one month.
- Quarterly obligations roll forward by one quarter.
- Annual obligations roll forward by one year.
- Once obligations can become completed/archived.

#### 3. No Source Document Link

Regulatory obligations should ideally link back to the source that created them.

Examples:

- NDPA document
- regulatory guideline
- audit finding
- extracted queue item
- document register item

Current Compliance Calendar records do not appear to store a source document code or source URL in the schema.

#### 4. Not Fully Integrated With Extraction

The extractor has logic for regulatory obligation candidates, and bulk extraction can write obligation-related fields to the AI Review Queue.

However, Compliance Calendar creation is still mostly manual through the Tier 1 form.

Intended behaviour should be:

```text
Regulatory document extraction
        |
        v
AI Review Queue obligation item
        |
        v
Human accept/edit
        |
        v
Compliance Calendar entry
```

That full human-in-the-loop cascade is not clearly complete yet.

#### 5. Not Fully Integrated With Gap Analysis

Gap Analysis has the concept of an `Obligation gap`.

That means:

> A regulatory or statutory obligation exists but is not tracked in the Compliance Calendar.

The Gap Analyzer comments mention obligation gaps, but the current active logic mainly checks controls, evidence, and ownership. It does not deeply compare regulatory obligations against the Compliance Calendar yet.

Intended behaviour should be:

```text
Regulatory requirements
        |
        v
Compliance Calendar coverage check
        |
        v
Missing obligation -> Gap Analysis item
```

#### 6. No Reminder/Escalation Workflow

Due Soon and Overdue are visible, but there is no full escalation path.

Intended behaviour should include:

- notify owner when obligation becomes due soon
- escalate to Compliance Lead when overdue
- optionally create Gap Analysis item for missed critical obligations
- optionally create Strategic Risk if repeated or material

---

## 5. Contract Register Current Behaviour

### API Endpoints

Contract Register endpoints live under:

```text
/api/v1/grc/contracts
```

Current endpoints:

```text
GET   /api/v1/grc/contracts
GET   /api/v1/grc/contracts/expiring
GET   /api/v1/grc/contracts/{id}
POST  /api/v1/grc/contracts
PATCH /api/v1/grc/contracts/{id}
```

There is no delete endpoint in the current router section inspected.

### Fields

Current Contract Register fields:

- `contract_reference`
- `title`
- `counterparty`
- `contract_type`
- `owner`
- `start_date`
- `end_date`
- `review_date`
- `applicable_standards`
- `status`
- `linked_controls_count`
- `created`
- `modified`

### Contract Types

Current valid types:

- `Client`
- `Vendor`
- `Partner`
- `Employment`
- `NDA`
- `Other`

### Status

The schema defines:

- `Active`
- `Expired`
- `Under Review`
- `Terminated`
- `Expiring Soon`

But the current service logic calculates only:

- `Active`
- `Expired`
- `Expiring Soon`

Current status calculation:

```text
end_date is empty                         -> Active
end_date < today                          -> Expired
today <= end_date <= today + 60 days      -> Expiring Soon
end_date > today + 60 days                -> Active
```

Important:

Like Compliance Calendar, contract status is calculated on read. It is not manually set in the current form.

### Frontend Behaviour

The Contract Register page currently:

- lists contracts
- supports search
- shows detail view
- allows adding a contract

The add form collects:

- reference code
- title
- counterparty
- type
- owner
- start date
- expiry date
- review date
- applicable standards

The detail view says:

```text
Contract clauses feed into the Control Register. Source field = "Contract".
```

That describes the intended direction, but the current Contract Register page itself does not trigger clause extraction or Control Register creation.

---

## 6. Is Contract Register In The Intended Behaviour?

Partially yes.

The current implementation is aligned with intended behaviour in these areas:

- It exists as a Tier 1 register.
- It tracks contract reference, title, counterparty, owner, dates, and type.
- It calculates expiry status automatically.
- It supports an expiring-contracts endpoint.
- It allows applicable standards to be recorded.

But it is not fully aligned yet.

### Intended Behaviour Not Fully Implemented

#### 1. Manual Contract Lifecycle Status

The schema includes `Under Review` and `Terminated`, but the status calculation does not allow those states to persist.

If a contract is terminated before its end date, the current status function would still show:

```text
Active
```

because it only looks at `end_date`.

Intended behaviour should separate:

- calculated expiry status
- manual lifecycle status

Recommended approach:

- `LifecycleStatus`: Active, Under Review, Terminated, Superseded
- `ExpiryStatus`: Active, Expiring Soon, Expired

Or keep one `Status` but make manual statuses override date calculation.

#### 2. Renewal Date Is Not First-Class

The schema has:

- `end_date`
- `review_date`

But many contracts need a specific renewal notice deadline.

Example:

```text
Contract expires: 2026-12-31
Renewal notice must be sent by: 2026-10-31
```

The renewal notice date is not the same thing as review date.

Intended behaviour should support:

- expiry date
- renewal notice date
- review date
- auto-renewal flag
- notice period

#### 3. No SharePoint Contract File Link

The Contract Register should ideally link to the actual contract file.

Current visible schema does not include:

- SharePoint file URL
- document register id
- source document code
- extracted document id

Intended behaviour should make each contract traceable to its signed file.

#### 4. No Clause-Level Linkage Yet

The frontend says:

```text
Contract clauses feed Control Register.
```

That is the intended behaviour, but the current Contract Register itself does not show linked clauses or controls beyond `linked_controls_count`.

Intended behaviour should be:

```text
Contract Register parent record
        |
        v
Contract extraction
        |
        v
AI Review Queue contract obligations/controls
        |
        v
Human accept
        |
        v
Control Register + Evidence Tracker
```

Examples of contract clauses that should become controls:

- vendor security review requirement
- SLA monitoring requirement
- breach notification requirement
- confidentiality obligation
- data processing obligation
- audit rights
- backup and availability obligations

#### 5. No Contract Obligation Calendar Feed

Some contract obligations are not controls. They are deadlines.

Examples:

- renewal notice deadline
- annual attestation from vendor
- quarterly service report
- client reporting deadline
- contract review deadline

Those should feed Compliance Calendar.

Current implementation does not clearly cascade contract dates or obligations into Compliance Calendar.

#### 6. No Risk Escalation For Expired Or Critical Contracts

If a critical vendor contract expires or is near expiry, the system currently can display `Expiring Soon` or `Expired`.

But it does not automatically:

- create a Gap Analysis item
- create a Strategic Risk
- escalate to contract owner
- create a Document Lifecycle/legal review task

Intended behaviour should depend on materiality.

Example:

```text
Critical vendor contract expired
        |
        v
Gap Analysis or Strategic Risk
        |
        v
Owner escalation
```

---

## 7. Relationship Between The Two Registers

Compliance Calendar and Contract Register are different, but they should interact.

### Contract Register Can Create Calendar Obligations

A contract can create recurring or date-based duties.

Examples:

- renewal notice
- expiry review
- annual contract review
- SLA reporting
- vendor audit review
- data protection attestation

These should become Compliance Calendar obligations when they are compliance-relevant.

### Compliance Calendar Can Reveal Contract Risk

If a contract-related obligation is overdue, the obligation can point back to the contract.

Example:

```text
Vendor security review due date missed
        |
        v
Compliance Calendar overdue item
        |
        v
Contract Register source
        |
        v
Gap Analysis / Strategic Risk if material
```

---

## 8. Relationship To Extraction

The extractor knows about regulatory and contract document types.

### Regulatory Documents

Regulatory extraction can produce obligation fields such as:

- obligation statement
- deadline
- recurrence
- authority
- standards reference
- penalty if missed

Those should become AI Review Queue items before entering the Compliance Calendar.

Intended flow:

```text
Regulatory document
        |
        v
Extractor finds obligation
        |
        v
AI Review Queue
        |
        v
Compliance Lead reviews/edits
        |
        v
Compliance Calendar
```

### Contract Documents

Contract extraction can identify:

- obligations Dragnet must fulfil
- counterparty obligations
- expiry or renewal dates
- SLA commitments
- data protection clauses
- audit rights
- breach notification clauses

Intended flow:

```text
Contract document
        |
        v
Contract Register parent record
        |
        v
Extractor identifies clauses
        |
        v
AI Review Queue
        |
        +--> Control Register
        +--> Evidence Tracker
        +--> Compliance Calendar
        +--> Gap Analysis if missing/weak
```

Current implementation has the building blocks, but the full cascade is not yet complete.

---

## 9. Relationship To Gap Analysis

Gap Analysis should eventually use both registers.

### Compliance Calendar In Gap Analysis

A missing regulatory obligation should create an `Obligation gap`.

Example:

```text
NDPA requires breach notification within a statutory timeline.
No Compliance Calendar item tracks this duty.
```

Gap Analysis item:

```text
GapCategory: Obligation gap
Severity: Major or Critical
Finding: Regulatory breach notification obligation is not tracked.
```

Current state:

- The concept exists in labels/comments.
- The active Gap Analyzer logic does not fully implement it yet.

### Contract Register In Gap Analysis

Contracts can create gaps when:

- critical contracts are expired
- vendor security obligations are not controlled
- SLA obligations are not monitored
- data protection clauses have no evidence
- renewal notice deadlines are missed

Current state:

- Contract Register is not deeply used by the Gap Analyzer yet.

Intended behaviour:

```text
Contract Register + extracted clauses
        |
        v
Gap Analyzer
        |
        v
Contract compliance gap / evidence gap / risk
```

---

## 10. Relationship To Strategic Risks

Not every overdue obligation or expiring contract is a strategic risk.

But some can become strategic risks.

### Compliance Calendar To Strategic Risk

Examples that may justify strategic risk:

- repeated missed statutory filings
- NDPC breach notification failure
- certification surveillance audit missed
- licence renewal missed
- regulatory penalty likely

The system should escalate based on severity/materiality, not every minor deadline.

### Contract Register To Strategic Risk

Examples that may justify strategic risk:

- critical vendor contract expired
- client contract renewal at risk
- DPA missing for important processor
- SLA breach likely to create penalty
- critical supplier has no enforceable security obligations

Current state:

- There is no direct Contract Register to Strategic Risk cascade.
- Strategic Risk can be manually created if leadership identifies the exposure.

Intended behaviour:

- System flags material contract risk.
- Compliance/Legal reviews.
- ExCo decides whether it becomes Strategic Risk.

---

## 11. What Is Currently Good

### Compliance Calendar

Good current behaviour:

- Simple and clear register.
- Good obligation type enum.
- Good recurrence enum.
- Owner is captured.
- Due Soon and Overdue are calculated live.
- Dedicated due-soon and overdue endpoints exist.
- Frontend clearly explains status is automatic.

### Contract Register

Good current behaviour:

- Simple and clear contract parent register.
- Contract type enum is useful.
- Owner is captured.
- Expiring Soon and Expired are calculated live.
- Expiring endpoint exists.
- Applicable standards can be attached.
- Frontend correctly positions contracts as sources for controls.

---

## 12. What Needs To Be Improved

### Compliance Calendar Improvements

Recommended improvements:

1. Add completion workflow.
2. Add recurring roll-forward.
3. Add completion evidence or note.
4. Add source document fields.
5. Add AI Review Queue accept cascade for extracted obligations.
6. Add Compliance Calendar checks to Gap Analyzer.
7. Add escalation for critical overdue obligations.
8. Add filters for overdue, due soon, upcoming, type, owner, authority.
9. Add edit/update UI.
10. Add link to Document Register or SharePoint source.

### Contract Register Improvements

Recommended improvements:

1. Add manual lifecycle status.
2. Separate expiry status from lifecycle status.
3. Add renewal notice date.
4. Add auto-renewal flag.
5. Add notice period.
6. Add SharePoint file URL.
7. Add extraction linkage.
8. Add linked controls view.
9. Add contract obligations to Compliance Calendar.
10. Add material contract risk escalation.
11. Add edit/update UI.
12. Add filters for status, type, owner, counterparty, expiring soon.

---

## 13. Intended Clean Behaviour

### Compliance Calendar Clean Flow

```text
Regulatory / statutory source
        |
        v
Extractor identifies obligation
        |
        v
AI Review Queue
        |
        v
Compliance Lead accepts/edits
        |
        v
Compliance Calendar
        |
        +--> Due soon reminders
        +--> Completion and recurrence roll-forward
        +--> Overdue escalation
        +--> Gap Analysis if obligation is missing or missed
        +--> Strategic Risk if material
```

### Contract Register Clean Flow

```text
Contract document
        |
        v
Contract Register parent record
        |
        v
Extraction of clauses, dates, obligations
        |
        +--> AI Review Queue for controls
        +--> Compliance Calendar for deadlines
        +--> Evidence Tracker for proof requirements
        +--> Gap Analysis for weak/missing coverage
        +--> Strategic Risk for material exposure
```

---

## 14. Final Assessment

### Is Compliance Calendar In Intended Behaviour?

Yes, but only at the foundation level.

It correctly exists as a Tier 1 obligation register, and its date-based status calculation is a good design. However, it does not yet fully support the intended lifecycle of obligations: completion, recurrence roll-forward, source traceability, extraction acceptance, and Gap Analysis integration.

### Is Contract Register In Intended Behaviour?

Yes, but only at the foundation level.

It correctly exists as a Tier 1 contract parent register, and expiry calculation is useful. However, it does not yet fully support contract lifecycle management, renewal notice tracking, source-file linkage, clause extraction, Control Register linkage, Compliance Calendar linkage, or risk escalation.

### What This Means

The current implementation is not wrong. It is a solid base layer.

But the intended behaviour is broader:

- Compliance Calendar should become the operating calendar for legal/regulatory duties.
- Contract Register should become the parent source for contract obligations and contract-derived controls.
- Both should feed Gap Analysis when something is missing, late, weak, or unowned.
- Both should feed Strategic Risk only when the issue is material enough for leadership risk treatment.

The next work should focus on workflow integration, not replacing the existing foundation.
