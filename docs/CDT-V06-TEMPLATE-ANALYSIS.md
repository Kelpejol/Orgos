# CDT & the v06 Cover Template — What the DOCX Library Changes

*Working analysis for Paul, and the basis for the questions to put to the compliance officer.
Every number below was measured against the live ORGOS LIBRARY, not assumed.*

---

## 1. What is actually in the library right now

Two sibling folders in `/sites/everybody/ORGOS LIBRARY/`:

| Folder | Contents |
|---|---|
| `Policies, Procedures, Manuals, Guidelines, Frameworks, Handbook, SOP` | **121 PDF** (the old set) |
| `OrgOs Library` | **121 DOCX** (the new set) |

Same 121 documents, re-provisioned in Word. Flat — no subfolders.

**But the DOCX set is not uniform.** I parsed all 121 and classified them by cover page:

| Cover format | Count | What it looks like |
|---|---|---|
| **NEW (v06)** — matches the template PDF | **9** | 15-row, 2-column table: Document Title → ISO 27001:2022 |
| **OLD (3CX-style)** | **92** | 3-column grid: COMPANY CODE / SERIAL / REVISION / ISSUE |
| **OTHER** — no recognisable control table | **20** | Handbooks, checklists, forms, frameworks |

So the new template rollout is **9 of 121 (~7%) complete**. The library is mid-migration, not migrated.

---

## 2. The new template, decoded

From `Control of Documented Information Procedure-V6.docx` — the reference implementation:

**Cover control table** (2 columns, 15 rows):

| Field | Example value |
|---|---|
| Document Title | Control of Documented Information Procedure |
| Document Code | `DRG-QI-PRO-CDI` |
| Document Type / Layer | Procedure (Layer 4) |
| Domain | Quality & Compliance |
| Parent Document | Control of Documented Information Policy (Layer 3) |
| Classification | Internal use only |
| Distribution | All staff |
| Owner | Compliance Senior Executive |
| First Pass Approval | Compliance Senior Executive |
| Final Approval | Chief Compliance Officer |
| Version | 06 |
| Effective Date | August 2026 |
| Next Review Due | August 2027 |
| ISO 9001:2015 | Clause 7.5 |
| ISO 27001:2022 | Clause 7.5 |

**Revision history** (4 columns): `Version | Date | Purpose of Change | Approved By`

**Header: empty. Footer:** `Property of Dragnet Solutions — internal use only.` + `Page N of M`

### Old → new field mapping

| Old CDT model | New template | Change |
|---|---|---|
| `doc_code`, `doc_type`, `title`, `classification`, `distribution` | same | ✅ survive |
| `serial` | — | ❌ **gone** (was part of the old code format) |
| `revision` + `issue` | **Version** | ⚠️ **two fields collapse into one** |
| `approved_by` | **First Pass Approval** + **Final Approval** | ⚠️ **one field splits into two** |
| `issue_date` | **Effective Date** | ⚠️ renamed, and now paired with **Next Review Due** |
| — | **Domain**, **Parent Document**, **Owner**, **ISO 9001**, **ISO 27001** | ➕ **five new fields** |

Revision-history row: `{revision, date, issue, purpose, authority}` → `{version, date, purpose, approved_by}`.

---

## 3. What the DOCX library closes out

**a) It kills the hardest chapter of the CDT design.** §10 of `DOCUMENT-TEMPLATING-DESIGN.md` is a long argument that PDFs cannot be templated and every legacy document needs a manual Word rebuild. That chapter is now **largely obsolete** — the Word originals exist. This was the single biggest cost in the plan.

**b) It switches on the machinery already built and shipped.** CDI auto-fix and the feedback-amendment engine are `.docx`-only by design — on a PDF library they were guidance-only. Against this library they can actually apply fixes.

**c) Zone 2 disappears.** The old design had three marker zones, one of them a per-page header strip repeating code/revision/issue on every page. **Verified: the new documents have an empty header** and only a plain footer. CDT drops from three zones to two, both on the cover, both in one section. That is a real simplification — no header/footer marking, no cross-section consistency problem.

