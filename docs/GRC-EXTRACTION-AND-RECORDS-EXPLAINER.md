# GRC Extraction, Roles and Records — what the framework actually requires, and what we build

**Audience:** Paul and Adekunle, to act on and to answer Bobby with.
**Sources read for this:** the BCDR Impact, Register and Process Continuity Procedure (DRG-ISMS-PRO-BCI); the Control of Documented Information Standard (DRG-QI-STD-CDI); the Enterprise Records Catalogue — Production Candidate (729 records); Bobby's brief; and the current OrgOS extractor.

---

## 1. The short version

The extracted "control" that started this is not a control, and the role in it is not a hallucination.

What the extractor produced was **clause 4.1 of a Procedure** — an implementation step. The actual control is **BCDR-01**, defined in the BCDR *Standard*, which the Procedure implements. And "Accountable Department Head" is a real, governed role: it is named in the Procedure's own Roles table (§3.0), and it appears in the Enterprise Records Catalogue as the custodian of REC-0676. The AI read the document correctly.

So the problem is not prompt quality. It is three structural mismatches:

| | What the framework says | What OrgOS does today |
|---|---|---|
| **Where controls live** | Defined once in a Standard; Procedures implement them under the same ID | Every document is treated as a fresh source of controls |
| **What a control is** | A record with a Control ID and 8 named fields | Free text with 1 owner role and no ID |
| **What a role is** | Three different kinds, only one of which maps to a person | A bare string matched against Entra job titles and OrgOS Groups |

> **Note on OrgOS's current state.** `CLAUDE.md` still documents a SharePoint-backed Role Register with `variant_terms` and `/api/v1/grc/roles`. **That was retired and no longer exists in code** — `README.md:984` says not to reintroduce it. Today a role is a string resolved against live Entra job titles plus OrgOS Groups (`ownership/resolver.py`). The sections below describe what is actually there. CLAUDE.md needs updating separately.

The good news is much better than expected: **CDI documents are already machine-readable.** We should be parsing them, not inferring from them. More on that in §3 — it is the single biggest change to the design.

---

## 2. What actually happened to that control

### What we extracted

> The Accountable Department Head records for each Tier 1 and Tier 2 process in REC-0676: 1. the maximum tolerable downtime; 2. the busiest periods; … 6. the secure workaround and how work is reconciled afterwards.

### What it really is

That is clause **4.1** of DRG-ISMS-PRO-BCI, verbatim. The document labels its own section:

> **4.0 Business impact assessment (BCDR-01)**

and the Procedure's Annex A says so again:

> | Standard control | Clause in this Procedure |
> | BCDR-01 Business impact assessment | 4.0 |

And its control block states plainly:

> **Standard controls implemented:** BCDR-01; BCDR-02; BCDR-04; BCDR-05; BCDR-06

So this Procedure implements **five** controls that already exist in the BCDR Standard. It introduces none. If we extract it as written today, we create five or more *new* controls that are duplicates of controls defined elsewhere — exactly what Bobby warned against:

> Procedures beneath a Standard implement its controls using the same IDs; they must not be counted as additional controls simply because they repeat a requirement.

### Three separate failures in one item

1. **No Control ID.** `ExtractionItem` has no `control_id` field at all (`agents/extractor/schemas.py:236-242`), and the Control Register has no control code either — the SharePoint item id is the identifier. Without it there is no way to say "this clause implements BCDR-01" rather than "here is a new control". Everything else follows from this.
2. **An implementation step was captured as a control.** The requirement belongs to BCDR-01 in the Standard. Clause 4.1 is *how Dragnet does it*. Both matter, but they are different objects.
3. **The role was permitted, not resolved.** This one is more subtle than it looks, and worth getting right before anyone concludes the model misbehaved.

The extractor *does* inject a role vocabulary into the prompt: your OrgOS group names plus every distinct job title held by an enabled Entra user — about 38 today (`agents/extractor/ollama_client.py:189-221`, `agents/extractor/service.py:775-788`). But the instruction ends:

> *"Return the single best-fitting title exactly as written above. **Only if none is a reasonable fit, use the role as written in the document.**"*

No Dragnet job title is a reasonable fit for "Accountable Department Head", so the model took the documented escape hatch and quoted the document. **It did exactly what we told it to.**

