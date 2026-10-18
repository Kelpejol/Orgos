# GRC Control Framework — Architecture Plan

**Audience:** Paul and Adekunle, as the build plan; the open decisions in §13 go to Bobby and Compliance.
**Companion to:** [GRC-EXTRACTION-AND-RECORDS-EXPLAINER.md](GRC-EXTRACTION-AND-RECORDS-EXPLAINER.md), which explains *why*. This document is *what we build, in what order, and what it touches*.
**Basis:** Bobby's brief; the CDI Standard (DRG-QI-STD-CDI) and Procedure (DRG-QI-PRO-CDI); the BCDR Procedure (DRG-ISMS-PRO-BCI); the Enterprise Records Catalogue; the records-governance review package; and a read of every OrgOS module the change reaches. Every claim about current code below was checked against the code.

---

## 0. First — the 120 job titles

You're right, and I overstated it. The prompt vocabulary is **your OrgOS group names plus every distinct job title held by an enabled Entra user** (`agents/extractor/service.py:775-788`). With ~38 titles, all 38 go in, plus the groups. The `job_titles[:120]` in `ollama_client.py:207` is a ceiling you never reach. I've corrected the explainer.

The real problem was never the count. It's three things about *what* we send:

1. **A job title is a bare string** — no duty description, so there's nothing for a model to match a control's wording against.
2. **The CDI framework's roles mostly aren't job titles.** "Accountable Department Head", "Document Owner", "Control Owner" will never appear in a directory, however many titles we send.
3. **The prompt mixes extraction with resolution.** It asks the model to *pick* a title, and to fall back to the document's wording if none fits — so one field silently holds either a resolved role or a raw quote, and nothing downstream can tell which.

The plan below fixes all three.

---

## 1. The whole system on one page

```
  GRC Control Library (one folder per domain)
            │
            ▼
  ┌──────────────────────┐   WIP / superseded excluded
  │ 1. SCOPE & IDENTIFY  │   doc code → layer (STD/PRO/POL/…)
  │                      │   read the document's own control block
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐   DEFINING   — Standard (or defining Procedure)
  │ 2. DOCUMENT ROLE     │   IMPLEMENTING — Procedure / Specification
  │                      │   AUTHORITY  — Policy        SUPPORTING — rest
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐   control blocks → control definitions
  │ 3. PARSE (no AI)     │   sections citing IDs → implementation steps
  │                      │   Roles table, Annex A/B/C → roles, records, open params
  └──────────┬───────────┘   …LLM fallback only where no structure exists
             ▼
  ┌──────────────────────┐   REC-nnnn  → Records Catalogue
  │ 4. RESOLVE           │   roles     → Role Catalogue
  │  (as-written kept)   │   mappings  → Clause Catalogue
  └──────────┬───────────┘   parents   → Document Register
             ▼
  ┌──────────────────────┐   new / changed / unchanged — per Control ID
  │ 5. DIFF              │   unchanged never reaches a reviewer
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐   Zone 1  control definitions (field-level diffs)
  │ 6. HUMAN REVIEW      │   Zone 2  roles & records that don't resolve
  │                      │   Zone 3  conflicts & harmonisation
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐   upsert by Control ID (never a duplicate row)
  │ 7. ACCEPT CASCADE    │   implementations + control↔record links
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐   per control↔record link, on its own schedule
  │ 8. EVIDENCE          │   referenced at source, not copied
  │    OBLIGATIONS       │   missing / late / stale → the control's failure route
  └──────────┬───────────┘
             ▼
     Control View · Standards Map · Gap Analysis · Harmonisation fixes → source docs
```

---

## 2. Principles

These are the rules every part of the build is held to. Each traces to Bobby's brief, a CDI control, or something we verified.

