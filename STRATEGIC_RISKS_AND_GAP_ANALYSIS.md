# Strategic Risks And Gap Analysis

This document explains how Strategic Risks and Gap Analysis currently work in OrgOS, what creates them, how they relate to the rest of the governance system, and how they should behave when the implementation is tightened.

The short version is:

- Gap Analysis is an operational compliance finding register. It asks: where is the management system weak, incomplete, unowned, or unprovable?
- Strategic Risk Register is an executive risk register. It asks: what business-level exposure has ExCo chosen to monitor, treat, accept, transfer, or avoid?
- A gap can become a strategic risk, but not every gap is a strategic risk.
- A strategic risk can come from a gap, but not every strategic risk comes from Gap Analysis.

These two modules should be connected, but they should not collapse into one another.

---

## 1. The Conceptual Difference

### Gap Analysis

Gap Analysis is about compliance coverage.

It compares what the organisation is supposed to have against what the confirmed registers currently show. It is evidence-oriented and control-oriented.

Examples:

- ISO 27001 A.5.18 requires access rights management, but no accepted control exists.
- A control exists for incident response, but no evidence requirement exists.
- A control exists, but the owner role is unassigned.
- Evidence is expected, but no one can prove the control is operating.

The question Gap Analysis answers is:

> What is missing, weak, or unprovable in the compliance system?

### Strategic Risk Register

Strategic Risk Register is about executive risk ownership.

It is not just a list of control defects. It is an ExCo-curated business risk register using human judgement. It should contain risks that matter at the business, regulatory, market, operational, reputational, or strategic level.

Examples:

- Failure to meet regulatory breach notification obligations could create legal penalties and reputation loss.
- Lack of mature AI governance could expose the business to client trust, model misuse, and regulatory risk.
- A major unresolved ISO 27001 gap could put certification at risk.
- A known weakness is accepted temporarily because the cost or timing of mitigation is not currently feasible.

The question Strategic Risk Register answers is:

> What business risk has leadership decided to track, treat, accept, or escalate?

---

## 2. Current Code Locations

### Backend

- `gap_analysis/router.py`
  - Main API for listing, creating, updating, closing, and accepting gap findings as risks.

- `agents/gap_analyzer/service.py`
  - The Gap Analyzer agent.
  - Reads Control Register, Evidence Tracker, and Role Register.
  - Detects missing controls, evidence gaps, and ownership gaps.
  - Uses Ollama to propose remediation packages.

- `agents/gap_analyzer/router.py`
  - API wrapper for triggering the Gap Analyzer.
  - Endpoint: `POST /api/v1/agents/gap-analysis/run`.

- `strategic_risks/router.py`
  - Main API for Strategic Risk Register.
  - Supports manual creation, listing, and updates.

- `review_queue/router.py`
  - Zone 2 ExCo escalation can create a Strategic Risk Register item.

### Frontend

- `frontend/src/pages/GapAnalysis/index.jsx`
  - Shows gap findings.
  - Allows compliance users to run the Gap Analyzer.
  - Allows marking gaps in progress or closed.
  - Allows accepting a gap as risk, which creates a Strategic Risk Register item.

- `frontend/src/pages/StrategicRisks/index.jsx`
  - Shows strategic risks.
  - Allows creating risks manually.
  - Allows changing status to Under treatment, Accepted, or Closed.

---

## 3. What Creates Gap Analysis Items Today

There are two intended sources in the wider design:

1. Gap Analyzer agent
2. Manual or audit-sourced findings

In the current implementation, the real active source is mainly the Gap Analyzer agent.

### 3.1 Gap Analyzer Agent

The frontend button calls:

```text
POST /api/v1/agents/gap-analysis/run
```

That endpoint calls:

```text
agents/gap_analyzer/service.py -> run_gap_analysis()
```

The agent reads:

- Control Register
- Evidence Tracker
- Role Register

Then it compares the current register data against a fixed internal list of required clauses.

The required clauses are currently hard-coded in `agents/gap_analyzer/service.py` as `REQUIRED_CLAUSES`.

Current standards covered:

- ISO 27001
- ISO 9001
- NDPA

Current clause examples:

- ISO 27001 A.5.1
- ISO 27001 A.5.15
- ISO 27001 A.5.18
- ISO 27001 A.8.24
- ISO 9001 7.5
- ISO 9001 9.2
- NDPA S.39
- NDPA S.40

### 3.2 What The Gap Analyzer Detects Today

The current detection logic finds three main gap types:

#### Missing Artefact

Created when a clause requires controls, but no Control Register item maps to that clause.

Current logic:

```text
No controls for required clause -> Missing artefact
```

Example:

```text
No controls found for ISO 27001 A.5.15 Access control.
```

#### Ownership Gap

Created when controls exist, but the control is blocked or has no owner OID.

Current logic:

```text
Control Status = Blocked OR OwnerEntraId is empty -> Ownership gap
```

Example:

```text
Control exists for ISO 27001 A.5.18, but role "Employee" is unassigned.
```

This is why the recent role harmonisation fix matters. If Control Register and Evidence Tracker owner fields are stale, Gap Analyzer can create false ownership gaps.

#### Evidence Gap

Created when a clause requires evidence, controls exist, but no Evidence Tracker item is linked to the control.

Current logic:

```text
Clause requires evidence AND control has no linked evidence item -> Evidence gap
```

Example:

```text
Control exists for ISO 27001 A.8.24, but no evidence requirement exists.
```

### 3.3 What The Gap Analyzer Does Not Properly Detect Yet

The comments describe six gap types:

- Missing artefact
- Control gap
- Evidence gap
- Ownership gap
- Standards misalignment
- Obligation gap

But the current active logic mainly detects:

- Missing artefact
- Evidence gap
- Ownership gap

These are not fully implemented yet:

- Control gap
  - The system does not yet assess whether a control statement is strong enough, precise enough, or materially adequate.

- Standards misalignment
  - The system does not yet detect controls mapped to the wrong standard clause.

- Obligation gap
  - The system does not yet compare regulatory obligations against Compliance Calendar items.

- Weak evidence quality
  - The system checks whether evidence exists, but not whether evidence is accepted, overdue, rejected, or sufficient.

- Duplicate gap suppression
  - Re-running the Gap Analyzer can create duplicate gap items because there is no robust uniqueness key.

---

## 4. Gap Analysis Fields Today

The Gap Analysis API returns these fields:

- `id`
- `GapId`
- `Standard`
- `Clause`
- `ClauseTitle`
- `GapCategory`
- `Severity`
- `Finding`
- `Impact`
- `RemediationHint`
- `ProposedRemediation`
- `Status`
- `AssignedTo`
- `AssignedToEntraId`
- `TargetDate`
- `VerificationMethod`
- `ResolutionNotes`
- `LinkedRiskId`
- `created`
- `modified`

### Statuses

Current valid gap statuses:

- `Open`
- `In progress`
- `Accepted risk`
- `Closed`

### Severity

Current severity values:

- `Critical`
- `Major`
- `Minor`

Current sorting order:

```text
Critical -> Major -> Minor
```

### GapId

The manual `POST /api/v1/gap-analysis` endpoint creates a GapId like:

```text
GAP-2026-0609
```

This is not ideal because multiple gaps created on the same day can receive the same GapId.

The older design notes describe a better format:

```text
GAP-{standard}-{YY}-{NNN}
```

Example:

```text
GAP-ISO27001-26-001
```

That intended format is better because it is unique, readable, standard-aware, and audit-friendly.

### Target Date

There is a mismatch in the current code:

- `gap_analysis/router.py` uses:
  - Critical: 56 days
  - Major: 28 days
  - Minor: 90 days

- `agents/gap_analyzer/service.py` uses:
  - Critical: 56 days
  - Major: 28 days

- Older docs mention:
  - Critical: 30 days
  - Major: 60 days
  - Minor: 90 days

The current implementation is therefore internally consistent between the router and agent for Critical/Major, but the policy intent is unclear. This should be decided and standardised.

---

## 5. Proposed Remediation Package

When the Gap Analyzer finds a gap, it calls Ollama to produce a remediation package.

The package is stored as JSON text in:

```text
ProposedRemediation
```

The expected JSON shape is:

```json
{
  "document": "Description of what document action is needed",
  "controls": ["Control statement 1", "Control statement 2"],
  "evidence": ["Evidence type code - description. Source: system. Frequency: period"],
  "roles": ["Role title"],
  "risk": "Risk if this gap remains open",
  "standards_mapping": "ISO 27001 A.5.18",
  "target_date": "YYYY-MM-DD",
  "verification": "How closure will be confirmed"
}
```

If Ollama fails or returns invalid JSON, the system creates a fallback package.

### What Works

- The remediation package is visible in the Gap Analysis page.
- A compliance user can view it.
- A compliance user can approve the package.

### Important Current Gap

The frontend button says:

```text
Approve package -> enter Document Lifecycle
```

But the current frontend action only calls:

```text
PATCH /api/v1/gap-analysis/{id}/status
```

and changes the gap to:

```text
In progress
```

It does not actually create a Document Lifecycle item.

So the UI promise is stronger than the backend behavior.

Correct intended behavior should be:

1. Reviewer opens the remediation package.
2. Reviewer approves, edits, or rejects the package.
3. If approved for remediation:
   - Gap status becomes `In progress`.
   - One or more Document Lifecycle entries are created if document work is needed.
   - Proposed controls can be staged into AI Review Queue or Control Register workflow.
   - Proposed evidence requirements can be staged into Evidence Tracker only after control approval.
   - Gap stores links to created lifecycle/remediation work.

---

## 6. What Creates Strategic Risk Items Today

Strategic Risk Register has three intended entry paths:

1. Manual ExCo assessment
2. Gap acceptance
3. Incident escalation

In current code, the active sources are:

1. Manual risk creation from the Strategic Risks page.
2. Gap acceptance from the Gap Analysis page.
3. Zone 2 ExCo escalation from Assignment & Ownership.

Incident escalation is referenced in comments and schema fields, but there is no full incident module flow visible in the inspected code.

### 6.1 Manual ExCo Assessment

Frontend:

```text
Strategic Risks -> + Add risk
```

Backend:

```text
POST /api/v1/risks
```

Creates a Strategic Risk Register item with:

- Description
- Category
- Source
- Likelihood
- Impact
- RiskScore
- OwnerEntraId
- Treatment
- TreatmentActions
- Status = `Open`
- DateIdentified = today
- ReviewDate = today + 90 days

### 6.2 Gap Acceptance

Frontend:

```text
Gap Analysis -> Accept risk
```

Backend:

```text
POST /api/v1/gap-analysis/{id}/accept-risk
```

This creates a Strategic Risk Register item and updates the gap.

The created risk has:

- Title: `Accepted risk: <gap finding>`
- Description: gap finding
- Category: `SWOT - Threat`
- Source: `Gap acceptance`
- Likelihood: `Medium`
- Impact:
  - `High` if the gap severity is Critical
  - `Medium` otherwise
- Treatment: `Accept`
- Status: `Accepted`
- RelatedGapId: the gap's `GapId` or item id
- Notes: ExCo rationale

Then the gap is updated:

- Status: `Accepted risk`
- LinkedRiskId: created risk item id
- ResolutionNotes: rationale and reviewer name

### 6.3 Zone 2 ExCo Escalation

Assignment & Ownership Zone 2 has a decision:

```text
Escalate to ExCo
```

That can create a Strategic Risk Register item from an ownership/document conflict.

Current risk fields include:

- Category: `SWOT - Threat`
- Source: `Zone 2 Assignment escalation`
- Likelihood: `Medium`
- Impact: `High`
- RiskScore: `6`
- Treatment: `Mitigate`
- Status: `Open`
- DateIdentified: today
- ReviewDate: today + 90 days
- EscalationNote: reviewer rationale

This is a good direction because some ownership conflicts are not ordinary remediation tasks. They can become executive accountability risks.

---

## 7. Strategic Risk Fields Today

The Strategic Risk API returns these fields:

- `id`
- `RiskId`
- `Title`
- `Description`
- `Category`
- `Source`
- `Likelihood`
- `Impact`
- `RiskScore`
- `RiskScoreLabel`
- `RiskScoreColor`
- `OwnerEntraId`
- `OwnerName`
- `Treatment`
- `TreatmentActions`
- `Status`
- `DateIdentified`
- `ReviewDate`
- `LastReviewed`
- `RelatedGapId`
- `RelatedIncidentId`
- `EscalationNote`
- `Notes`
- `created`
- `modified`