Then nothing downstream caught it. At Zone 1 accept the only test is whether the string is non-empty (`review_queue/router.py:296`):

```python
"Status": "Active" if owner_role else "Blocked",
```

So an unresolvable role is written to the Control Register as **Active**. It is detected later — the Gap Analyzer raises a Major "Ownership gap" (`agents/gap_analyzer/service.py:190-215`) and the Standards Map shows red — but by then a reviewer has already signed it off.

The accept cascade should resolve the role rather than test it for emptiness — that is worth fixing regardless of the rest of this work.

> **Correction.** An earlier version of this document said a 120-title cap truncates the vocabulary. It does not, at your size: `job_titles[:120]` is a ceiling, and with ~38 titles plus your groups every one is sent. The problem is not *how many* titles the model sees but *what kind of thing* a job title is — see §6.

### The record reference was thrown away

The clause says **REC-0676**. That single token is the key to six of Bobby's nine fields, and we currently discard it. The Catalogue resolves it immediately:

```
REC-0676  Business Impact Assessment Summary
  Type:       Report / Analysis Record
  Custodian:  Accountable Department Head named in REC-0676
  Location:   S01 SharePoint, Governance & Records library,
              folder "Business Impact Assessment Summary"
  Retention:  RR-26        Validation: Set at business review
```

---

## 3. CDI documents are already machine-readable — this changes the design

This is the finding that should change how we build.

A Standard does not describe controls in prose. It states them in a **fixed, labelled block**. From DRG-QI-STD-CDI:

```
CDI-001 Approved parent, no orphans

Requirement:  Every controlled document except the Master Policy and the Manual
              MUST link to an approved parent in the layer above…
Trigger:      Creation, submission, reclassification.
Accountable / Executing:  Compliance Executive (QMS & NDPA) / platform check V03.
Evidence:     REC-0623 Controlled Document Register; validation result REC-0635.
Risk:         A document is issued without authority because its parent is
              missing or unapproved, so controls conflict or go unowned.
Failure route:   Submission blocked (V03). An orphan found in the issued estate
                 is raised as a nonconformity to the Compliance Executive…
Exception route: None.
Mapping:      ISO 9001 7.5.2; ISO/IEC 27001 7.5.2, A.5.1.
```

Now compare what our extractor asks the model for. The entire policy prompt requests **four fields** (`ollama_client.py:113-127`):

> `"s"` the control sentence · `"r"` what goes wrong · `"o"` the responsible role · `"c"` the ISO clause

Everything else is then filled in by keyword rules: `control_type` by word matching (`_assign_control_type`), `evidence_type` by word matching (`_suggest_evidence_type`). The document states Trigger, Evidence, Risk, Failure route, Exception route and Mapping **explicitly, on labelled lines** — and we ask the model to re-derive two of them from scratch and guess at the rest.

I parsed that same Standard with a plain regular expression, no AI involved. The result:

- **45 controls** extracted with **all 8 fields present on every single one** — 45/45 for Requirement, Trigger, Accountable / Executing, Evidence, Risk, Failure route, Exception route, Mapping.
- **8 distinct accountable roles**, a small controlled vocabulary.
- **15 distinct REC IDs** referenced as evidence.

Procedures are structured too, just differently: a Roles table (§3.0), clause sections tagged with the control ID they implement, a risk statement per control, **Annex A** mapping control → clause, and **Annex B** listing records with creator, step, location and retention.

### What this means

**Our extractor is solving a harder problem than the documents pose.** It sends prose to an LLM and asks it to invent structure that is already there — and the LLM's output is then "normalised" by keyword rules (`_assign_control_type`, `_suggest_evidence_type`). That is a lossy path for a document whose fields are literally labelled.

The design should invert:

1. **Parse first.** If the document has the CDI control block shape, read the fields directly. Near-100% fidelity, reproducible, no model cost, no hallucination surface.
2. **Use the LLM only where structure is absent** — legacy documents, and the handful of judgement calls (is this clause a requirement or narration?).
3. **Treat a parse failure as a document-quality finding**, not as a reason to guess. A Standard that does not parse is a CDI nonconformity — which is CDI-003's own requirement: *"Controls cannot be extracted or audited because register fields or layer content are missing."*