| # | Principle | Source |
|---|---|---|
| P1 | **Parse before infer.** Where a document states a field on a labelled line, read it. The model is a fallback, and anything it produces is marked *inferred*. | 45/45 CDI controls carry all 8 fields |
| P2 | **One definition per Control ID.** Defined in the Standard (or defining Procedure); Procedures implement it under the same ID and never create a new control. | Bobby §1 |
| P3 | **Reference, don't recreate.** The Records Catalogue, specialist registers and source systems stay authoritative; OrgOS links to them by ID. | Bobby §3–4; Catalogue GR-04, GR-09 |
| P4 | **As-written and as-resolved are separate fields.** What the document says is evidence; what it maps to is a decision. Never overwrite one with the other. | The failure in §0 |
| P5 | **Every field carries provenance and status.** Source document, version, section, method (parsed / inferred / human), validation status. | Bobby §4 bullet 2, §5 |
| P6 | **Missing stays visible; unrecognised is flagged.** No field is filled by guessing. | Bobby §5 |
| P7 | **A human confirms before anything enters an operational register.** The Review Queue remains the gate. | Bobby §4 bullet 5 |
| P8 | **Fix at the source.** A discrepancy is routed to the document that causes it, through the Document Lifecycle — OrgOS does not quietly edit control definitions. | Zone 3 already works this way |
| P9 | **Gate destructive automation on validation.** No disposition on a record whose retention is unvalidated. | Catalogue GR-11; Bobby §5 |

---

## 3. What the documents give us — and what they don't

This sets how much can be parsed versus inferred, so it's worth being precise.

### Shapes seen so far

| Document | Shape | Parseable? |
|---|---|---|
| **CDI Standard** (DRG-QI-STD-CDI) | Each control a labelled block: `Requirement`, `Trigger`, `Accountable / Executing`, `Evidence`, `Risk`, `Failure route`, `Exception route`, `Mapping` | **Yes** — 45 of 45 controls, all 8 fields |
| **BCDR Procedure** (DRG-ISMS-PRO-BCI) | Control block with `Standard controls implemented: BCDR-01; …`; section headings `4.0 Business impact assessment (BCDR-01)`; Roles table; Annex A control map; Annex B records; Annex C open parameters | **Yes** |
| **CDI Procedure** (DRG-QI-PRO-CDI) | Control block; section headings `5.0 Hierarchy and Parentage (implements CDI-001, CDI-019)` | **Yes** — different citation syntax |
| **IRG Standard, review draft** (DRG-QI-STD-IRG-01-26) | Prose. **No control IDs, no labelled fields.** | **No** — fallback only |

So the current CDI v06 house style is highly parseable, and older or draft documents are not. **We do not yet know the proportion across the whole library** — that's the first thing Phase 1 measures (§12).

### Fields Bobby asks for that no document states per control

Bobby lists *monitoring method*, *evidence freshness* and *authority* among the CDI extras. In the CDI Standard:

- **Monitoring method** and **evidence freshness** are defined terms, but **no control block states them** — they're not among the 8 labels.
- **Authority** is stated once per *document* (`Approval Authority` in the control block), not per control.
- **Evidence check frequency** — the "when do we confirm proof" half of Bobby's field 7 — is not stated either. The `Trigger:` line is when the control *operates*.

Bobby also notes the mandatory GRC Ingestion Appendix, which would presumably carry these, **has not been introduced**. So per P6 these fields exist in the model, display as **"not stated"**, and are set by a person at confirmation. They are never derived.

---

## 4. Target data model

Storage stays SharePoint Lists via Graph. No new infrastructure. Joins happen in Python, as today.

### Entities

| Entity | List | New / evolved | Key | Authority |
|---|---|---|---|---|
| Control definition | **Control Register** | **Evolved** — additive columns | `ControlId` | Defining document, confirmed by a reviewer |
| Implementation step | **Control Implementations** | New | `ControlId` + `DocCode` + `Section` | Implementing document |
| Control ↔ record | **Control Record Links** | New (many-to-many) | `ControlId` + `RecordId` | Defining doc, confirmed |
| Record | **Records Catalogue** | New | `RecordId` (REC-nnnn) | The Catalogue — see decision D1 |
| Evidence obligation | **Evidence Tracker** (Record Tracker) | **Evolved** | item id | OrgOS, generated |
| Role | **OrgOS Groups** → *Role Catalogue* | **Evolved** | name | Organogram, confirmed |
| Role assignment | **Role Assignments** | New | role + scope + person | Verified by Compliance / HR |
| Standards clause | `reference/clauses.yaml` | New, in the repo | standard + clause | Published standards |
| Finding | **AI Review Queue** | Evolved — new item types | item id | Generated |

### Why evolve rather than replace

**Control Register and Evidence Tracker are evolved in place, with new columns only.** Existing rows keep their item ids, so the Evidence Tracker's `LinkedControlId` links, the Audit Log and every Standards Map history stay intact. A parallel new list would mean migrating every link, for no gain. This also matches how `scripts/provision_sharepoint_columns.py` already works.