**d) Version replaces Revision + Issue.** One number instead of two that had to be kept in step.

**e) Two-step approval becomes explicit** (First Pass → Final), matching the v06 domain-based approval model.

---

## 4. What it breaks — and one hard blocker

### 🔴 Blocker: the document code format

The new code is `DRG-QI-PRO-CDI` — `DRG-[FUNCTION]-[TYPE]-[ID]`, no `-01-26` suffix (CDI v06 §4.0). Measured against our current validator:

```
DRG-QI-PRO-CDI          → INVALID
DRG-QI-PRO-CDI-01-26    → valid
```

**All 9 new-template documents fail validation today.** That is not cosmetic — `is_valid_doc_code()` gates **CDI-01, the approval step, and publishing to the register**. Every document authored to the new standard is blocked end-to-end.

I measured the whole library's codes:

| Shape | Count | Example | Status |
|---|---|---|---|
| 4 segments (new canonical) | 9 | `DRG-QI-PRO-CDI` | ❌ fails |
| 5 segments (SOP, no mnemonic) | 4 | `DRG-CLE-SOP-01-25` | ❌ fails |
| 6 segments (old standard) | 91 | `DRG-CAE-PRO-3CX-01-26` | ✅ 78 pass |
| 6 segments (**combined POL-PRO**) | 10 | `DRG-QI-POL-PRO-NCA-01` | ❌ fails |
| No code found in body | 17 | — | ❌ |

**23 codes fail in total.**

> **Correction to something I shipped earlier.** The combined-document fix I added assumed combined codes looked like `DRG-QI-POL-PRO-CDI-01-26` (trailing `-NN-YY`). The real ones are `DRG-QI-POL-PRO-NCA-01` — a **single** trailing serial. My `COMBINED_DOC_CODE_PATTERN` does not match them, so **the Nonconformity & Corrective Action document is still failing**. That fix needs redoing against the real shape.

The validator must accept, side by side:
- new canonical 4-segment,
- combined `POL-PRO` with a single serial,
- legacy 6-segment (the v06 glossary explicitly defines *"Legacy Document — any controlled document carrying a retired code"*, so the standard itself expects both to coexist).

### Other breaks

- **CDT data model is wrong.** `MergeContext` (serial/revision/issue/approved_by/issue_date) no longer matches. Same for the uncommitted `grc/schemas.py` register fields and the `RevisionNumber`/`IssueNumber`/`SerialNumber` SharePoint columns — those columns would be created for a model that is already superseded. **Good thing they were never provisioned.**
- **The AI drafter emits a third, non-conforming cover.** `docx_builder.py` produces a 6-row table (Document Code / Document Type / Department / Version / Status / Date), a revision history of `Version | Date | Author | Change`, and a *trailing* "Review and Approval" table. That is neither the old nor the new standard. It must be rewritten to emit the 15-row cover, the 4-column history, and the footer — and drop the trailing approval table, which the cover now covers.
- **Intake points at the PDF folder.** 14 code sites read `settings.compliance_starting_folder`; all resolve through settings, so **one env change** (`COMPLIANCE_STARTING_FOLDER=OrgOs Library`) redirects the lot.

---

## 5. The cover-page / page-growth question

> *"…maybe 2 pages of words and one empty for the growth of the revision table…"*

**Do not reserve a blank page.** In Word a table grows and the document repaginates itself; a reserved page would simply render as an unwanted blank page once the table outgrows it, and the blank would persist when it doesn't.

The correct structure:

```
[cover section]  logo + title block
                 15-row control table
                 REVISION HISTORY  ← grows downward, repaginates automatically
[page/section break]
[body]           1.0 Purpose & Scope …
```

An explicit **page (or section) break** after the revision history guarantees the body always starts on a fresh page no matter how many revision rows accumulate. That is exactly what the `{%tr for r in revision_history %}` repeating-row marker already built is for — one row per register entry, unlimited growth, no layout maintenance.