### Risk Score

The code calculates:

```text
RiskScore = Likelihood x Impact
```

Likelihood:

- Low = 1
- Medium = 2
- High = 3

Impact:

- Low = 1
- Medium = 2
- High = 3
- Critical = 4

Possible scores:

```text
1 to 12
```

### Current Score Labels

Current backend labels:

- 1 to 2: Low
- 3 to 4: Medium
- 5 to 6: High
- 7 to 12: Critical

Older docs describe:

- 1 to 3: Low
- 4 to 6: Medium
- 7 to 9: High
- 10 to 12: Critical

This is another mismatch that should be resolved. The current frontend displays whatever label/color the backend returns, but dashboard counts treat score >= 8 as critical, which does not exactly match the backend label logic.

### Strategic Risk Statuses

The frontend uses:

- `Open`
- `Under treatment`
- `Accepted`
- `Closed`

The backend accepts any status string in `PATCH /api/v1/risks/{id}` without validation.

This should be tightened. Strategic risk statuses should be an enum.

Recommended statuses:

- `Open`
- `Under treatment`
- `Accepted`
- `Transferred`
- `Avoided`
- `Closed`

Optional status:

- `Review overdue`

But `Review overdue` should probably be calculated, not stored.

---

## 8. Current Frontend Behavior

### Gap Analysis Page

The page shows:

- Severity badge
- Standard and clause
- Gap status
- Finding
- Impact
- Target date
- Proposed remediation package
- Linked risk if accepted

Filters:

- Open
- Closed / Accepted
- All
- Severity
- Standard
- Search

Actions for Compliance Lead:

- Run gap analysis
- View remediation package
- Mark in progress
- Accept risk
- Close gap when in progress

### Strategic Risks Page

The page shows:

- Risk score
- Category
- Status
- Description
- Treatment
- Owner
- Review date
- Treatment actions
- Escalation note
- Related gap
- Notes

Filters:

- All
- Open
- Under treatment
- Accepted
- Closed
- Search

Actions:

- Add risk
- Mark under treatment
- Accept risk
- Close treatment complete

---

## 9. How The End-To-End Flow Should Work

### Flow A: Control And Evidence Create The Source Of Truth

1. Extraction Review accepts controls.
2. Control Register entries are created.
3. Evidence Tracker entries are created when evidence is defined.
4. Role Register determines whether controls and evidence are assigned.
5. Standards Map calculates clause coverage from controls and evidence.

Gap Analysis should not work from raw extraction items. It should work from confirmed registers.

That part is currently correct.

### Flow B: Gap Analyzer Creates Findings

1. Compliance Lead runs Gap Analyzer.
2. Agent reads:
   - Control Register
   - Evidence Tracker
   - Role Register
   - required standard clauses
3. Agent detects:
   - missing controls
   - blocked ownership
   - missing evidence
   - eventually weak controls, wrong mappings, obligation gaps
4. Agent writes Gap Analysis items.
5. Each gap has:
   - severity
   - finding
   - impact
   - target date
   - proposed remediation package
   - verification method

### Flow C: Compliance Decides Remediate Or Accept Risk

For each gap, Compliance Lead should decide:

1. Remediate
2. Accept as risk
3. Close because already fixed
4. Reassign owner
5. Mark false positive or suppress duplicate

Current implementation supports:

- In progress
- Closed
- Accepted risk

It does not yet support:

- false positive
- duplicate/suppressed
- reassignment workflow
- document lifecycle creation from package approval

### Flow D: Remediation Should Create Work

When a remediation package is approved, the system should create real work items.

Depending on package content:

- Document action should create Document Lifecycle entry.
- Control action should stage a queue item or create a control review task.
- Evidence action should create evidence requirements only after control approval.
- Role action should create or update Role Register task.
- Standards mapping should link the remediation back to affected clause.

The current code only changes gap status to `In progress`.

### Flow E: Accepted Risk Should Create A Strategic Risk

When leadership accepts a gap as risk:

1. Gap status becomes `Accepted risk`.
2. Strategic Risk Register item is created.
3. The risk links back to the gap.
4. The gap links forward to the risk.
5. Standards Map should still show the clause as not fully compliant, but with accepted risk context.