**The Role Catalogue evolves OrgOS Groups rather than reinstating the Role Register.** `README.md:984` is explicit that the Role Register must not come back. Groups already have what a role needs — description, verified members by Entra OID, aliases — and `OwnershipIndex` already resolves them everywhere ownership is checked. We add the missing fields; we don't build a second ownership system.

### New and changed columns

**Control Register — added:**
`ControlId` (indexed, unique) · `ControlTitle` · `Requirement` · `ControlTrigger` · `AccountableRoleAsWritten` · `AccountableRole` · `ExecutingRoleAsWritten` · `ExecutingRole` · `FailureRoute` · `ExceptionRoute` · `MappingAsWritten` · `MappingJson` (structured `[{standard, clause}]`) · `DefiningDocCode` · `DefiningDocVersion` · `DefiningSection` · `MonitoringMethod` · `EvidenceFreshness` · `ProvenanceJson` (per-field source, method, status) · `DefinitionStatus` (Active / Blocked / Superseded / Withdrawn / **Legacy**) · `BlockedReason`

Existing `OwnerRole`, `ISOClause`, `ControlStatement` and `RiskImplication` are kept and written in parallel during migration, so nothing that reads them breaks.

**Evidence Tracker — added:**
`ControlId` · `RecordId` · `Scope` (e.g. a process, service, department) · `EvidenceCheckFrequency` · `FreshnessDays` · `EvidenceReference` (link to the authoritative location) · `ResponsiblePersonOid` · `ResolutionPath`

**OrgOS Groups → Role Catalogue — added:**
`Kind` (Positional / Functional / Team / System) · `RoleStatus` (Recognised / Proposed / Unrecognised) · `Department` · `ReportsTo` · `ResolutionRule` (for Functional) · `RoleSource` (Organogram / CDI document / Manual) · `SourceRef` · `ActingHolderOid` · `ActingUntil`

**Role Assignments — new:**
`Role` · `ScopeType` (Global / Department / Process / Service / Document / Contract) · `ScopeValue` · `PersonOid` · `Basis` · `VerifiedBy` · `VerifiedOn` · `ValidFrom` · `ValidTo`

**Control Record Links — new:**
`ControlId` · `RecordId` · `RecordIdAsWritten` · `LinkPurpose` (Operation / Approval / Review / Exception) · `EvidenceCheckFrequency` · `FreshnessDays` · `StatedIn` (doc + section) · `LinkStatus` (Stated / Confirmed / Inferred)

**Records Catalogue — new:** the Catalogue's 29 columns, plus `ImportBatch` and `ImportedOn`. Every validation-status column is carried verbatim.

### Two deliberate modelling choices

**Roles have four kinds, not three.** The explainer named three. The CDI Standard shows a fourth in its `Executing` half: *"Compliance Executive (QMS & NDPA) / **platform check V03**"*. A platform check executes a control and is not a person. Kind `System` lets us record that honestly instead of forcing it into a person-shaped field.

**Functional roles resolve through scoped assignments, not membership.** "Accountable Department Head" has no members. It resolves *for a scope*: `(Accountable Department Head, Process: Payroll) → Finance Manager → [person]`. That's what the `Role Assignments` list is for. Positional roles use `ScopeType = Global`.

---

## 5. The extraction pipeline

Each stage is a pure function with its own tests, using the real documents as fixtures. That's how we keep this correct over time.

### Stage 1 — Scope and identify
- Walk the configured domain folders.
- **Exclude WIP and superseded copies.** Today `scripts/intake_sharepoint_to_lifecycle.py` walks every subfolder with no exclusion. We need to know how they're marked — decision D3.
- Read the document code → layer via `lifecycle/domains.py`, which already knows the CDI type codes.
- Parse the document's **own control block**: title, code, layer, domain, parent, child documents, related documents, owner, approval authority, classification, issue status, supersedes, standards, *Standard controls implemented*.

### Stage 2 — Decide the document's role
| Role | Test | What we take from it |
|---|---|---|
| **Defining** | Contains labelled control blocks | Control definitions |
| **Implementing** | Cites control IDs (control block field, section headings, or Annex A) without defining them | Implementation steps, roles, record links, open parameters |
| **Authority** | Layer 1–2 Policy | Authority and intent — **no controls** (Bobby §1) |
| **Supporting** | Guideline, Playbook, Checklist, Form, Register | Nothing by default |