This also gives us the demonstration Bobby asked for, on the documents he named, with evidence rather than model output.

---

## 4. The Enterprise Records Catalogue — what it is and what it gives us

They told you it is "a guide for record collection". That undersells it considerably. It is a **governed register of 729 records** (REC-0001 … REC-0729) and it is the authority for where evidence lives and how long it is kept. Here is what is actually in it.

### Structure

- **Enterprise Records Catalogue** — 729 rows × 29 columns, the master.
- **Findability View** and **Retention & Disposition** — derived views over the same Record IDs. Per rule GR-10 they are *not* separate systems of truth.
- **Location & Retention Basis** — one line per record: System ID, location, rule, rule status, custodian.
- **Governance Rules** — 12 rules (GR-01…GR-12) that constrain how the catalogue may be used.
- **Type & Scope Review Queue**, **Unadmitted Candidates**, **Proposed Rule Changes** — the open items.

### The fields that matter to us

Per record: Record ID, Canonical Record Name, Aliases, Controlled Record Type, Admission Status, Source Documents, Privacy Overlay, **Process Custodian**, **Authoritative Location / System**, **Retrieval Instruction**, **Retention Period / Rule**, **Retention Trigger**, **Retention Authority**, **Disposition**, Destruction Method, Destruction Evidence, Legal Hold, Specialist Register Reference, and two validation-status columns.

### The rules we must obey

These are not advisory — they are the operating rules of the catalogue, and several directly constrain what OrgOS may do:

- **GR-03** — a Record ID is stable; renaming does not change it. *So we link by ID, never by name.*
- **GR-04** — custodian, location, retrieval, retention and disposition are governed at the **Record Name / process context**, not at Record Type. *So we must not infer a record's retention from its type.*
- **GR-09** — ROPA, Risk Register and other specialist masters stay authoritative in their domain; the catalogue cross-references rather than recreates. *This applies to us too: OrgOS cross-references, it does not recreate.*
- **GR-11** — **automated disposition is prohibited until operational metadata is validated.** This is the hard one. See below.
- **GR-12** — every entry cites one System ID from the Records Systems Register (DRG-QI-REG-RSR).

### How much of it is actually validated — the critical caveat

This matters more than anything else in the workbook, and it must shape what we build:

| Dimension | State |
|---|---|
| Record Validation Status | **625 of 729** are "identity/type-only migration state" — the ID and Type are admitted, operational metadata is **not** validated |
| Retention Validation | 381 "Recommended – business review pending" · 250 "Unreconciled – source statement only" · 87 "Set at business review" · **8 validated** · 3 not validated |
| Findability Validation | 565 "Recommended – business review pending" · 69 "Not stated" · 66 controlled-source evidence · **8 validated** |
| Admission Status | 727 Governed Record · 2 withdrawn duplicate proposals |

So: **the identities are solid, the operational metadata mostly is not.** The cover sheet says it plainly — *"unvalidated records are prohibited from automated disposition."*

This is exactly Bobby's §5:

> Catalogue entries marked recommended or pending business review must retain that status. Missing values must remain visible rather than being filled by AI inference. Automated disposal must not proceed on unvalidated retention rules.

**Design consequence:** every catalogue-derived field in OrgOS carries its validation status with it, and the UI shows it. An unvalidated retention rule is displayed, never acted on. We build the disposition *machinery* but gate it on validation status, and it stays off for 721 of 729 records until Compliance validates them.

### It works — proof

Every record the BCDR Procedure names resolves cleanly:

| In the Procedure | Resolves to | Custodian | Retention |
|---|---|---|---|
| REC-0675 | BCDR Criticality Mapping Sheet | Head of IT and Infrastructure | RR-26 |
| REC-0676 | Business Impact Assessment Summary | Accountable Department Head named in REC-0676 | RR-26 |
| REC-0678 | Process Continuity and Recovery Register | Accountable Department Head named in REC-0676 | RR-26 |
| REC-0679 | Third Party Continuity Register | Contract-owning Department Head named in REC-0679 | RR-23 |
| REC-0680 | Contract Workforce Continuity Register | HR Manager | RR-26 |
| REC-0681 | Critical API and Communication Register | Head of IT and Infrastructure | RR-26 |
| REC-0688 | Continuity Decision and Exception Record | Chief Technology Officer | RR-26 |

