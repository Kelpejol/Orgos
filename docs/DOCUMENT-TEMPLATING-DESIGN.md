# Controlled Document Templating — Design & Operating Standard

**Dragnet Solutions Limited · OrgOS GRC Orchestration Module**
**Subject:** Automatic propagation of controlled metadata (version, revision, issue, dates, approver, classification) across compliance documents
**Status:** Design specification (no code) — for review before implementation
**Author reference example:** `DRG-CAE-PRO-3CX-01-26` (3CX Procedure, Rev 03 / Issue 04)

---

## Table of Contents

1. [The Problem in Plain Terms](#1-the-problem-in-plain-terms)
2. [The Core Insight That Changes Everything](#2-the-core-insight-that-changes-everything)
3. [Why NOT AI — and Where AI Still Belongs](#3-why-not-ai--and-where-ai-still-belongs)
4. [The Central Design: Source vs Published](#4-the-central-design-source-vs-published)
5. [The Merge Engine — How Substitution Actually Works](#5-the-merge-engine--how-substitution-actually-works)
6. [The Standard — What "A Standard Document" Means](#6-the-standard--what-a-standard-document-means)
7. [The Three Controlled Zones (and the Markers in Each)](#7-the-three-controlled-zones-and-the-markers-in-each)
8. [The Data Model — What the Register Must Store](#8-the-data-model--what-the-register-must-store)
9. [New Documents — The Full Workflow](#9-new-documents--the-full-workflow)
10. [Existing Documents — The Migration Workflow](#10-existing-documents--the-migration-workflow)
11. [The "Issue New Revision" Bookkeeping](#11-the-issue-new-revision-bookkeeping)
12. [Auditability, Safety & Compliance Guarantees](#12-auditability-safety--compliance-guarantees)
13. [Edge Cases & How They Are Handled](#13-edge-cases--how-they-are-handled)
14. [How This Fits the Existing OrgOS Codebase](#14-how-this-fits-the-existing-orgos-codebase)
15. [Rollout Plan](#15-rollout-plan)
16. [Glossary](#16-glossary)

---

## 1. The Problem in Plain Terms

Every controlled document at Dragnet — like the 3CX Procedure — repeats the same set of *control facts* in several places:

- **Document code** (`DRG-CAE-PRO-3CX-01-26`)
- **Revision number** (`03`)
- **Issue number** (`04`)
- **Date** (`March 2026`)
- **Approving authority** (`Arek Bawa`)
- **Classification** (`Internal use only`)
- **Title** (`3CX Procedure`)
- **Document type** (`Procedure`)
- Plus the **revision history table**, which lists every past revision.

Right now, a human types these values into the document by hand, in **every place they appear**:

- on the **cover page** (the "Document Control No" line, the Serial/Revision/Issue boxes, "Approved By", "Date"),
- in the **header strip** that shows on all pages,
- and as a new row in the **revision history table** every time the document changes.

When any one of these facts changes — a scheduled review bumps the revision, a new approver signs off, the review date rolls over — the officer must find and correct **every** occurrence. Miss one, and the cover says Rev 03 while the header says Rev 02. That inconsistency is exactly the kind of thing an ISO 9001 / ISO 27001 auditor flags as a document-control nonconformity.

**The goal:** an officer changes a control fact **once, in one place in OrgOS**, and it propagates to every location in the document automatically — with no manual editing, and no AI guesswork.

---

## 2. The Core Insight That Changes Everything

The first instinct is: "the version number appears on all 15 pages, so this is a big find-and-replace problem across the whole document." **That is false, and understanding why makes the whole solution simple.**

A Word document does **not** store the header 15 times. A repeating page header is stored **exactly once**, inside the document's section definition, and Word simply *paints* it onto every page when it renders. The "it's on every page" experience is a display effect, not a storage fact.

So in the actual `.docx` file, every controlled fact lives in only **three discrete locations**:

| # | Location | Stored how | Appears where |
|---|----------|-----------|---------------|
| 1 | **Cover page** | Once, in the body | Page 1 only |
| 2 | **Header strip** | Once, in the section header | Repeated visually on all pages |
| 3 | **Revision history table** | Once, in the body (page 2) | Page 2 only, but *grows* over time |

That means we are not solving a "scattered across 15 pages" problem. We are filling **three slots** — one of which is a list that grows by one row per revision. This is small, predictable, and fully mechanical.

---

## 3. Why NOT AI — and Where AI Still Belongs

The officer's concern was correct: **AI must not be in the substitution path.** Here is the reasoning, stated precisely so it survives future "why don't we just use the LLM for this?" conversations.

Filling a version number into a document is a **data-binding operation**, not a reasoning task:

- There is **exactly one correct answer** every time (the value stored in the register).
- The operation must be **100% reproducible** — the same inputs must always produce byte-identical outputs.
- The operation must be **auditable** — we must be able to prove, later, which value went where.
- A wrong value is **not a cosmetic bug** — it is a compliance finding.

A language model is non-deterministic, occasionally hallucinates, and cannot offer a proof of correctness. Using it to write "Revision 03" into a controlled document would inject risk for zero benefit.

**This is already the philosophy of your own codebase.** The CDI checker (`agents/cdi_checker/service.py`) states it explicitly in its comments:

> *"determinism is the floor, so a hallucinating model cannot fail a compliant document"*

and the AI in that module is only ever allowed to flip a deterministic **FAIL → PASS** (a second opinion), never to author or to fail a value. We apply the identical principle here: **the merge is deterministic; AI never touches it.**

**Where AI still earns its place (unchanged):**

- **CDI language checks** (CDI-06/07/08/16) — semantic judgement about vague roles, aspirational language, etc. That is genuine reasoning and stays with the model.
- **Extraction** (`agents/extractor`) — pulling controls/evidence out of prose.
- **Optionally**, as a *convenience only* during one-time legacy migration, to *suggest* where metadata sits in a messy old file — but even there, a human confirms and the deterministic locator is preferred. It is never on the critical path.

---

## 4. The Central Design: Source vs Published

This is the heart of the whole system. **Every controlled document exists in two forms.**

### 4.1 The Source Document (the "master with holes")

A `.docx` that looks exactly like the finished document — same cover, same header, same body, same revision-history table — **except** that in the three controlled zones, the literal control facts are replaced by **markers** (placeholders). For example, instead of the header cell reading:

```
Revision: 03   Issue: 04   Date: March 2026
```

the source reads:

```
Revision: {{ revision }}   Issue: {{ issue }}   Date: {{ issue_date }}
```

Everything else — the entire body: Purpose, Scope, Roles, Access Control, Call Transfer, the Appendix, all of it — is **ordinary typed text** authored by the officer, and it stays exactly as written.

**The source is the permanent artifact.** It is what officers edit when *content* changes. It always keeps its markers, forever.

### 4.2 The Published Document (the clean copy)

Produced by the **merge step**: take the source, look up the current control facts from the register, and swap every marker for its real value. The output is a clean, normal document — no markers, "Revision 03" spelled out properly in all three zones — identical in appearance to what you have today.

**The published copy is disposable.** Nobody ever hand-edits it. If it is lost, damaged, or a value changes, you regenerate it from the source in seconds.

### 4.3 Why two forms and not one

The reason is simple and important: **once a marker is filled in, it is gone.** After the merge, the published document contains "Revision 03" as plain text — there is no `{{ revision }}` left to update next time. So:

- The **marked-up source** is what you save and re-use, because it is the only form that can be re-rendered.
- The **clean published copy** is the always-regenerable output.

This is exactly like source code vs a compiled program: you keep the source, you rebuild the binary whenever you need it, and you never patch the binary by hand.

```
   REGISTER (single source of truth for control facts)
        │  revision = 03, issue = 04, date = "March 2026",
        │  approver = "Arek Bawa", classification = "Internal use only", ...
        ▼
  ┌──────────────┐        merge         ┌───────────────────┐
  │    SOURCE    │  ───────────────────▶│    PUBLISHED      │
  │ (.docx with  │   (fill the holes    │ (clean .docx/PDF, │
  │   markers +  │    from register)    │  no markers, all  │
  │   body text) │                      │  zones consistent)│
  └──────────────┘                      └───────────────────┘
     edited by                              read/distributed;
     officers                               never hand-edited
```

---

## 5. The Merge Engine — How Substitution Actually Works

The merge is a mechanical "fill the holes" operation. Conceptually:

1. Load the source `.docx`.
2. Read the document's control facts from the Document Register (by document code).
3. For each marker in the three controlled zones, replace it with the corresponding value.
4. For the revision-history table, repeat one row per history entry.
5. Save the result as the published document.

### 5.1 The technical trap this must avoid

There is one well-known pitfall that any naive implementation hits. When you type `{{ revision }}` into Word, Word frequently splits that text internally into several fragments ("runs") because of spell-check, formatting boundaries, or where your cursor was. A crude "search the text for `{{ revision }}` and replace it" **silently fails**, because the string is not stored contiguously.

The correct approach uses a templating library built specifically for Word that understands this run-splitting problem and stitches markers back together before substituting — and that can reach **inside headers, footers, and table cells**, not just body paragraphs. (In the Python ecosystem this is the well-established `docxtpl` / *python-docx-template* library, which layers Jinja2 templating over `python-docx`.) This matters because two of our three zones are **inside tables and headers**, precisely where naive replacement tools fail.

We are **not** rolling our own find-and-replace. That is the single biggest avoidable mistake here.

### 5.2 Marker syntax (the standard)

- **Simple value:** `{{ field_name }}` — e.g. `{{ doc_code }}`, `{{ revision }}`, `{{ issue }}`, `{{ issue_date }}`, `{{ approved_by }}`, `{{ classification }}`, `{{ title }}`, `{{ doc_type }}`.
- **Repeating table row (revision history):** a row-loop marker that says "draw this row once per history entry". **Authoring rule (verified against docxtpl):** the `{%tr for %}` and `{%tr endfor %}` tags each **consume the entire table row they sit in**, so they must be placed on their **own separate control rows** — one immediately *above* the data row and one immediately *below* it — **not** inline inside the data row. Layout in the Word table:

  | Row | Cell contents |
  |-----|---------------|
  | Header row | `Rev` · `Date` · `Issue` · `Purpose` · `Authority` (fixed labels) |
  | **Control row** | `{%tr for r in revision_history %}` (in the first cell; rest empty) |
  | **Data row** (repeats) | `{{ r.revision }}` · `{{ r.date }}` · `{{ r.issue }}` · `{{ r.purpose }}` · `{{ r.authority }}` |
  | **Control row** | `{%tr endfor %}` (in the first cell; rest empty) |

  At merge time the two control rows disappear and the data row repeats once per history entry — four entries → four rows, five next year → five rows, automatically. **Do not** write `{%tr for%}…{%tr endfor%}` inside the data row itself; docxtpl will delete that whole row and the loop breaks. (This corrects the earlier inline sketch — proven wrong by spike; see the implementation plan.)

- **Optional value with a fallback:** `{{ next_review_date or "—" }}` so a blank field never leaves a stray marker in the output.

### 5.3 What the merge guarantees

Because the cover, the header, and every relevant cell all reference **the same variable** (`{{ revision }}`), it is **structurally impossible** for them to disagree. The officer sets the revision once, in one field; the three zones cannot fall out of sync because they are literally reading the same number.

---

## 6. The Standard — What "A Standard Document" Means

For the merge to work, all documents **of a given type** must follow **one master template**. This is the "standard document that all documents of this type must follow" the officer described. It is both a requirement and the goal.

### 6.1 One master template per document type

There is one master template per controlled document type:

- Procedure (`PRO`)
- Policy (`POL`)
- SOP (`SOP`)
- Form (`FRM`)
- Guidelines / Manual / Framework / Handbook — as needed

Each master template is a `.docx` stored in a dedicated **`Templates/`** folder inside the ORGOS LIBRARY (alongside the existing `compliance_starting_folder`). Each master defines:

- The **cover page layout** (with markers in the control fields).
- The **header strip table** (with markers), stored once in the section header.
- The **revision-history table** (with the repeating-row marker).
- The **fixed boilerplate**: the confidentiality footer, the standard section skeleton (1.0 Purpose, 2.0 Scope, 3.0 Roles & Responsibilities, …), page geometry, fonts, and Dragnet branding.

### 6.2 What is fixed vs what officers fill

| Part of the document | Fixed by the template | Filled by officer | Filled by the register (merge) |
|---|---|---|---|
| Page size, margins, fonts, branding | ✅ | | |
| Cover layout & labels | ✅ | | |
| Header strip layout | ✅ | | |
| Revision-history table structure | ✅ | | |
| Confidentiality footer text | ✅ | | |
| Document code, revision, issue, dates, approver, classification, title, type | | | ✅ |
| Revision-history *rows* | | | ✅ |
| Body content (Purpose, Scope, Procedures, Appendices…) | skeleton only | ✅ | |

This table is the contract. If everyone respects it, the system is airtight.

### 6.3 The deal you are signing up for

The honest trade-off: **consistency is mandatory.** Two documents of the same type must have the same cover, header, and revision-history structure. This is what makes the merge trivial *and* what makes the CDI structural checks pass by construction (revision history present, classification present, code format valid, etc. — all guaranteed because the template guarantees them). The cost is that non-conforming legacy documents must be reconciled to the standard once (see §10).

---

## 7. The Three Controlled Zones (and the Markers in Each)

This section is the concrete specification of exactly where markers go. These three zones — and **only** these three — contain markers. The body never does.

### 7.1 Zone 1 — The Cover Page

Using the 3CX cover as the reference, the control fields become:

```
DOCUMENT CONTROL NO: {{ doc_code }}

┌────────────────┬──────────────────┬────────────────────────┐
│ COMPANY CODE   │ DOCUMENT TYPE    │ DISTRIBUTION           │
│ DRG            │ {{ doc_type }}   │ {{ distribution }}     │
├────────────────┼──────────────────┼────────────────────────┤
│ SERIAL NUMBER  │ REVISION NUMBER  │ ISSUE NUMBER           │
│ {{ serial }}   │ {{ revision }}   │ {{ issue }}            │
├────────────────┴──────────────────┴────────────────────────┤
│ APPROVED BY: {{ approved_by }}                              │
├─────────────────────────────────────────────────────────────┤
│ DATE: {{ issue_date }}                                      │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Zone 2 — The Header Strip (stored once, shown on every page)

```
┌──────────┬───────────────────────────┬────────────────────────────────────────┐
│  [logo]  │ Document Type: {{ doc_type }}    │ Classification: {{ classification }}   │
│          ├───────────────────────────┼────────────────────────────────────────┤
│          │ Document Title: {{ title }}       │ Document Code: {{ doc_code }}          │
│          │                           ├───────────────┬───────────┬────────────┤
│          │                           │ Revision:{{revision}}│ Issue:{{issue}}│ Date:{{issue_date}}│
└──────────┴───────────────────────────┴───────────────┴───────────┴────────────┘
```

Because this lives in the section header, marking it once makes every page consistent.

### 7.3 Zone 3 — The Revision History Table (grows over time)

The header row is fixed boilerplate. The data rows are a single repeating-row marker:

```
┌────────────┬──────────────┬────────────┬───────────────────────────┬──────────────────────┐
│ REVISION   │ DATE OF      │ ISSUE      │ ISSUE/REVISION PURPOSE     │ APPROVING AUTHORITY  │
│ NUMBER     │ REVISION     │ NUMBER     │                            │                      │
├────────────┼──────────────┼────────────┼───────────────────────────┼──────────────────────┤
│ {%tr for r in revision_history %}                                                          │
│ {{r.revision}} │ {{r.date}} │ {{r.issue}} │ {{r.purpose}}            │ {{r.authority}}      │
│ {%tr endfor %}                                                                             │
└────────────┴──────────────┴────────────┴───────────────────────────┴──────────────────────┘
```

For the 3CX example, the register's `revision_history` list would hold four entries, producing the four rows exactly as in the current document; the next revision adds a fifth entry and a fifth row appears automatically.

---

## 8. The Data Model — What the Register Must Store

The Document Register becomes the **single source of truth** for control facts. Your current `DocumentBase` already has: document code, title, type, department, current version, effective date, next review date, applicable standards, status. To drive the template, add the following.

### 8.1 New scalar fields

| Field | Example | Notes |
|---|---|---|
| `revision_number` | `03` | The 3CX doc tracks revision **and** issue separately — both are needed. |
| `issue_number` | `04` | |
| `serial_number` | `01` | The "Serial Number" box on the cover. |
| `classification` | `Internal use only` | Feeds Zone 1 and Zone 2. |
| `approved_by` | `Arek Bawa` | Approving authority (name, or a Role Register reference). |
| `issue_date` | `March 2026` | The cover/header "Date". |
| `distribution` | `Candidate Experience` | The cover "Distribution" cell. |

### 8.2 The revision history (a small list per document)

Each entry: `{ revision, date, issue, purpose, authority }`.

Because OrgOS has **no relational database** (SharePoint Lists only), there are two viable storage shapes:

- **Option A — a JSON text column** on the Document Register item holding the list. Lowest friction; one read gives you the whole history. Recommended unless the history must itself be independently queried/reported.
- **Option B — a dedicated "Document Revision History" list**, one row per revision, keyed by `document_code`. More work, but each revision is a first-class item (filterable, reportable). Consistent with the "everything is a SharePoint list" pattern.

### 8.3 Derived / computed fields (never typed by a human)

- `next_review_date` = `effective_date` + review cycle (e.g. 12 months). Computed, matching the existing pattern of stateless status calculations in `grc/service.py`.
- The revision-history row for a new revision is **generated** by the "Issue new revision" action (see §11), not typed.

---

## 9. New Documents — The Full Workflow

For any document created **after** this system is in place, the flow is straightforward because the markers are already present in the master template.

1. **Create the register entry.** An officer (or the AI Policy Drafter) creates a Document Register item. The system generates the document code `DRG-[DEPT]-[TYPE]-[REF]-[YY]` and sets the initial control facts: `revision_number = 00` (or `01` per your convention), `issue_number = 01`, `serial_number`, `classification`, `issue_date`, `effective_date`, computed `next_review_date`, and a first revision-history entry (e.g. "00 | <date> | 01 | Issued for Compliance Team's review | <authority>").

2. **Start from the master template.** The system copies the correct master template for the document type into the document's **source** location. This source already contains all markers in the three zones and the empty section skeleton in the body.

3. **Officer authors the body.** The officer writes the actual content (Purpose, Scope, Procedures, etc.) directly into the body of the source. **They never touch the metadata zones** — those still hold markers.

4. **Merge to publish.** When ready, the system runs the merge: source + register values → published document. The published copy has every control fact filled and consistent across all three zones.

5. **(Optional) CDI check.** The published document can be run through the existing CDI checker to confirm structural and language compliance before distribution.

6. **Distribute.** The published copy (as `.docx` and/or a locked PDF) is the controlled copy people read.

From this point on, the officer's job for metadata is **only** to change fields in OrgOS — never to edit the document's version/date/approver by hand.

---

## 10. Existing Documents — The Migration Workflow

> **Critical reality: the existing library is PDF-only.** Every current document (including the 3CX Procedure) exists **only as a PDF** — there are no editable Word `.docx` originals. This section is written for that reality. It is the single most important constraint on migration, and it changes the approach from "convert a Word file" to "rebuild into the template."

### 10.1 Why a PDF cannot be templated directly

Recall the two forms of a document (§4):

- A **source** must be an editable Word `.docx`, because markers (`{{ revision }}`) can only be placed into an editable file and re-rendered.
- A **published** copy is the frozen output people read — **and a PDF is exactly this frozen form.**

So each existing PDF is a *published* artifact whose editable *source* has been lost (or never kept). You cannot put markers into a PDF, and therefore you cannot drive the merge engine from a PDF. A PDF has to be rebuilt into a templated `.docx` source before it can join the system.

### 10.2 Why automated PDF → Word conversion is NOT the answer

Tools exist that claim to turn a PDF back into Word (Adobe, Word's "open PDF", LibreOffice). **Do not rely on them for these documents.** For a structured controlled document — cover control table, repeating header strip, revision-history table, the flowchart image, the appendix tables — PDF→Word conversion reliably produces a mangled result:

- Tables break apart into loose text or misaligned cells.
- The repeating header/footer collapses into the body as stray paragraphs.
- Bullet levels, numbering, and spacing scramble.
- Images (e.g. the page-12 flowchart) are dropped or rasterised.

You would spend **more** time repairing a bad conversion than rebuilding cleanly. Automated conversion is therefore out. Migration is a deliberate, one-time **rebuild**, not a conversion.

### 10.3 The reframing that makes this manageable

Rebuilding sounds heavy, but two facts shrink the work dramatically:

1. **You must build the master template anyway** (§6) — that is the standard, and it is unavoidable regardless of migration. Once it exists, it already carries the cover, header, revision-history table, markers, and section skeleton.
2. **Metadata does not go into the document body — it goes into the register** (§8). So migrating a PDF is *not* about reproducing its cover/header by hand. Those are the template's job. Migration is only about **getting the body content into the template** and **the control facts into the register.**

So each document splits into two independent parts, below.

### 10.4 Part A — The metadata (fast, and partly automatable)

Read the control facts off the PDF's cover and header — document code, revision, issue, serial, date, approver, classification, title, type — plus every row of the revision-history table, and enter them into the Document Register (§8). This is a few minutes per document.

It can be **pre-filled** rather than typed: OrgOS already extracts text from PDFs (the CDI checker uses `pypdf` / the extractor path). A migration screen can auto-extract these values and present them for the officer to **confirm or correct**. The officer verifies against the PDF; the values are never trusted blindly. No AI is required for this — the fields sit in structurally predictable places on the cover/header.

### 10.5 Part B — The body content (the real one-time work)

Move the actual procedure text (Purpose, Scope, Roles, all numbered steps, the appendix) into the **body** of the master template. Because the template already owns the three metadata zones, **only the body is touched.**

To reduce effort:

- **Auto-extract the raw body text** from the PDF (existing tooling) so it does not have to be retyped.
- A person then **reformats** it inside the template — restoring bullet levels, numbering, tables, and re-inserting images such as the page-12 flowchart — and **verifies it word-for-word against the original PDF.**

This word-for-word check is mandatory and non-negotiable: the body *is* the compliance content. A procedure step that changes wording during migration is a real defect, so the reformatted body must match the source PDF exactly (only layout is normalised, never meaning).

### 10.6 Where AI may and may not help in migration

Consistent with §3 (determinism is the floor):

- **Metadata (Part A):** no AI. Deterministic extraction + human confirmation.
- **Body reflow (Part B):** AI *may* assist by drafting the extracted text into the template's section structure — but its output is treated strictly as a **draft that a human verifies against the source PDF, word for word.** AI must never be allowed to silently reword a control statement or a procedure step. If there is any doubt, the raw extracted text is placed manually.
- **The merge itself:** never AI, ever.

### 10.7 The per-document migration steps (PDF-only)

1. **Auto-extract** text from the PDF (metadata candidates + raw body text).
2. **Confirm the control facts** and enter them into the register, including the full `revision_history` list read from the PDF's revision-history table.
3. **Rebuild the body** inside a copy of the master template: paste/reflow the body text, restore tables/bullets/images, and check word-for-word against the PDF. The metadata zones stay as markers.
4. **Save this as the source** (`.docx` with markers + rebuilt body) in the working/sources area.
5. **Merge once and eyeball** the published output against the original PDF — cover, header, body, and revision-history table should read identically (metadata now coming from the register).
6. **Publish** the new controlled PDF; retire the old hand-maintained PDF as a historical artifact.

From step 6 on, the document is fully system-managed: future revisions and dates propagate automatically (§11), and it never needs a manual rebuild again.

### 10.8 Pace the migration — do NOT do it all at once

Because migration is one-time manual work sized to the library, prioritise it rather than attempting a big-bang cleanup:

- **Migrate eagerly** the documents that are **active and revised often** — the ones causing the manual-update pain today. They repay the effort immediately.
- **Migrate lazily** the **rarely-touched** documents: leave the existing PDF in place and rebuild into the template **the next time that document is due for revision anyway.** The revision effort you would spend regardless becomes the migration effort — nothing is wasted.

New documents (§9) are unaffected: every document created after go-live is born as a proper templated source, so the PDF-only problem never recurs — it applies strictly to the existing back-catalogue.

### 10.9 Honest bottom line

PDF-only means migration is a **manual rebuild into the template, not an automatic conversion.** But it is one-time per document, the metadata step is quick and assisted, the body text can be auto-extracted to avoid retyping, and the whole effort can be paced (active docs first, the rest on their next revision). Crucially, **it does not block building the system** — the merge engine, the register fields, and the new-document flow can all be built and used immediately; the back-catalogue is migrated alongside, at whatever pace suits the team.

---

## 11. The "Issue New Revision" Bookkeeping

This is the workflow that eliminates manual metadata editing entirely. Example: the 3CX Procedure is due for scheduled review and moves from Rev 03 / Issue 04 to Rev 04 / Issue 05.

1. The officer opens the document in OrgOS and clicks **"Issue new revision"** (providing the revision purpose, e.g. "Issued for use", and confirming the approving authority).
2. The system performs the bookkeeping automatically:
   - `revision_number` → `04`
   - `issue_number` → `05`
   - `issue_date` → the new date
   - `effective_date` → set; `next_review_date` → recomputed (effective + cycle)
   - **Appends** a new `revision_history` entry: `{ revision: "04", date: <new date>, issue: "05", purpose: "Issued for use", authority: "Arek Bawa" }`
3. The system **re-runs the merge** on the (unchanged) source.
4. Out comes a fully consistent published document: cover, header on all pages, and the revision-history table (now with five rows) **all** showing Rev 04 / Issue 05 — because they all read the same values.

The officer set the revision **once** (implicitly, by clicking the action). Nothing was typed into the document. Nothing can be inconsistent.

If instead the **content** changes (a new offboarding step), the officer edits the **body of the source**, leaves the markers alone, and re-merges — the metadata stays correct without anyone touching it.

---

## 12. Auditability, Safety & Compliance Guarantees

- **Single source of truth.** Control facts live in the register; the document is a *rendering* of them. There is one authoritative value for "the revision of this document", and every occurrence in the file derives from it.
- **Structural consistency guarantee.** Cover, header, and history cannot disagree because they reference the same variables during merge.
- **Full determinism.** Same source + same register values → byte-identical published document, every time. No model, no randomness.
- **Merge audit trail.** Every merge can be logged (who triggered it, when, the exact field values used, the resulting file URL) into the existing Audit Log list — giving an auditor a provable record of what was published and from what.
- **Revision history is data, not prose.** Because history entries live in the register, the revision log becomes queryable and reportable, not just a table buried in a Word file.
- **Immutable published copies.** Publishing as a **locked PDF** (rendered from the merged `.docx`) prevents anyone from hand-editing the controlled copy; the editable `.docx` source stays in the working area. (This is a distribution-format choice, noted here as the compliance-preferred option.)
- **Consistent with existing philosophy.** The determinism-is-the-floor stance mirrors the CDI checker, so this system does not introduce a new, conflicting mental model.

---

## 13. Edge Cases & How They Are Handled

| Edge case | Handling |
|---|---|
| **A marker is left in the output** (typo in a field name) | Fail loud: the merge validates that every marker resolved; an unresolved marker blocks publishing and is reported. Optionally provide `{{ field or "—" }}` fallbacks for genuinely optional fields. |
| **Word split the marker across runs** | Handled by using a proper Word-aware templating library (§5.1), never naive string replace. |
| **Multiple sections** (a document with different first-page vs later-page headers) | Each section header is templated independently; the master template defines them. Most Dragnet docs use a single repeating header. |
| **Legacy PDF has no revision-history table** | The template supplies the table; whatever history the PDF records is entered into the register during migration (§10.4). If the PDF has no history at all, seed a single entry for its current revision. |
| **Legacy library is PDF-only (no `.docx` originals)** | This is the actual situation. Migration is a one-time **rebuild into the template**, not an automatic conversion — see §10 in full. Automated PDF→Word conversion is explicitly rejected (§10.2). |
| **PDF body text extracts messily** (broken tables, dropped images) | Expected. Auto-extraction gives raw text only; a human reformats inside the template and verifies word-for-word against the PDF (§10.5). |
| **Distribution cell / department-specific labels differ** | Modelled as register fields (`distribution`, `department`) rather than hardcoded, so the same template serves all departments of a type. |
| **Someone hand-edits a published copy** | Discouraged by locked-PDF distribution; and because the published copy is regenerable, any drift is corrected by re-merging from the source. |
| **Two documents share a code** | The document code is the merge key; the register enforces uniqueness (already the pattern in `grc/`). |

---

## 14. How This Fits the Existing OrgOS Codebase

- **`agents/policy_drafter/docx_builder.py`** already generates `.docx` programmatically with `python-docx` and Dragnet branding. The merge engine is a **sibling** capability (template + fill) rather than a replacement — the drafter *creates* content; the merge engine *stamps controlled metadata*. They can share the branding helpers.
- **`agents/cdi_checker/service.py`** already extracts text from **PDFs** (via `pypdf`) as well as `.docx` (via `mammoth`), and states the determinism-floor philosophy. Since the legacy library is PDF-only (§10), migration reuses the **PDF** extraction path to pre-fill metadata candidates and raw body text for human confirmation. The philosophy is carried over verbatim.
- **`grc/` (Document Register)** gains the new fields (§8) following existing Pydantic v2 + SharePoint-column-mapping conventions (`grc/schemas.py`, `grc/constants.py`, `grc/service.py`). `next_review_date` computation follows the existing stateless-status pattern.
- **SharePoint** stays the single store: master templates in a `Templates/` folder in the ORGOS LIBRARY; sources in a working area; published copies in the distribution area — all via the existing `graph/client.py` file operations.
- **Audit Log list** receives merge events, consistent with the existing soft-delete/audit conventions.
- **No new database**, no new external service, no cloud LLM added. The only new dependency is a Word-aware templating library for the merge (§5.1).

---

## 15. Rollout Plan

A phased path that delivers value early and keeps risk contained:

1. **Phase 0 — Standard definition.** Finalise the master template for **one** type (Procedure), including the exact three-zone marker layout. Agree the register field additions (§8).
2. **Phase 1 — Merge engine.** Implement source → published merge with the Word-aware library, marker validation (fail-loud on unresolved markers), and the repeating revision-history row. Prove it on a hand-made Procedure source.
3. **Phase 2 — Register wiring.** Add the new fields, the `next_review_date` computation, and the "Issue new revision" action with automatic history-row append.
4. **Phase 3 — New-document flow.** Wire "create from master template" so new Procedures are born as templated sources.
5. **Phase 4 — Legacy migration tooling (PDF-only).** Build the migration screen: auto-extract metadata + raw body text from a PDF (existing `pypdf` path), let an officer confirm the control facts into the register, and provide a rebuild-into-template workflow with a word-for-word check against the source PDF (§10). Prove it on the 3CX Procedure as the reference case. There is **no** automatic PDF→Word converter (§10.2) — this phase builds *assistance* for a human rebuild, not an unattended conversion.
6. **Phase 5 — Paced back-catalogue migration.** Migrate active/high-churn documents eagerly; leave rarely-touched ones to be rebuilt on their next scheduled revision (§10.8). No big-bang.
7. **Phase 6 — Expand types.** Repeat the master-template definition for Policy, SOP, and the rest.
8. **Phase 7 — Distribution hardening.** Add locked-PDF output and merge-event audit logging.

Each phase is independently useful; nothing forces a big-bang cutover. Note that Phases 0–3 deliver a fully working system for **new** documents — the PDF-only migration (Phases 4–5) runs alongside and never blocks it.

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **Control fact / controlled metadata** | A governed field that must be consistent everywhere: document code, revision, issue, serial, dates, approver, classification, title, type. |
| **Marker / placeholder** | A `{{ field }}` token in a source document that the merge replaces with a register value. |
| **Source document** | The permanent `.docx` that keeps its markers plus the authored body; what officers edit. |
| **Published document** | The clean, regenerable output of the merge; what is distributed; never hand-edited. |
| **Merge** | The deterministic operation that fills a source's markers from the register to produce the published document. |
| **Master template** | The one standard `.docx` per document type, defining layout, boilerplate, and the three marker zones. |
| **Three controlled zones** | Cover page, header strip, revision-history table — the only places markers appear. |
| **Migration / conversion** | The one-time process of turning a legacy hardcoded document into a templated source. |
| **Issue new revision** | The OrgOS action that bumps revision/issue/dates and appends a history row automatically, then re-merges. |

---

*End of design specification. No code is included by design — this document defines the standard and the mechanism so implementation can proceed against an agreed contract.*