Where a family has **no Standard**, the Procedure that carries control blocks is the defining document. The test is structural, not a title guess.

### Stage 3 — Parse, deterministically
- **Control blocks** → one candidate per ID, every field with provenance.
- **Section headings citing IDs** → implementation steps, in both syntaxes seen: `(BCDR-01)` and `(implements CDI-001, CDI-019)`.
- **Roles table** → role mentions *with duty descriptions*. These seed the Role Catalogue (§8).
- **Annex A** → control map, cross-checked against the headings.
- **Annex B** → record links: record, creator role, step, location.
- **Annex C** → open parameters, recorded as visible gaps.
- **`Mapping:` line** → structured `{standard, clause}` pairs, e.g. `ISO 9001 7.5.2; ISO/IEC 27001 7.5.2, A.5.1` → three pairs.

### Stage 4 — Resolve
Each resolvable value keeps its as-written form (P4) and gains a resolution with a status:

| Value | Resolved against | Outcomes |
|---|---|---|
| `REC-nnnn` | Records Catalogue | Found · *Not in catalogue* |
| Role | Role Catalogue (name, then alias) | Recognised · Proposed · *Unrecognised* |
| Mapping | Clause Catalogue | Matched · *Unknown clause* |
| Parent / child doc | Document Register | Found · *Missing* |

### Stage 5 — Fallback, labelled
For a document in scope that should define controls but doesn't parse, two things happen:

1. A **CDI finding** is raised. A Standard that can't be parsed fails CDI-003, whose stated risk is *"controls cannot be extracted or audited because register fields or layer content are missing."* The CDI checker should share this parser so the two never disagree.
2. Optionally, the **LLM extracts** — but it returns roles and records *verbatim*, with no vocabulary in the prompt and no "pick the closest" instruction. Resolution happens in Stage 4, in code. Every field is marked `inferred`, and these candidates carry no Control ID; they're **Legacy** controls until a document defines them.

### Stage 6 — Diff
Compare each candidate with what's confirmed for that Control ID:
- **Unchanged** → closed automatically, never shown to a reviewer.
- **Changed** → a Zone 1 item showing the field-level diff.
- **New** → a Zone 1 item.

Re-extracting a revised Standard therefore produces a small set of real changes. Today a re-run only skips a statement whose text exactly matches one already queued for that document (`agents/extractor/service.py:547-552`); a control that was reworded arrives as a brand-new item and, if accepted, a second Control Register row alongside the old one.

### What the LLM does in this design
| Use | Status |
|---|---|
| Extracting from documents with no structure | Fallback, labelled `inferred` |
| Suggesting a role for an unresolved mention, from duty descriptions | Advisory, scored, human decides |
| Flagging a Procedure clause that semantically contradicts its Standard | Advisory |
| Gap narrative and remediation drafting | As today |
| Filling any field silently | **Never** |

---

## 6. Review queue and the accept cascade

### Zones, redefined
| Zone | Today | After |
|---|---|---|
| **1** | Extracted controls | **Control definitions** — new and changed, with field-level diffs and per-field provenance |
| **2** | JD orphans | **Things that don't resolve** — unrecognised roles, functional roles needing a scope, REC IDs not in the Catalogue (raised as Record admission requests, a CDI concept), plus JD orphans as now |
| **3** | Near-duplicate controls | **Conflicts** — see §7 |

### What "accept" writes
Today, accepting one item writes one Control Register row and one Evidence Tracker row, and stores the control **Active if the owner string is non-empty** (`review_queue/router.py:296`).

After:
1. **Upsert** the Control Register row by `ControlId`. A changed definition updates; it never duplicates.
2. Write **Control Implementations** for each implementing step.
3. Write **Control Record Links** for each confirmed record.
4. Set status by resolution: **Active** only if the accountable role is Recognised; otherwise **Blocked**, with `BlockedReason` saying which field and why.
5. **Don't create an evidence row here.** Obligations are generated from the links (§9), because one control can need several records.
6. Write the Audit Log, as now.

The cascade already compensates on failure, since SharePoint has no transactions (`review_queue/router.py:337-340`). With more lists in play, that pattern extends to every write in the chain, in reverse order.