7 of 7. The linking Bobby describes is achievable today.

### Two things the workbook does not contain

1. **The RR-xx rules themselves.** Every row cites a rule code (RR-11 is the most common, on 141 records) but the definitions live in *"Schedule Annex A"* — the **Records Retention Rule Schedule, DRG-QI-REG-RRS**. Without it, "RR-26" is an opaque token. **We need that register.**
2. ~~**The System IDs.**~~ **Correction:** the *Location & Retention Basis* sheet already names every system — S01 = SharePoint (family library), S05 = SeamlessHR, S08 = Microsoft 365 and Entra ID, and so on, 16 in all. The Records Systems Register (DRG-QI-REG-RSR) is not needed to resolve them.

Both are named as child documents of the CDI Standard, so they exist. Ask for them.

---

## 5. The nine fields — where each one actually comes from

Bobby's list, mapped to its real source, with what we have today.

| # | Field | Authoritative source | In OrgOS today |
|---|---|---|---|
| 1 | **Control ID** | The Standard's control block (`BCDR-01`, `CDI-001`) | ❌ **No field exists** |
| 2 | **Control description / requirement** | `Requirement:` line in the Standard | ⚠️ `control_statement`, free text, no ID |
| 3 | **Supporting evidence record name** | Catalogue → Canonical Record Name | ⚠️ `evidence_description`, free text |
| 4 | **Record ID** | `Evidence:` line → `REC-nnnn` → Catalogue | ❌ **Discarded** |
| 5 | **Responsible role** (accountable ≠ executing) | `Accountable / Executing:` — already split by `/` | ❌ One `proposed_owner_role`, unvalidated at intake |
| 6 | **Responsible person** | Recognised role → verified directory identity | ⚠️ `OwnershipIndex` resolves role → people at read time; nothing is stored |
| 7 | **Trigger / frequency for confirming proof** | Two different things — see below | ⚠️ `evidence_frequency` conflates them |
| 8 | **Record retention rule** | Catalogue → Retention Period / Rule + Trigger + Authority | ❌ Nothing |
| 9 | **Record location and retrieval** | Catalogue → Authoritative Location / System + Retrieval Instruction | ⚠️ `source_system`, free text |

Plus the CDI extras Bobby lists in §4, all of which a Standard already states and we currently drop: **risk, authority, standards mapping, monitoring method, evidence freshness, failure route, exception route**, and source document + version + section.

### Field 7 deserves its own note

Bobby is explicit:

> Please also distinguish when a control operates from when its evidence is checked. For example, a check performed on each transaction and a monthly review of evidence are different requirements. Neither frequency should be guessed.

These are two fields, not one:

- **Control operating trigger** — from the Standard's `Trigger:` line. For CDI-001: *"Creation, submission, reclassification."* Event-driven, not periodic.
- **Evidence confirmation frequency** — when we check the proof exists. For CDI-001 that might be a monthly or quarterly review of REC-0623.

Today `evidence_frequency` is a single free-text field filled by the LLM. It has to become two fields, and where the document does not state one, it stays **empty and visible**, not guessed.

---

## 6. The role problem, properly understood

This is the heart of what you were asked to solve, and the usual answer — "have the AI match roles with a confidence score" — is only about a third of the answer.

### Roles in CDI documents are three different kinds of thing

Looking at the actual vocabulary across the CDI Standard (8 accountable roles) and the Catalogue (21 distinct custodians):

**Kind 1 — Positional roles.** `HR Manager`, `Information Security Officer`, `Chief Compliance Officer`, `Head of IT and Infrastructure`, `Chief Technology Officer`.
These map to a post in the organogram and resolve to a person through the directory. This is the only kind OrgOS handles well today.

**Kind 2 — Functional / relational roles.** `Document Owner`, `Control Owner`, `Custodian Role`, `Accountable Department Head`, `Contract-owning Department Head`.
**These do not resolve to one person at all.** "Accountable Department Head" means *the head of whichever department owns this particular process*. It resolves **per instance**, and the instance is named in a record. The Catalogue says this out loud:

> Process Custodian: **Accountable Department Head named in REC-0676**

That is the catalogue telling us the resolution route: look it up in the record. A global role-to-person mapping cannot answer it, and a confidence percentage on it is meaningless.