Current implementation does steps 1 to 4.

The Standards Map accepted-risk annotation is described in frontend text but not confirmed in inspected Standards Map behavior.

### Flow F: Strategic Risk Is Managed Over Time

Strategic Risk Register should then operate on its own lifecycle:

1. Open
2. Under treatment, Accepted, Transferred, or Avoided
3. Periodic review
4. Closed when risk no longer applies or treatment is complete

Risks should not automatically close just because a gap closes. A linked gap can reduce or resolve a risk, but ExCo should still review and close the risk explicitly.

---

## 10. Current Gaps And Issues

### 10.1 Duplicate Gap Creation

The Gap Analyzer writes new findings every run.

There is no robust deduplication key such as:

```text
Standard + Clause + GapCategory + ControlId
```

This means repeated runs can create duplicate open gaps for the same underlying issue.

Recommended behavior:

- If an equivalent open gap already exists, update it instead of creating a duplicate.
- If an equivalent closed gap exists and the issue reappears, create a recurrence or reopen with history.
- Add a stable `GapKey` field if SharePoint supports it.

### 10.2 GapId Is Not Unique Enough

Manual gap creation currently uses date-based GapId:

```text
GAP-YYYY-MMDD
```

Multiple gaps on the same day can collide.

Recommended behavior:

```text
GAP-{STANDARD}-{YY}-{NNN}
```

Examples:

```text
GAP-ISO27001-26-001
GAP-NDPA-26-003
```

### 10.3 Remediation Approval Does Not Create Lifecycle Work

The UI says approval enters Document Lifecycle, but backend only marks the gap `In progress`.

Recommended behavior:

- Add endpoint:

```text
POST /api/v1/gap-analysis/{id}/approve-remediation
```

It should:

- parse `ProposedRemediation`
- create Document Lifecycle item if document work is needed
- store linked lifecycle id on the gap
- mark status `In progress`
- record resolution notes

### 10.4 Gap Analyzer Does Not Use Evidence Quality Enough

Current evidence gap detection checks whether evidence exists, but not whether it is:

- Submitted
- Accepted
- Rejected
- Overdue
- stale
- owned by assigned person

Recommended behavior:

- No evidence item: Evidence gap, Major
- Evidence pending but not yet due: Minor or Open action
- Evidence overdue: Major
- Evidence rejected: Major
- Evidence submitted but unverified: Minor or Amber
- Evidence accepted: no evidence gap

### 10.5 Gap Analyzer Does Not Detect Weak Controls

Current control coverage is mostly clause mapping based.

Recommended behavior:

- Deterministic first:
  - control exists
  - active owner
  - mapped standard clause
  - evidence expected where required
- Semantic assist second:
  - AI can suggest whether the control statement materially covers the clause.
  - AI should not directly create accepted findings without deterministic anchor.

### 10.6 Strategic Risk Score Bands Are Inconsistent

Backend label bands do not match older docs or frontend critical counts.

Recommended behavior:

Pick one matrix and use it everywhere.

Suggested bands:

| Score | Label |
|---:|---|
| 1-3 | Low |
| 4-6 | Medium |
| 7-9 | High |
| 10-12 | Critical |

Then update:

- backend `_score_label`
- backend `_score_color`
- frontend summary counts

### 10.7 Strategic Risk Status Is Not Validated

Backend accepts any risk status string.

Recommended behavior:

Use a fixed enum:

- `Open`
- `Under treatment`
- `Accepted`
- `Transferred`
- `Avoided`
- `Closed`

### 10.8 Accepted Risk Needs Stronger Governance

Accepting a gap as risk currently requires a rationale and Compliance Lead/Admin role.

But conceptually, accepted risk should be an ExCo decision.

Recommended behavior:

- Require explicit ExCo approver field or role.
- Store accepted-by user.
- Store accepted date.
- Store next review date.
- Require review cycle.
- Require rationale minimum length.

### 10.9 Standards Map Accepted-Risk Annotation Needs Confirmation

Gap Analysis frontend says accepted risk remains visible to auditors on Standards Map.

That behavior should be verified or implemented.

Recommended behavior:

- If a clause has an accepted risk linked to an open compliance gap:
  - Standards Map should not turn Green.
  - It should show Red or Amber with `Accepted risk`.
  - It should link to the Strategic Risk Register item.

### 10.10 Strategic Risks Need Better Links Back To Source

Strategic risks can link to `RelatedGapId` and `RelatedIncidentId`.

For full traceability, risks should also support:

- source queue item id
- source control id
- source document code
- source standard clause
- source evidence id
- ExCo decision record

---

## 11. Recommended Intended Behavior

### Gap Analysis Should Be A Work Intake Register

Gap Analysis should not merely report problems. It should turn compliance weaknesses into structured work.

Each gap should have:

- unique gap id
- stable deduplication key
- source clause
- source control/evidence/role where applicable
- severity
- impact
- owner
- target date
- proposed remediation package
- decision path
- linked work item
- closure verification

### Strategic Risk Should Be An Executive Risk Register

Strategic Risk Register should not become a dumping ground for every control problem.

It should only receive:

- accepted risks
- executive escalations
- strategic market/regulatory/operational risks
- high-impact unresolved compliance gaps

Each strategic risk should have:

- unique risk id
- source
- category
- likelihood
- impact
- score
- treatment
- accountable owner
- treatment actions
- review date
- accepted/closed governance trail
- links to gap, incident, document, or queue source

### AI Should Help But Not Decide

Gap Analysis can use AI for remediation packages and semantic adequacy review.

But final decisions should remain human:

- AI can propose a package.
- AI can suggest likely control weakness.
- AI can explain why evidence appears inadequate.
- AI can help classify severity.

Human reviewers should:

- approve remediation
- accept risk
- close a gap
- decide strategic risk treatment

---

## 12. Recommended Implementation Priorities

### Priority 1: Make Gap Runs Idempotent

Add duplicate detection before writing Gap Analysis records.

Recommended key:

```text
Standard | Clause | GapCategory | ControlId or SourceDocument
```

### Priority 2: Fix Remediation Approval Cascade

Create a real backend endpoint for approving a remediation package.

It should create Document Lifecycle work and link it back to the gap.

### Priority 3: Standardise Score Bands And Status Enums

Make Strategic Risk scoring consistent across backend, frontend, and docs.

Validate statuses server-side.

### Priority 4: Improve Evidence-Based Gap Logic

Gap Analyzer should distinguish:

- no evidence defined
- evidence pending
- evidence submitted
- evidence accepted
- evidence rejected
- evidence overdue

### Priority 5: Improve Accepted Risk Governance

Accepted risk should capture:

- rationale
- accepting person
- accepted date
- review date
- linked risk id
- standards map annotation

### Priority 6: Add Strategic Risk Source Traceability

Strategic risks created from Zone 2 or Gap Analysis should keep rich source links, not just text notes.

---

## 13. Clean Target Flow

The clean target flow should look like this:

```text
Confirmed controls + evidence + roles
        |
        v
Gap Analyzer
        |
        v
Gap Analysis finding
        |
        +--> Remediate
        |       |
        |       v
        |   Document Lifecycle / control review / evidence requirement
        |       |
        |       v
        |   Gap closed after verification
        |
        +--> Accept as risk
                |
                v
            Strategic Risk Register
                |
                v
            ExCo review cycle
```

This preserves the right separation:

- Gap Analysis manages compliance remediation.
- Strategic Risk manages executive risk decisions.
- Document Lifecycle manages document changes.
- Control Register remains the source of confirmed controls.
- Evidence Tracker remains the proof workflow.
- Standards Map remains the live compliance health view.

---

## 14. Summary

The current implementation has the right broad structure:

- Gap Analyzer reads confirmed registers.
- Gap Analysis stores findings and remediation packages.
- Gap acceptance creates Strategic Risk Register entries.
- Strategic Risk Register is kept manual-first and ExCo-oriented.

The main improvements needed are not architectural rewrites. They are mostly workflow-hardening:

- deduplicate gap generation
- make GapId unique
- make remediation approval actually create work
- improve evidence quality logic
- standardise risk scoring/statuses
- strengthen accepted-risk governance
- ensure Standards Map reflects accepted risk correctly

Once those are done, Gap Analysis and Strategic Risks will become a strong governance loop rather than two adjacent registers.