---

## 7. Harmonisation, redesigned

Today harmonisation compares control *text* with `difflib` (80% similarity) across documents. With Control IDs most of that becomes exact, and the cases separate cleanly:

| Case | Example | Action |
|---|---|---|
| **Same ID, defined twice** | Two documents both define BCDR-01 | Zone 3 → *Select governing document* (already a Zone 2 decision) → lifecycle fix task to the other |
| **Implementation contradicts definition** | Procedure names a different role or trigger for BCDR-01 than the Standard | Standard prevails (the Procedures say so) → lifecycle fix task to the Procedure |
| **Cited but not defined** | A Procedure implements BCDR-07, which no Standard defines | *Unmapped requirement* finding |
| **Defined but not implemented** | A Standard control no Procedure carries out | Informational finding |
| **Similar text, different IDs** | Near-duplicate controls in two domains | Today's `difflib` path, unchanged |
| **Legacy, no ID** | Fallback-extracted controls | Today's `difflib` path, unchanged |

Zone 3 decisions keep routing fixes to the source documents (P8) — that part of today's design is right.

One small fix while there: Zone 3 lifecycle tasks are created with `document_type="Policy"` hard-coded. They should carry the real type.

---

## 8. Roles, end to end

### Where the vocabulary comes from, in order of authority
1. **The controlled organogram** — Recognised.
2. **Roles tables in CDI documents** — Proposed, *with duty descriptions*. Every v06 Procedure has one, so this gets us a usable vocabulary before the organogram arrives.
3. **Entra job titles** — demoted to a **hint** for suggesting who holds a role. Never an owner in their own right. Bobby: *"A Microsoft job title alone is not sufficient authority for a role assignment."*
4. **Free text** — Unrecognised; flagged.

### How a role resolves
```
as written:  "Accountable Department Head"
   ├─ exact or alias match in Role Catalogue? ── yes → Recognised
   └─ no ──→ Unrecognised → Zone 2
              └─ advisory: top suggestions scored from duty descriptions
                 reviewer: map to a role (adds an alias) · propose a new role · reject
```

### How a person resolves (Bobby's field 6)
```
(role, scope) → Role Assignment → verified Entra identity
   Positional: (Head of IT and Infrastructure, Global) → [vacant]
                → acting: Chief Technology Officer → <person>
   Functional: (Accountable Department Head, Process: Payroll) → <person>
   Team:       (Customer Success, Global) → members
   System:     platform check V03 → no person; shown as automated
```

The **resolution path is stored and displayed**, not just its result. When a person changes, every control resolves afresh — nothing has to be re-edited.

Vacancy is real, not hypothetical: the BCDR Procedure already says *"Head of IT and Infrastructure (the CTO holds the duty while the title is vacant)."* `ActingHolderOid` and `ActingUntil` cover it.

### What changes in the code
- `OwnershipIndex` (`ownership/resolver.py`) gains role kind, status and scoped resolution. Every caller benefits at once: Standards Map, Gap Analyzer, Control Register and Record Tracker all resolve through it already.
- Job titles stop being treated as owners, so a control owned by a raw job title becomes Blocked with a clear reason — **a migration step, not a silent change** (§11).
- The Org Roles page's "Owns" column, keyed today on job title, keys on role instead.
- The classifier's role-conflict check stops comparing normalised strings and compares resolved roles. Today "Head of IT" and "IT Head" are reported as a conflict.

### AI role suggestions — when, and how
Built in Phase 4, after the vocabulary exists (§12), because a score needs descriptions to compare against. Suggestions are advisory, show the reasoning, and take one click to accept. Accepting a suggestion **adds an alias**, so the same mention resolves automatically next time. That's how the vocabulary improves through use rather than by guessing.

---

## 9. Records and evidence, end to end

### The Catalogue in OrgOS
- Imported from the Excel master, with every validation column intact.
- Read-only in OrgOS to begin with — see decision D1 on whether OrgOS later becomes the master.
- **The disposition gate is built before any disposition feature** (P9).
- A `REC-nnnn` cited in a document but absent from the Catalogue becomes a **Record admission request** to the Compliance Executive — the CDI Standard defines that request and says who assigns IDs.