**Kind 3 — Team / function labels.** `Customer Success`, `Cloud Operations`, `Legal / Corporate Governance`, `BCDR / Information Security`.
A group, not a post. Resolves to a set of people, or to a group's lead.

### What OrgOS actually has to match against

There is no Role Register — it was retired. Today a role resolves through `ownership/resolver.py` against two sources:

| Source | What it is | Has a description? | Synonyms? |
|---|---|---|---|
| **Entra job titles** | Every distinct `jobTitle` on an enabled user, read live | **No** — a bare string | No |
| **OrgOS Groups** | A SharePoint list of named groups with members | **Yes** | Yes — up to 6 aliases each |

`OwnershipIndex` normalises both into one lookup and returns `{resolved, kind, canonical, people}`. Groups overwrite same-named job titles; aliases only fill unoccupied names.

That model handles **Kind 1** well and **Kind 3** reasonably — a group is close to a team role. It cannot represent **Kind 2** at all, because a functional role has no fixed membership.

It also undercuts the AI suggestion idea you raised: an Entra job title carries **no description**, so there is nothing for the model to compare a control's wording against. Only groups have descriptions. Matching quality is capped by that, not by the model.

> **Aside on synonyms.** `variant_terms` is gone as a role concept. Group **aliases** replaced it — the Harmonisation page already tells reviewers to "add them as aliases on the matching group under Org roles → Groups so they resolve automatically". That is the right mechanism; it just needs the vocabulary underneath it to be complete.

Kinds 2 and 3 are **governance roles defined by the CDI framework**, not HR posts. They will never appear in a directory sync, no matter how good the matching is. And as you noted, people hold more than one role, which a title-keyed list cannot express either.

Bobby's line is the governing rule here:

> The controlled organogram establishes recognised roles and reporting lines. The Role Register reflects those roles, with verified directory identities used to resolve the current people. **A Microsoft job title alone is not sufficient authority for a role assignment.**

So the role vocabulary needs to come **from the organogram**, not from directory job titles. Yes — please provide the organogram. Specifically we need, from it or alongside it:

1. The **controlled list of recognised roles** — the authorised vocabulary.
2. **Reporting lines** — needed to resolve "the department head for process X".
3. **Role → person assignments**, allowing one person to hold several roles and one role to be held by several people.
4. For each role, its **kind** (positional / functional / group).
5. For each functional role, its **resolution rule** — e.g. *Accountable Department Head resolves via the department that owns the process, named in REC-0676*.
6. **Vacancy handling.** The BCDR Procedure already shows the case: *"Head of IT and Infrastructure (the CTO holds the duty while the title is vacant)."* The model has to carry a delegation.

Item 5 is the one that will not come from an org chart on its own — it is a governance decision per functional role, and it is a short list. Worth asking Compliance to write it down once.

### What the AI should and should not do

**Should:** when a document names a role, match it against the controlled vocabulary and offer the best candidates with a score, using the role's duty description and the control's wording. A reviewer confirms. This is genuinely useful for legacy documents and for ambiguous wording — **once roles have descriptions to match against.**

Note that the documents hand us those descriptions for free. Every CDI Procedure carries a Roles table; BCDR §3.0 is:

> | Accountable Department Head | Owns a process. Sets maximum tolerable downtime and workarounds. Names a trained deputy |
> | Head of IT and Infrastructure | Keeps the Continuity Register. Compares promises with configuration and tests |

That is a role vocabulary *with duty descriptions*, already written, in every Procedure. Harvesting those tables is probably the cheapest route to a usable vocabulary while the organogram is being prepared.

**Should not:** fill in a role that is not in the vocabulary. Per Bobby's §5 — *"Unrecognised roles must be flagged."* The correct output for "Accountable Department Head" when nothing recognises it is **not** a 72% guess at "Head of IT and Infrastructure". It is:

> ⚠ Unrecognised role: "Accountable Department Head" — quoted verbatim from §4.1.
> Does not resolve to a job title or group. This looks like a functional role
> (resolves per process, not to one person).
> → Add to the controlled vocabulary, or map it to a recognised role.

A wrong owner is worse than a blank one, because a blank one gets fixed and a wrong one gets signed off.