And the user's instinct is right on the second point: **revision history now lives only on the cover**, not repeated per page — confirmed by the empty headers.

---

## 6. Preview as PDF — verified, no new dependency

The plan was always "merge to Word, preview as PDF". We have no PDF converter in the stack (no LibreOffice, no docx2pdf). **Microsoft Graph converts natively.** I tested it against this library:

```
GET /drives/{drive_id}/root:/{path}:/content?format=pdf
→ 200, 382,273 bytes, magic %PDF-   ✅
```

So the preview flow is: merge → upload the merged `.docx` to a working location → request the same item with `?format=pdf` → return the PDF. Register values in, rendered cover out, no extra infrastructure.

---

## 7. Sequenced plan

**Order matters — purging before step 1 recreates the breakage.**

1. **Fix the code validator** to accept new 4-segment, combined single-serial, and legacy forms. *Unblocks CDI-01, approval and publish for all 9 new docs + the 10 combined ones.* ← do this first
2. **Redo the combined-document fix** against the real `-01` shape.
3. **Repoint intake** at `OrgOs Library` (one env var) and confirm the DOCX path end-to-end.
4. **Purge and re-intake** — now safe, and codes land correctly.
5. **Rework the CDT model** to the v06 field set (cover + history), replacing serial/revision/issue.
6. **Provision the register columns** for the *new* field set (not the old one).
7. **Rewrite `docx_builder.py`** so AI-drafted documents are born in the v06 shape.
8. **Wire the merge + PDF preview** into the Document Register.

Steps 1–4 are the unblock. 5–8 are CDT proper.

---

## 8. Questions for the compliance officer — ANSWERED, decisions locked

All eight resolved. Recorded here as the final spec CDT is built against.

1. **Cover template is final.** The officer supplied `Cover_Page_Template 1.pdf` as *the* master to build against. It is the **15-row** cover (Document Title → ISO 27001:2022, `Effective Date`, no `Supersedes` row) — the same shape as the already-issued v06 CDI Procedure, **not** the 16-row "Proposed Issue / Supersedes" variant seen in Bobby's pending draft package. That draft variant is therefore NOT what we build against.
   - New detail from the supplied PDF: the subtitle line under the logo is **dynamic** — `[Domain Name] · [Document Type]` — not a fixed "QIMS" label. It prints the document's actual Domain and Document Type.
2. **Confirmed — no running header/footer content.** Header is blank; footer is fixed boilerplate (`Property of Dragnet Solutions — internal use only.` + page number), never per-document data. **Zone 2 is retired.** CDT is two zones now: the cover, and the revision-history table (both on the same cover page/section).
3. **Confirmed — "Purpose of Change" is canonical.** Use that heading everywhere; the CDI Procedure's plain "Purpose" is not to be followed literally.
4. **Confirmed — every cover field is editable at every revision**, not just some. The officer's answer: "anything can change at any time, especially if the CDI procedure changes." **Build implication:** the Document Register form must let Compliance edit *every* cover field (Domain, Parent Document, Classification, Distribution, Owner, both approvals, the standards list) on every revision — nothing on the cover can be treated as "set once, locked forever."
5. **Answered, and it changes the data model.** Three regulatory bodies today: **ISO 9001:2015, ISO 27001:2022, NDPA** — and the officer confirmed the count can grow further (a new standard version, or a new certification). **Build implication:** the two fixed `iso_9001` / `iso_27001` scalar markers in the original CDT design are wrong. The standards block must become a **repeating row**, exactly like `revision_history` (a `{%tr for %}` loop over a `standards` list on the register), not two hard-coded cells. This is a real, material change to `MergeContext`.
6. **Confirmed — cover-page presence is the inclusion signal.** "Only documents that have and need our cover page would be put in that SharePoint folder." The ~20 documents without a control table (handbooks, checklists, reference forms) are deliberately excluded — they are not controlled documents under CDT and should never be expected to carry a cover.
7. **Migration owner confirmed: Wani (Victoria Shobayo) will convert the remaining ~112 documents herself.** No committed date — "finish it herself," open-ended. **Build implication:** the code-format validator and the "OLD vs NEW cover" detection must keep accepting *both* shapes indefinitely, with no fixed cutover date to plan a hard switch around. Treat legacy-format acceptance as permanent, not a temporary bridge.
8. **Confirmed — "Draft" is a real, deliberate state.** A document sits with `Version: Draft` (no number) until approved, then it takes its first real version number. **Build implication:** the register's version/revision field needs to represent "Draft" as a distinct, valid state — not just an empty string — and the merge/publish step is what turns "Draft" into the first issued number.