### Two frequencies, never one
| | Operating trigger | Evidence check frequency |
|---|---|---|
| Means | When the control runs | When we confirm the proof exists |
| Source | `Trigger:` line of the defining document | Stated in the document, or **set by a person** at confirmation |
| CDI-001 example | *Creation, submission, reclassification* | e.g. quarterly review of REC-0623 |
| If absent | Shown as "not stated" | Obligation exists but is **unscheduled**, and says so |

Today one free-text `EvidenceFrequency` field, filled by the model, stands in for both.

### Obligations
- One obligation per **Control Record Link**, optionally per scope. Phase 5 starts with one per link; per-process expansion (e.g. one BCDR-01 obligation per Tier 1/2 process) follows once scope lists exist.
- **Reference at source.** The obligation points to the record's authoritative location from the Catalogue. Today evidence is uploaded into OrgOS under `Evidence/EVID-…`, which copies it — Bobby §3 says not to where the source system is already authoritative. Upload stays only for records whose authoritative location *is* OrgOS.
- **Freshness.** A record past its freshness period is *stale*, distinct from *missing* or *late*.

### Routing
Missing, late, incomplete and stale evidence route through what already exists — the scheduler (`jobs/`), Power Automate notifications on list changes, and Gap Analysis findings. Each obligation also shows the control's own **Failure route** and **Exception route**, because the defining document has already said what happens.

---

## 10. What changes in each downstream module

| Module | Today | Change |
|---|---|---|
| **Extractor** | LLM asked for 4 fields; vocabulary injected into the prompt | Parser first; LLM fallback with no vocabulary injection; verbatim roles |
| **CDI Checker** | Its own regex checks | Shares the parser; a Standard that won't parse is a CDI-003 finding |
| **Review Queue** | One row per accepted item; Active if owner non-empty | Diffs by Control ID; upsert; Active only if the role is Recognised |
| **Classifier** | Text similarity only; roles compared as strings | ID-based conflicts first; similarity for legacy and cross-ID only; resolved roles |
| **Control Register** | Free-text control, no ID | Control ID and the full field set, with provenance |
| **Evidence / Record Tracker** | One row per control; uploads copy evidence | Obligations per link; reference at source; two frequencies |
| **Standards Map** | 23 hard-coded clauses; `startswith` matching | Clause Catalogue; exact `{standard, clause}` matching |
| **Gap Analyzer** | 18 hard-coded clauses; one record per control | Same Clause Catalogue; many records per control; new gap types |
| **Ownership resolver** | Job titles + groups | Role kinds, status, scopes, delegation |
| **Org Roles / Groups UI** | Groups with members and aliases | Role Catalogue fields; Unrecognised queue |
| **Document Lifecycle** | Approval triggers extraction | Approval of a Standard re-parses and diffs; superseding a document supersedes its definitions |
| **Document Register** | Code, type, version | Defining/implementing flag; parent and child links from the control block |
| **Policy Drafter** | Section-by-section prose (DRG-QI-REF-DOCS-01-26 sequence), no labelled control blocks | Drafts Standards in the v06 control-block shape, so what it writes, the parser can read |
| **NL search** | Indexes control text | Indexes by Control ID |

### Two Standards Map bugs this fixes — verified, worth fixing early regardless

**Prefix matching double-counts.** Controls are matched to clauses with `ISOClause.startswith(clause)` (`standards_map/router.py`). A control mapped to **A.5.18** is counted under **A.5.18 and A.5.1**, so A.5.1's traffic light reflects controls that aren't about A.5.1. The same matching ignores which standard a clause belongs to, so ISO 27001 clause 7.5.2 would land in the ISO 9001 7.5 row.

**Correct mappings vanish.** A properly parsed mapping — `ISO 9001 7.5.2; ISO/IEC 27001 7.5.2, A.5.1` — matches **no** clause, so a well-extracted control wouldn't appear on the map at all.

Also: the map's 23 clauses and the Gap Analyzer's 18 are two separate lists that have already drifted — 5 clauses show on the map but are never checked for gaps. And neither includes **ISO 22301** or Annex A **5.19, 5.20, 5.29, 5.30**, which is everything the BCDR Procedure maps to. Today BCDR controls could never appear on the Standards Map.

---

## 11. Migrating what's already there

Nothing is deleted. Everything is reversible until cut-over.