### Answering your question about percentages

A confidence score is fine as a **suggestion aid for a human**, and we should build it. But it should be built *after* the controlled vocabulary exists, because:

- Entra job titles have no descriptions, so today there is nothing meaningful to score a control's wording against. The score would be string similarity wearing a percentage.
- For functional roles the right answer is a resolution rule, not a score. "Accountable Department Head" is 100% correct and 0% resolvable to one person; a percentage cannot say that.
- Accountability and execution are two fields; a single score cannot express "accountable: Document Owner, executing: platform check V03".

So: vocabulary first, scoring second. The ordering matters — scoring against today's vocabulary would produce confident wrong answers, which is strictly worse than the flag we get now.

---

## 7. What to build

Staged so each step is useful on its own and nothing depends on decisions we have not got yet.

### Stage 0 — Stop the harm (days)

Small, safe, and it fixes the reported bug.

- Add `control_id` to the extraction schema **and to the Control Register**. Nothing else works without it.
- Resolve every extracted role through `OwnershipIndex` **at Zone 1 accept**, not just at read time. Where it does not resolve, **flag it as unrecognised** and show the verbatim quote. Never substitute. (Today the accept cascade only tests the string for emptiness, so an unresolvable role is stored Active.)
- Replace prompt-side role matching with post-hoc matching: extract the role exactly as written, then resolve it in code, so "as written" and "as resolved" are separate fields.
- Capture the `REC-nnnn` tokens already present in the text instead of discarding them.
- Split `proposed_owner_role` into `accountable_role` and `executing_role`.
- Split `evidence_frequency` into `control_trigger` and `evidence_check_frequency`; leave either blank when the document does not say.
- Update `CLAUDE.md`, which still documents the retired Role Register and will mislead anyone — human or AI — working on exactly this.

### Stage 1 — Load the Records Catalogue as reference data (1–2 weeks)

- Ingest the 729 records as a read-only reference register in OrgOS, keyed by Record ID.
- Carry **every** validation-status column through, and surface it in the UI.
- Resolve `REC-nnnn` → name, type, custodian, location, retrieval, retention, trigger, authority, disposition, privacy overlay.
- Hard rule in code: **no automated disposition on a record whose retention is not validated** (GR-11). Build the gate before the feature.
- Flag any `REC-nnnn` cited in a document that is not in the catalogue — that is a real finding worth reporting.
- **Blocked on:** the Retention Rule Schedule (DRG-QI-REG-RRS), for retention *periods* only.

### Stage 2 — A structured control parser (2–3 weeks)