---

## 9. Bottom line

The DOCX library is a genuine unlock — it removes the biggest cost in the CDT plan and switches on tooling already built. It arrived **with a new template that changes the CDT data model**, and **with a code format that our validator rejects**, which currently blocks every document authored to the new standard.

With the officer's answers now locked, the model is fully specified: **15-row cover** (final template supplied), **two zones only** (cover + revision history, no header/footer markers), **a growing standards list** (not two fixed ISO cells), **every cover field editable at every revision**, **cover-page presence = in scope for CDT**, **both old and new code/cover formats supported indefinitely** (Wani's migration has no end date), and **"Draft" as an explicit pre-approval version state**.

Fix the code format first, then purge. The rest of CDT should be rebuilt against this now-final v06 field set rather than the 3CX one it was originally designed for.

---

## 10. Build status (2026-09-25) — the v06 rebuild is done, tested, uncommitted

Everything in §7's steps 5–8 (rebuild the register/merge schema, the AI drafter, PDF preview) is now built and tested against the confirmed v06 spec. All of it remains **uncommitted**, alongside the rest of CDT — nothing here has been pushed.

**Schema (`lifecycle/schemas.py`)** — `MergeContext` rebuilt to the final field set: `domain`, `parent_document`, `type_layer`, `owner` (a role/group label — e.g. "Compliance Team" — never a person; distinct from the register's `owner_id`), `first_pass_approval`, `final_approval`, `version` (may literally be `"Draft"`), `effective_date`/`next_review_due` (human-printed), and two repeating lists: `standards` (growing, per answer #5) and `revision_history` (renamed `revision`→`version`, dropped `issue`, `authority`→`approved_by`, per the officer's confirmed header).

**Storage** — `CdtCoverFacts` bundles every cover fact except `doc_code`/`title`/`doc_type` (their own columns already) into **one JSON column**, `CDTCoverFacts`, on both the Document Lifecycle and Document Register lists. This is deliberate: OrgOS cannot create SharePoint columns (confirmed via a live 403 while building OrgOS Groups), so one bundled column beats fourteen an admin would otherwise have to add by hand, on two lists. **Two new columns needed, each list, both "Multiple lines of text": `CDTCoverFacts`, `RevisionHistory`.** Every write is gated on the column actually existing, so nothing breaks before an admin adds them — it just doesn't persist yet.

**Merge engine (`lifecycle/merge.py`)** — generalised to scan *any* list field (not just `revision_history`) for stray marker tokens in values, so `standards` gets the same protection automatically.

**⚠ Template-authoring rule, learned the hard way while rebuilding the test fixtures:** docxtpl's row-repeat (`{%tr for %}` / `{%tr endfor %}`) only works with **three separate rows** — a for-row (tag alone), a data-row (the `{{ }}` markers), and an endfor-row (tag alone). Putting the for-tag and the data markers in the *same* row (which seemed like the obvious way to write it) silently produces **zero** repeated rows — no error, just nothing. Whoever builds the real master `.docx` templates must follow the 3-row pattern exactly (see any of the `_add_loop`/`_build_master` helpers in `tests/lifecycle/test_merge.py` for a worked example).

**Templates (`lifecycle/templates.py`)** — vocabulary/validation updated: required markers are now just `doc_code` + `version` (dropped `revision`/`issue`); known markers include the new `standards` loop. Confirmed "two zones, not three" in the validator's own docstrings.