1. **Shadow run.** The new pipeline writes its results to a report and to new columns only. Today's flow carries on untouched, behind a flag in the style of `DOCUMENT_WRITE_MODE`.
2. **Match existing controls to IDs.** For each defining document re-parsed, propose a match from existing Control Register rows (same source document, then text similarity) to Control IDs. A reviewer confirms in a batch. Matched rows gain their `ControlId` and keep their item id, links and history.
3. **Unmatched rows become Legacy**, not deleted. A triage list decides whether each is withdrawn, kept as legacy, or raised as a gap in a defining document.
4. **Map existing evidence rows to Record IDs** by name and alias against the Catalogue. Proposed, confirmed in a batch.
5. **Map existing owner strings to the Role Catalogue.** Unmapped ones surface in Zone 2. This is the step that turns today's silently-Active-but-unowned controls into honest Blocked ones, so it's worth telling people before it happens.
6. **Close or re-queue pending queue items** created by the old extractor.
7. **Cut over** domain by domain, starting with CDI and BCDR.

---

## 12. Delivery plan

Ordered so each phase is useful on its own, and so Bobby sees the demonstration he asked for **before** we change any register. Durations are rough and assume one developer full-time; they move with what we learn in Phase 1.

### Phase 1 — Parser and demonstration · ~2–3 weeks · writes nothing
- The deterministic parser: document control block, Standard control blocks, implementing sections in both syntaxes, Annex A/B/C, mapping lines.
- Catalogue import as an in-memory reference.
- **Library census:** run the parser across every in-scope document and report how many are parseable, partially parseable, or prose. This sizes the fallback problem with data rather than assumption.
- **Demonstration report** on the documents Bobby named — the CDI Standard, its Procedure, the Records Governance Procedure, the BCDR Standard and Procedure, and the Catalogue — showing every control's nine fields, resolution status per field, and every gap.

**Exit:** Bobby has reviewed the report; the census tells us how much fallback we need.

### Phase 2 — Reference data · ~1–2 weeks
- `reference/clauses.yaml` with ISO 27001 (clauses and Annex A), ISO 9001, ISO 22301 and NDPA. Point the Standards Map and Gap Analyzer at it — **this fixes both Standards Map bugs**, and can ship on its own.
- Records Catalogue list, imported, with the disposition gate.
- Role Catalogue fields on Groups; Role Assignments list; seeded from Procedure Roles tables, then the organogram.

**Exit:** every REC ID and role in the demonstration documents resolves, or is flagged with a reason.

### Phase 3 — Model, review and cascade · ~2–3 weeks
- New columns and lists provisioned.
- Zone 1 diffs, Zone 2 resolution items, the upserting cascade.
- Role resolution at accept.

**Exit:** re-extracting an unchanged Standard produces zero reviewer items; changing one requirement produces exactly one.

### Phase 4 — Downstream · ~2–3 weeks
- Control View with the nine fields and CDI extras.
- Gap Analyzer gap types; harmonisation by ID; scored role suggestions; classifier on resolved roles.

### Phase 5 — Evidence · ~3–4 weeks
- Obligations from links; two frequencies; reference at source; freshness; routing through the scheduler, Power Automate and gap findings.

### Phase 6 — Migration and cut-over · ~2 weeks, domain by domain
- Shadow run, matching batches, legacy triage, cut-over starting with CDI and BCDR.

**Total: roughly 12–17 weeks**, front-loaded with the parts that prove the approach.

---

## 13. What I need from you

### Documents
| # | What | Why |
|---|---|---|
| R1 | **Records Retention Rule Schedule** (DRG-QI-REG-RRS) | Defines RR-01…RR-31. Without it "RR-26" is an opaque code |
| R2 | **Records Systems Register** (DRG-QI-REG-RSR) | Resolves S01, S06, S08, S09 to real systems (Catalogue rule GR-12) |
| R3 | **Controlled organogram** — roles, reporting lines, holders, people with several roles, vacancies and acting holders | The Recognised role vocabulary |
| R4 | **BCDR Standard** (DRG-ISMS-STD-BCDR) | Defines BCDR-01…06; we only have the Procedure that implements them |
| R5 | **Records Governance Procedure** (DRG-QI-PRO-IRG) | Implements the IRG controls; part of the demonstration Bobby asked for |