- A deterministic reader for the CDI control block: `Requirement / Trigger / Accountable / Executing / Evidence / Risk / Failure route / Exception route / Mapping`.
- A reader for Procedure shape: Roles table, clause→control tags, Annex A control map, Annex B records table.
- Record source document, **version** and section for every extracted field (Bobby's §4 bullet 2).
- LLM only as fallback, clearly marked as inferred.
- Report parse failures as CDI findings rather than guessing.

### Stage 3 — Controls vs implementations (1–2 weeks)

- One control record per Control ID, defined from the **Standard** (or the defining Procedure where no Standard exists).
- Procedure clauses attach to the control as **implementation steps**, never as new controls.
- Deduplicate on Control ID, not on text similarity.
- Preserve Policy → Standard → Procedure authority, and flag conflicts and unmapped requirements.

### Stage 4 — Role resolution (2–3 weeks, gated on the organogram)

- Build the controlled role vocabulary from the organogram, carrying the three role kinds and a **duty description** per role. Seed it from the Roles tables already in every Procedure.
- Extend `OwnershipIndex` to resolve functional roles by rule, not by membership.
- Role → person via verified directory identity, supporting many-to-many and delegation for vacancies.
- Then, and only then, AI suggestion with confidence for unmatched roles.

This replaces the retired Role Register with something the framework actually describes — do not simply reinstate the old one.

### Stage 5 — The control view and evidence operation (3–4 weeks)

- The nine-field view Bobby asked for, plus the CDI extras, with per-field provenance and validation status.
- Human confirmation before anything enters the operational registers (his §4 bullet 5) — the Review Queue already does this; it needs the new fields.
- Proof scheduling from the control trigger and the evidence check frequency as **separate** inputs.
- Reference evidence at source; do not copy it into GRC (his §3).
- Route missing / late / incomplete / stale evidence through existing monitoring and exception processes.

---

## 8. What we need before some of this can be built

Worth putting straight back to Bobby:

1. **The Records Retention Rule Schedule (DRG-QI-REG-RRS)** — without it RR-26 is meaningless to the system.
2. ~~The Records Systems Register~~ — not needed; the Catalogue already names every system.
3. **The controlled organogram**, with recognised roles and reporting lines.
4. **A ruling on functional roles** — the resolution rule for each of `Document Owner`, `Control Owner`, `Custodian Role`, `Accountable Department Head`, `Contract-owning Department Head`. Short list, one-off decision.
5. **The BCDR Standard (DRG-ISMS-STD-BCDR)** — we have the Procedure that implements BCDR-01…06 but not the Standard that defines them. For the demonstration we need both.
6. **Confirmation on Annex C.** The BCDR Procedure ships with its open parameters deliberately blank — maximum tolerable downtime per process, several service tiers, retention periods. Per Bobby's §5 these must *stay* visible as gaps. Confirm OrgOS should display them as open parameters rather than treating them as extraction failures.

---

## 9. What to say back to Bobby

Short form, if it helps:

> We have read the CDI Standard, the BCDR Procedure and the Enterprise Records Catalogue against the current extractor. Three things:
>
> **One.** The documents are already structured — the CDI Standard's 45 controls each carry all eight fields in a labelled block, and we parsed them deterministically with no AI. We are changing the design to parse that structure directly and use the model only where it is absent. That removes the inference risk you are concerned about and gives reproducible extraction.
>
> **Two.** The Catalogue links cleanly. All seven records named in the BCDR Procedure resolve to Record IDs with custodian, location, retention and trigger. We will reference it, not recreate it, per GR-04 and GR-09. We will carry validation status on every field, and automated disposition will be blocked wherever retention is unvalidated — which today is 721 of 729 records.
>
> **Three.** The role issue is structural, not an AI error. "Accountable Department Head" is correct in the document and is the custodian named in the Catalogue for REC-0676. It simply is not a directory job title, and job titles plus groups are all our resolver has to match against. CDI roles are of three kinds, and functional roles like this one resolve per process rather than to one person. We are building the role vocabulary from the controlled organogram, and until a role is recognised we will flag it rather than infer a substitute.
>
> To complete this we need the Retention Rule Schedule, the controlled organogram, the BCDR Standard, and a ruling on how each functional role resolves.

---

## Appendix — evidence behind the numbers

| Claim | How it was checked |
|---|---|
| 45 controls, 8/8 fields each | Regex parse of DRG-QI-STD-CDI; every labelled field present on all 45 |
| 8 distinct accountable roles | Distinct values of the `Accountable / Executing:` line, left of the `/` |
| 729 records, REC-0001…REC-0729 | Row count of the Enterprise Records Catalogue sheet |
| 625 identity/type-only | `Record Validation Status` column tally |
| 381 / 250 / 87 / 8 / 3 retention states | `Retention Validation` column tally |
| 21 distinct custodians | `Process Custodian` column tally |
| 7 of 7 BCDR records resolve | Looked up each REC ID from the Procedure's Annex B in the Catalogue |
| No `control_id` in the schema | `agents/extractor/schemas.py:236-262`; Control Register has no control code either |
| Role not resolved at intake | `review_queue/router.py:296` — `"Active" if owner_role else "Blocked"` is the only test |
| Prompt asks for 4 fields | `agents/extractor/ollama_client.py:113-127` |
| Vocabulary = groups + ~38 job titles | `agents/extractor/service.py:775-788`; the `[:120]` at `ollama_client.py:207` is a ceiling never reached |
| Role Register retired | `README.md:984`; no `grc/schemas.py` role classes; `ownership/resolver.py` is the live model |
| Records have no ID/custodian/retention | `record_tracker/router.py:61-87` — full column list, none present |

**Correction made during drafting:** an earlier version of this document said roles are checked against a "Role Register". That register was retired; `CLAUDE.md` still describes it, which is itself worth fixing. The live model is Entra job titles plus OrgOS Groups, resolved by `ownership/resolver.py`.