**Register bridge (`grc/schemas.py`, `grc/constants.py`, `grc/service.py`)** — `DocumentBase.cdt_cover: Optional[CdtCoverFacts]` replaces the old flat revision_number/issue_number/serial_number/approved_by/issue_date/classification/distribution fields. The `document_code` field validator now reuses the *same* `is_valid_doc_code()` as CDI-01/approval/publish, so the register can never silently disagree with the rest of the system on what a valid code is.

**Lifecycle endpoints (`lifecycle/router.py`)** — new: `GET`/`PATCH /documents/{id}/cover` (Compliance or the document owner can edit any cover fact, any time — matches answer #4 exactly) and `GET /documents/{id}/preview.pdf` (merges the document's *current* cover facts into its source `.docx` and returns it as a PDF via Graph's native `?format=pdf` conversion — no local converter needed; verified against the live ORGOS LIBRARY). The preview never touches the source — it uploads the merged copy to a disposable scratch folder (`_CDT_Previews/`) purely so Graph has a real driveItem to convert.

**Approval (`_finalize_document_approval`)** — now the actual "issue a new version" moment: advances `cdt_cover.version` (`"Draft"`→`"01"`, `"05"`→`"06"`, …), auto-fills `final_approval` with the approver's resolved name if not already set, appends a new `revision_history` row, and attempts to produce the **published** (marker-free) copy via `merge()` — that copy becomes the Document Register's `SharePointUrl`. **Hard rule, tested both ways:** a merge failure (bad template, unreadable source, whatever) never blocks approval — it falls back to linking the raw source, exactly as before CDT existed, with a clear warning logged. The cover/history data still advances and gets saved either way; only the "clean copy" convenience is lost on failure.

**AI Drafter (`agents/policy_drafter/`)** — this was producing a *third*, non-conforming cover shape before (a 6-row table, `Version|Date|Author|Change` history, a trailing "Review and Approval" table matching neither the old nor the new standard). Rebuilt to **fetch the type's master CDT template** (`Templates/{doc_type}.docx`, validated) and build directly on top of it — the AI only appends body content (Purpose, Scope, …) *after* the cover; the cover's markers are never touched, exactly the same "AI never edits the file" principle as the rest of CDT. `docx_builder.py` lost ~150 lines of hand-rolled cover/header/footer/history/approval code that's now entirely superseded. Document codes also dropped the trailing `-SERIAL-YEAR` (v06 §4.0); a genuine collision gets a disambiguator appended to the ID (`CDI`, `CDI2`, `CDI3`, …) instead of reviving the old numbering.

**Tests** — 160 passing (up from 149 before this rebuild; only the 3 pre-existing, unrelated respx token-mock failures remain). Notably: `tests/lifecycle/test_merge.py` (18), `test_templates.py` (12), `test_register_bridge.py` (8) — all rewritten against v06, not just patched; `tests/lifecycle/test_approval_cdt.py` (4, new) — proves the approval merge-success and merge-failure-fallback paths explicitly; `tests/agents/policy_drafter/test_v06_drafting.py` (7, new) — proves the drafter builds on the real master template with markers surviving intact.

### What's still needed before this is live

1. **An admin adds 4 columns**, all "Multiple lines of text": `CDTCoverFacts` + `RevisionHistory` on **both** Document Lifecycle and Document Register.
2. **The actual master template `.docx` files** need to exist in the ORGOS LIBRARY's `Templates/` folder, one per document type (`Templates/Procedure.docx`, `Templates/Policy.docx`, …), built with the confirmed 15-row cover + the 3-row docxtpl loop pattern above. Nothing today auto-generates these — they must be hand-authored once, matching the officer-supplied `Cover_Page_Template 1.pdf`.
3. **The code-format fix, the combined-document detection, and the intake folder repoint** (§7 steps 1–3) are already shipped separately (see the `dev`/`main` git history) — this rebuild is steps 5–8 on top of that.
4. **Frontend** — none of this turn's work has a UI yet: no cover-facts edit form, no "Preview PDF" button, no visibility into the new endpoints. That's the natural next piece once this backend is reviewed.