### Decisions — mostly for Bobby and Compliance
| # | Decision | Why it matters |
|---|---|---|
| **D1** | **Is OrgOS the system of record for the Records Catalogue?** The Catalogue's own entry for itself, REC-0632, gives its location as *"S09 OrgOS GRC"*. If yes, OrgOS hosts the master, with admission and validation workflows. If no, OrgOS mirrors a master held elsewhere. | Decides whether Phase 2 builds a mirror or a governed register — a much bigger module. |
| **D2** | **Which governing set is current?** The consolidated **CDI Standard** (DRG-QI-STD-CDI) holds CDI-001…021 *and* IRG-001…024 in the labelled format, with new-style codes. The **review package** has a separate IRG Standard (DRG-QI-STD-IRG-01-26) in prose, with no control IDs and old-style codes. I read the consolidated Standard as the newer one. | Decides which document we build the IRG controls from. |
| **D3** | **How are WIP and superseded copies marked** in the Control Library — a folder, a filename convention, or the control block's `Issue Status`? Note the current CDI and BCDR documents themselves say `Issue Status: Draft`. | Ingestion must exclude them, and today excludes nothing. |
| **D4** | **The resolution rule for each functional role:** Document Owner, Control Owner, Custodian Role, Accountable Department Head, Contract-owning Department Head. | A short, one-off governance decision. Without it these stay Blocked. |
| **D5** | **Who sets an evidence check frequency** when the document doesn't state one? | The scheduling half of field 7. |
| **D6** | **Evidence type taxonomy.** OrgOS enforces the 16-code taxonomy (DRG-QI-REF-EVTX-01-26). The CDI Standard's IRG-002 says the **Enterprise Record Type Taxonomy** "MUST be the authorised set of Types" — the Catalogue uses 85 types. Do the 16 codes retire? | Two taxonomies can't both be authoritative. |
| **D7** | **May an Entra job title still own a control**, or only a Recognised role? I recommend only Recognised roles, per Bobby's line on job titles. | Decides how many existing controls go Blocked at migration. |
| **D8** | **Who approves role vocabulary changes** — new roles, aliases, functional resolution rules? | The Role Catalogue needs an owner, as the Catalogue does. |
| **D9** | **Existing evidence copied into OrgOS** under `Evidence/` — leave, or re-point to source? | Bobby §3. |

### Access and time
- Continued Graph read access to every domain folder in the GRC Control Library.
- About **an hour with Compliance** for D4 and D8, and a **review session with Bobby** on the Phase 1 report.
- Someone to confirm the Phase 6 matching batches for each domain — that's the slow, human part, and it's also where the data becomes trustworthy.

---

## 14. Risks, and how we contain them

| Risk | Containment |
|---|---|
| Much of the library isn't v06-shaped | The Phase 1 census measures it before we commit to anything; fallback items are labelled and treated as Legacy |
| Parser drift as house style evolves | Golden tests on the real documents; a parse failure becomes a CDI finding, not silence |
| Migration Blocks a lot of controls at once | Shadow run first, owners mapped in batches, and people told before cut-over |
| SharePoint has no transactions | Compensating rollback, extended from today's cascade pattern |
| SharePoint list thresholds | Indexed `ControlId` and `RecordId` columns; 729 records and a few hundred controls are well within limits |
| Two clause lists drift again | One `clauses.yaml`, with a test that both consumers use it |
| A wrong owner gets signed off | Unrecognised is Blocked, never guessed; the resolution path is shown at confirmation |
| Unvalidated retention triggers disposal | The gate ships before the feature, with a test asserting it |

---

## 15. What "done" looks like

The test is Bobby's own request: take the CDI Standard, its implementing Procedures and the Enterprise Records Catalogue, and show *"the resulting control view, the resolved fields and any gaps so we can see precisely what the system can operate and what needs correction."*

Concretely, for every control in those documents, OrgOS shows:

- **Control ID**, requirement, and its defining document, version and section.
- **Accountable and executing roles**, each as written and as resolved, with the person and the resolution path — or a visible reason it won't resolve.
- **Every evidence record** by REC ID, with name, custodian, location, retrieval, and retention *with its validation status*.
- **The operating trigger and the evidence check frequency**, separately — or "not stated".
- **Risk, failure route, exception route and standards mapping**, as the document states them.
- **Every implementation step**, from every Procedure, under the one control.
- **Every gap**, as a finding with an owner: unrecognised role, unknown record, unvalidated retention, open parameter, unmapped requirement, conflict.

And nothing on that page was guessed.
