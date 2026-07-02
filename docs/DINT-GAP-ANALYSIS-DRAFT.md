# OrgOS vs DINT Spec — Gap Analysis & Implementation Draft

**Reference spec:** Decision & Integrity Model, DRG-QI-REF-DINT-01-26 v2.0 (May 2026)
**Audit date:** 2026-07-02
**Scope:** Full backend + frontend audit against the spec, with implementation drafts for the two priority features:

1. **Global Cascade Impact Modal** — before any decision/approval that cascades, show what will change.
2. **Document Register "Revise" flow** — re-upload an updated version of an approved document and send it back through the Document Lifecycle.

Plus: all other unmet spec items, and general code-health recommendations.

---

## Part 1 — Compliance Matrix (spec §9 "Prototype Changes Required" + core sections)

Legend: ✅ Done · 🟡 Partial · ❌ Missing

| # | Spec requirement | Status | Evidence / notes |
|---|---|---|---|
| 1 | Three separate zone screens (not one queue) | ✅ | `App.jsx` routes `ExtractionReview`, `AssignmentOwnership`, `Harmonisation` as separate pages. The old tabbed `pages/AIReviewQueue/index.jsx` is **dead code** — not imported anywhere. |
| 2 | Sidebar: three Tier-2 entries | ✅ | `Sidebar.jsx:20-22`. |
| 3 | Sidebar pending-count badges per zone | ❌ | Counts exist inside each page header and WorkHub, but the sidebar shows label text only. |
| 4 | Zone-specific decision buttons | ✅/🟡 | Zone 1: Accept / Edit & accept / Reject / Mark false positive / Request 2nd review ✅. Zone 3: Merge / Partial merge / Keep separate / Rename ✅. Zone 2: all spec decisions exist but split by subtype (JD→Doc, Doc→JD, Conflict) — acceptable, arguably better than a flat list. |
| 5 | Rationale enforcement ≥10 chars | 🟡 | UI enforces ≥10 in all three zones. **Backend inconsistent**: `control_register/router.py` enforces ≥10; `review_queue/router.py` zone1/2/3 endpoints only enforce ≥5. |
| 6 | Confidence indicator: colour dot + High/Medium/Low/Very low | 🟡 | `ExtractionReview.jsx:130-143` has dot + bar + label, but the 80–89% band is labelled **"Amber"** instead of **"Medium"**. Zones 2/3 show no confidence indicator. |
| 7 | Chain preview ("If accepted, this creates: …") | 🟡 | Zone 1 only (`ChainPreview`, ExtractionReview.jsx:149-180). Missing the "→ Standards Map link" line. Nothing in Zones 2/3, Lifecycle approval, or Gap approval. |
| 8 | Cascade hints below each button | ❌ | No one-line downstream-effect hints under any decision button. |
| 9 | **Cascade impact screen/modal before confirming** | ❌ | **The priority gap.** No pre-confirm impact view anywhere. Zone 1/2 show cascade results only *after* the decision. Lifecycle `ApproveConfirmModal` says only "will create an entry in the Document Register." Backend has exactly one dry-run precedent: `GET /grc/documents/{id}/withdrawal-impact` (`grc/service.py:543`) — the pattern to generalise. |
| 10 | Conflict items: both versions side by side | 🟡 | Conflict subtype detected with its own decision set (`AssignmentOwnership.jsx:61-66, 426-436`), but rendered as a single card — no two-document side-by-side comparison. Backend stores conflicts as `ItemType="Orphan"` + `OrphanClassification="CONTROL_CONFLICT"`, not a distinct type. |
| 11 | Harmonisation variants side by side + frequency + canonical | 🟡 | Variant chips + editable canonical name exist. No per-variant frequency counts (the `VariantFrequency` badge was repurposed for classifier guidance text); not a side-by-side layout. |
| 12 | Remediation package review screen | ✅ | `GapAnalysis/index.jsx:87-210` full package viewer + "Approve package → Document Lifecycle". |
| 13 | Standards Map traffic lights | 🟡 | Rendered ✅ (`StandardsMap/index.jsx:43-56`) and RAG calc exists (`standards_map/router.py:106`). But the calc **ignores two spec rules**: missing `evidence_link` on accepted evidence should cap at Amber; missing `escalation_note` on a control should force Amber. Both fields are read but never inspected. |
| 14 | Evidence link field + hard gates | 🟡 | Field exists; **submit** hard-gates on link (422 without it). **Verify/accept does not re-check** the link is populated (spec §5.1: "cannot accept without link"). UI submit is file-upload-only — no URL input for evidence that lives in another system (spec expects a link to the artefact's location). |
| 15 | Escalation note on Control Register | ✅ | `EscalationNote` read/written (`control_register/router.py:68, 346`); shown in Standards Map clause detail. (Not yet enforced by CDI Checker at approval — spec §5.5.) |
| 16 | CDI Review screen (per-finding accept/edit/reject) | 🟡 | CDI check auto-runs on lifecycle upload and stores `CDIStatus`/`CDIFailures`; `cdiFix` API exists. No dedicated per-finding accept/edit/reject workbench with live preview as spec §9 describes. |
| 17 | Approval sphere of influence (`references` / `referenced_by`) | ❌ | **Entirely absent.** No fields in `grc/constants.py DOC_FIELDS` or schemas; no doc-to-doc graph; approval cascade never flags referencing documents (spec §5.3.1). |
| 18 | Document relationship fields in Document Register | ❌ | Same as above. |
| 19 | **Revise action on Document Register** | ❌ | **The priority gap.** Detail view has Back / Edit / Withdraw only. No "Revise", no new-version upload, no re-entry into lifecycle. |
| 20 | **"+ Revise existing" on Document Lifecycle** | ❌ | Only "+ New document" exists (`DocumentLifecycle.jsx:2369`). |
| 21 | Pre-queue validation (block untyped evidence / no source ref / no confidence) | 🟡 | `extractor/service.py:_validate_items` soft-flags (`DEFICIENT`) instead of blocking; confidence is defaulted (0.75) rather than required. Spec §3 requires a hard gate returning items to the Extractor. |
| 22 | Global state model (Pending → Active → Under review → Blocked → Escalated → Closed) | ❌ | Each register uses its own vocabulary; no unified/global state field, no "Escalated" state anywhere (escalation creates a Strategic Risk instead — reasonable, but the mapping isn't recorded). |
| 23 | Audit trail — 9+ fields incl. AI recommendation | 🟡 | `control_register/_write_audit_log` writes 11 fields (Zone, AIConfidence, StateFrom/To, CascadeResult…) ✅. But `review_queue` zone2/zone3 cascades use a **different, thinner schema** (no Zone, no confidence, no state transition). **`AIRecommendation` is never persisted or logged anywhere.** |
| 24 | Accept cascade (Control + Evidence + Audit + queue update) | ✅/🟡 | Full cascade exists (`control_register/router.py:263`). Gaps: source document's `LinkedControlsCount` is not incremented on accept (only set at lifecycle approval); evidence entry only created when an evidence type exists (correct per taxonomy, but a control can leave Pending with no evidence — spec §5.5 says it shouldn't). |
| 25 | Escalate / 2nd review / false positive | ✅ | All present as endpoints or decision values; Escalate to ExCo creates a Strategic Risk entry. |
| 26 | Gap → accept-risk → Strategic Risk | ✅ | `gap_analysis/router.py:429` full flow with rationale ≥20, risk id generation, back-links. |
| 27 | Withdrawal impact preview | ✅ | `GET /grc/documents/{id}/withdrawal-impact` — the model for Part 2 below. |

---

## Part 2 — Draft A: Global Cascade Impact Modal

### Concept

One reusable pattern, three pieces:

1. **Backend: per-action "impact" (dry-run) endpoints** that compute what a decision *would* change, without changing it. The existing `withdrawal-impact` endpoint is the template.
2. **Frontend: one shared `<CascadeImpactModal>`** component that renders any impact payload and hosts the final Confirm button (with the rationale field moved into it).
3. **Wiring:** every cascading action opens the modal → modal fetches the impact → user reads it, enters/confirms rationale → Confirm fires the real mutation.

### 2.1 Backend — impact endpoints

Standardise on one response shape so a single modal can render all of them:

```json
{
  "action": "accept-control",
  "summary": "Accepting this control creates 3 records and updates 2.",
  "creates":  [ {"register": "Control Register",  "detail": "Active control owned by ISMS Lead"},
                {"register": "Evidence Tracker",  "detail": "LOG evidence, monthly, owner: ISMS Lead"},
                {"register": "Audit Log",         "detail": "Decision record (reviewer, rationale, cascade)"} ],
  "updates":  [ {"register": "AI Review Queue",   "detail": "Item → Accepted"},
                {"register": "Standards Map",     "detail": "ISO 27001 A.8.15 recalculates (currently Red → likely Amber)"} ],
  "flags":    [ {"register": "Document Lifecycle","detail": "2 documents reference DRG-ISMS-POL-ACC-26 and will be flagged for review"} ],
  "warnings": [ "Owner role 'Network Engineer' is Unassigned — control will be created as Blocked." ],
  "blocked":  false,
  "blocked_reason": null
}
```

New endpoints (all `GET`, read-only, reuse the exact logic of their write counterparts refactored into `plan_*()` helper functions so preview and execution can never diverge):

| Endpoint | Previews |
|---|---|
| `GET /api/v1/queue/items/{id}/impact?decision=Accept` | Zone 1 accept/edit-accept: control + evidence + audit creations, queue update, Standards Map clause recalculation, owner-blocked warning |
| `GET /api/v1/queue/items/{id}/zone2-impact?decision=Create+new+document` | Zone 2: lifecycle item creation, role creation (Blocked), control reassignment, Strategic Risk creation (Escalate to ExCo) |
| `GET /api/v1/queue/items/{id}/zone3-impact?decision=Merge&canonical=...` | Zone 3: which Role Register / Control Register / Evidence Tracker entries get re-pointed, which documents get flagged for terminology update — with counts |
| `GET /api/v1/lifecycle/documents/{id}/approval-impact` | Lifecycle approval: Document Register entry create/update, re-extraction (est. item count into Zone 1), and — once §5.3.1 lands — the `referenced_by` list ("This revision will trigger review notifications for X documents") |
| `GET /api/v1/gap-analysis/{id}/remediation-impact` | Gap approve-package: lifecycle entry, pre-linked controls/evidence/roles |
| *(exists)* `GET /grc/documents/{id}/withdrawal-impact` | Keep; migrate its response to the shared shape |

Implementation notes:
- Refactor each cascade (`_zone1_accept_cascade`, `_zone2_cascade`, `_zone3_cascade`, `approve_doc`) to first build a **plan** (list of intended writes) and then execute it. The impact endpoint returns the plan; the write endpoint executes it and stores the plan summary as the audit log's `CascadeResult`. This kills the current risk of the preview text drifting from real behaviour.
- The impact response's `blocked`/`blocked_reason` lets the backend enforce hard constraints (spec §5.5) *in the modal* — e.g. "Cannot accept: evidence has no type code."

### 2.2 Frontend — shared `<CascadeImpactModal>`

New file: `frontend/src/components/shared/CascadeImpactModal.jsx`

```
Props:
  open, onClose
  title            — "Confirm: Accept control"
  impactUrl        — impact endpoint to fetch (or `impact` object passed directly)
  requireRationale — number | false   (min chars; default 10)
  confirmLabel     — "Accept & apply cascade"
  danger           — bool (red confirm for Reject/Withdraw/Approve-irreversible)
  onConfirm(rationale) — fires the real mutation; modal shows isPending state
```

Layout (single scrollable body):

```
┌──────────────────────────────────────────────────────┐
│  Accept control — cascade impact                  ✕  │
├──────────────────────────────────────────────────────┤
│  Accepting this item will:                           │
│                                                      │
│  WILL CREATE                                         │
│   ● Control Register   Active control, owner: ISMS…  │
│   ● Evidence Tracker   LOG evidence, monthly…        │
│   ● Audit Log          Decision record               │
│                                                      │
│  WILL UPDATE                                         │
│   ● AI Review Queue    Item → Accepted               │
│   ● Standards Map      A.8.15 recalculates           │
│                                                      │
│  ⚠ Owner role "Network Engineer" is Unassigned —     │
│    control will be created as Blocked.               │
│                                                      │
│  Rationale (min 10 characters) *                     │
│  ┌──────────────────────────────────────────────┐    │
│  │                                              │    │
│  └──────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────┤
│                     [ Cancel ]  [ Accept & apply ]   │
└──────────────────────────────────────────────────────┘
```

- Confirm disabled until rationale ≥ min chars (moves the existing inline rationale gate into the modal, one implementation instead of three).
- If `blocked: true`, hide Confirm and show `blocked_reason` prominently.
- Loading/error states while the impact fetch is in flight; if the impact endpoint fails, degrade to a static generic warning + confirm (never block the user on a preview failure).

While building it, also extract the shared modal shell (`ModalOverlay`/`ModalShell`) that the eight existing bespoke inline modals (Zone2ActionModal, StakeholdersModal, ApproverModal, ApproveConfirmModal, etc.) duplicate today, and migrate them onto it opportunistically.

### 2.3 Wiring — where the modal appears

| Surface | Trigger | Impact source |
|---|---|---|
| ExtractionReview (Zone 1) | Accept, Edit & accept, Reject | `/queue/items/{id}/impact` |
| AssignmentOwnership (Zone 2) | All approve/assign decisions (replace/wrap `Zone2ActionModal`'s final step) | `/queue/items/{id}/zone2-impact` |
| Harmonisation (Zone 3) | Merge, Partial merge, Rename | `/queue/items/{id}/zone3-impact` |
| DocumentLifecycle / LifecycleApprove | Approve & publish (replace `ApproveConfirmModal` body) | `/lifecycle/documents/{id}/approval-impact` |
| DocumentRegister | Withdraw (already has the data — just render it in the modal instead of/alongside current flow) | `/grc/documents/{id}/withdrawal-impact` |
| GapAnalysis | Approve package, Accept risk | `/gap-analysis/{id}/remediation-impact` |
| DocumentRegister → **Revise** (Draft B below) | Start revision | lightweight static impact ("enters Lifecycle at Review; active version stays live until approved") |

Also add the spec's cheap sibling: **one-line cascade hints** under each decision button (static strings per decision, e.g. "Creates Document Lifecycle item with AI draft") — no backend needed, ~an hour of work, big clarity win.

---

## Part 3 — Draft B: Document Register "Revise" flow (re-upload after approval)

### Concept (spec §5.3.2)

Two entry points, one flow: an **active** Document Register document re-enters the Document Lifecycle at *Review* for amendment. The active version stays live in the register until the revision is approved; on approval the register item is **updated in place** (version bump), not duplicated.

### 3.1 Backend

**New endpoint** in `lifecycle/router.py`:

```
POST /api/v1/lifecycle/documents/revise
{
  "document_register_id": "42",           // required — active register item
  "reason": "Scheduled review",           // enum: Scheduled review | NC corrective action |
                                          //       Business initiative | Gap remediation |
                                          //       Sphere of influence review | Other
  "description": "What needs changing and why",   // required, ≥10 chars
  "nc_reference": null,                   // required iff reason = NC corrective action
  "gap_reference": null,                  // required iff reason = Gap remediation
  "triggering_document": null             // required iff reason = Sphere of influence review
}
```

Behaviour:
1. Validate the register item exists and `Status == "Active"`; **409** if it already has an open (non-Approved/non-Rejected) lifecycle entry — one revision in flight per document.
2. Create the lifecycle item at Stage **Review** with:
   - `LinkedDocumentRegisterItem = document_register_id` **set at creation** (today this field is only written at approval — that's the key plumbing change),
   - `Trigger = reason`, `Notes = description`, `linked_gap_id`/`linked_nc_id` from the references,
   - `DocumentCode`, `Title`, `Department`, `DocumentType` copied from the register item,
   - `SharePointFileUrl` = the current approved file (so the reviser can download the live version),
   - assigned to the register item's owner.
3. Set the Document Register item's status to **"Under Review"** — but it remains the live record (spec: "no disruption to live operations"; the register still lists it, and the previous approved file stays downloadable).

**Change `approve_doc`** (`lifecycle/router.py:623`) to branch:

- **New document** (no pre-existing `LinkedDocumentRegisterItem` at creation): current behaviour — create register entry, `CurrentVersion = "R01"`.
- **Revision** (`LinkedDocumentRegisterItem` set at creation): **update** the existing register item instead of creating one —
  - bump `CurrentVersion` `R01 → R02 → R03…` (replaces today's hardcoded `"R01"`),
  - refresh `EffectiveDate`, `NextReviewDate`, `SharePointUrl` to the new file,
  - status back to **Active**,
  - re-run re-extraction (`_extract_approved_document_to_review_queue`) — new/changed items flow to Zone 1 exactly as spec §5.3 "Document revised and re-published" describes; refresh `LinkedControlsCount`,
  - *(future, once §5.3.1 lands)* read `referenced_by` and create "Referenced document revised" lifecycle items for each referencing document.
- On **rejection/recall** of a revision: register item's status returns to **Active** untouched — spec §5.3 "Document fails approval → no cascade; previous approved version remains."

### 3.2 Frontend

**Entry point 1 — Document Register detail view** (`DocumentRegister/index.jsx`):
- Add a **"Revise"** button (alongside Edit/Withdraw), visible only when `status === "Active"`.
- Opens a `ReviseDocumentModal` collecting the §5.3.2 form: Reason (select), Description (textarea, ≥10), and the conditional lookup field (NC ref / Gap ref / Triggering document) that appears based on reason.
- Submit → `POST /lifecycle/documents/revise` → toast with link "Opened in Document Lifecycle", and the row now shows an "Under Review · revision in progress" badge with a link to the lifecycle card. Disable Withdraw/Edit while a revision is in flight.

**Entry point 2 — Document Lifecycle page** (`DocumentLifecycle.jsx`):
- Add **"+ Revise existing"** next to "+ New document". Opens a searchable dropdown of Active documents from `documentsApi.list({status: 'Active'})`, then the same `ReviseDocumentModal`. Same endpoint, same result.

**On the lifecycle card:** show a "Revision of DRG-…-{code} (R02)" badge and a "Download current approved version" link (already supported — `SharePointFileUrl` is pre-filled). The rest of the lifecycle (upload revised file → CDI check → Sensitisation → Approval) works unchanged; the upload flow already sets `Revised=True` and runs the CDI check.

**Approval:** the `approval-impact` endpoint (Draft A) tells the approver "This will UPDATE DRG-…-… to R02, re-extract N controls into Extraction Review" instead of "will create an entry."

### 3.3 Ordering note

Draft B is independent of Draft A and can ship first; the Revise confirm step can start as a plain modal and adopt `CascadeImpactModal` when it exists.

---

## Part 4 — Other unmet spec items (recommended fixes, prioritised)

**P1 — correctness / audit-readiness**
1. **Unify the duplicate Zone 1 implementations.** `review_queue/router.py` (`PATCH /decide`, `_zone1_accept_cascade`) and `control_register/router.py` (`POST /accept-control` etc.) both implement the accept cascade with *different* rationale thresholds (5 vs 10) and *different* audit-log schemas. The live frontend calls the control_register endpoints for Zone 1 and review_queue for Zones 2/3; `zone1_decide` is reachable only from the dead AIReviewQueue page. Pick one home (suggest: keep review_queue as the router, reuse control_register's richer `_write_audit_log` for all three zones), delete the other, and enforce **≥10 chars everywhere server-side**.
2. **Standardise the audit log**: one writer, always including Zone, AIConfidence, **AIRecommendation** (currently never persisted — spec §8 requires it; start storing the extractor's proposed action on the queue item), StateFrom/StateTo, CascadeResult. This log is the ISO 27001 A.5.9 evidence — inconsistency here is an audit finding waiting to happen.
3. **Verify hard gate**: `verify_evidence` should 422 an Accept when `EvidenceLink` is empty (spec §5.1), not rely on submit having required it.
4. **Pre-queue hard gate** (spec §3): in `extractor/service.py`, block (don't just DEFICIENT-flag) items with no evidence type code, no source reference, or no confidence score; return them to the extractor with `extraction failed — requires investigation` instead of writing them to the queue. If you want reviewers to still see deficient items, keep the flag but exclude them from decision-making until repaired.

**P2 — spec-visible behaviour**
5. **`references` / `referenced_by` fields + sphere-of-influence cascade** (spec §5.3.1): add the two columns to Document Register (`DOC_FIELDS`, schemas, provisioning script); have the CDI Checker populate `references` from each document's Related Documents section; auto-maintain `referenced_by` on write; fire "Referenced document revised" lifecycle items on approval. This is a prerequisite for the full approval-impact modal payload.
6. **Standards Map RAG rules**: cap at Amber when accepted evidence lacks `EvidenceLink` ("accepted but not locatable") or a control lacks `EscalationNote` (spec §5.4).
7. **`LinkedControlsCount`** on the source Document Register item: increment on Zone 1 accept (today it's only set at lifecycle approval, so it drifts as controls are accepted later).
8. **Evidence submit**: add a URL input alongside file upload — much evidence lives in Intune/Entra/CPR, and the spec's `evidence_link` is "a link to the actual artefact location", not necessarily an uploaded copy.

**P3 — polish**
9. Sidebar pending-count badges per zone (data already fetched by each page — lift a lightweight `GET /queue/items?status=Pending Review` count query into the sidebar, or reuse WorkHub's query via React Query cache).
10. Confidence label "Amber" → "Medium"; add the confidence dot to Zone 2/3 item cards.
11. Zone 2 conflict: render the two versions side by side (both statements + source doc codes in two columns) — the data is already on the item.
12. Zone 3: real per-variant frequency counts (classifier already sees the documents; store `VariantFrequency` as JSON `{term: count}` and render it), and a side-by-side variant layout.
13. Add "→ Standards Map link" to the Zone 1 ChainPreview.
14. Global state model: pragmatic version — add a computed `global_state` in each register's serializer mapping local statuses to the six spec states (Pending/Active/Under review/Blocked/Escalated/Closed) so Work Hub and reporting can group uniformly, without migrating stored values.

---

## Part 5 — General findings (things to update / that don't work well)

Independent of the spec:

1. **Dead code shipping in the bundle**: `pages/AIReviewQueue/index.jsx` and `pages/Extractor/index.jsx` are complete pages that aren't routed in `App.jsx`. Delete them (or route Extractor if it's meant to be live) — AIReviewQueue in particular still has the weaker rationale gate and generic buttons, and will confuse anyone reading the code.
2. **API layer fragmentation**: `queueApi`, `controlApi`, `evidenceApi`, `gapApi`, `standardsApi` are defined inline per page, and `DocumentLifecycle.jsx` redefines its own `lifecycleApi` (adding `claim`) rather than extending the one in `grcApi.js`. Consolidate everything into `api/grcApi.js` — one place to see what the backend surface is, one axios instance, one error-normalisation path.
3. **Eight bespoke inline modals** duplicate the same fixed-overlay markup across pages. Extract a shared `Modal` primitive (comes free with Draft A's CascadeImpactModal work).
4. **Hardcoded `CurrentVersion = "R01"`** at approval (`lifecycle/router.py:~695`) — every document is forever R01. Fixed by Draft B's version-bump logic.
5. **Rationale thresholds are 5/10/20 across endpoints** with no single constant. Define `MIN_RATIONALE = 10` (and the deliberate 20 for risk-acceptance) in one constants module.
6. **`Zone` is not a field on queue items** — zones are inferred from ItemType/OrphanDirection, and the audit writer in control_register hardcodes a zone string. Add a real `Zone` column at extraction/classification time; filtering and the sidebar badges get simpler.
7. **CLAUDE.md is stale**: it documents the old single AIReviewQueue page, doesn't mention `ExtractionReview`, `LifecycleApprove`, `LifecycleFeedback` pages or the `jobs/` scheduler module, and describes queue endpoints (`/accept-control` under `/api/v1/queue/...`) that now live in two routers. Worth a refresh pass after the Zone-1 consolidation so it stops misleading contributors (and AI tools).
8. **No tests for anything past Tier 1** — the review-queue cascades and lifecycle approval are the highest-blast-radius code paths in the system (they write to 4+ SharePoint lists per call) and have zero coverage. When you refactor the cascades into `plan/execute` for Draft A, add tests on the plan builders — they're pure-ish and easy to test with respx.
9. **Cascade atomicity**: spec §7.5 says a failed cascade must roll back and mark the item `Blocked ("Cascade failed")`. SharePoint has no transactions, so the current cascades can partially apply (control created, evidence write fails, queue item never updated). The plan/execute refactor should at minimum: execute in dependency order, catch mid-cascade failures, write a "Cascade failed at step N" status onto the queue item, and log the partial state to the Audit Log so an admin can repair.

---

## Part 6 — Suggested build order

| Phase | Work | Why first |
|---|---|---|
| 1 | Draft B backend (`/lifecycle/documents/revise` + approval branch + version bump) | Self-contained; unblocks the user-visible Revise feature |
| 2 | Draft B frontend (Revise button + modal + "+ Revise existing") | Ships the second priority feature end-to-end |
| 3 | Zone-1 consolidation + unified audit writer + rationale constant (P1 #1-2) | Prerequisite hygiene before adding impact endpoints on top |
| 4 | Plan/execute refactor of cascades + impact endpoints (Draft A backend) | Preview logic derives from the same plan the write executes |
| 5 | `CascadeImpactModal` + shared Modal primitive + wiring on all surfaces (Draft A frontend), + static cascade hints under buttons | Ships the first priority feature |
| 6 | references/referenced_by + sphere-of-influence cascade (P2 #5), feeding the approval-impact payload | Completes spec §5.3.1 and enriches the modal |
| 7 | Remaining P2/P3 items | Polish |
