# CDT — Clock / Parking Lot

**Purpose:** Things that are deferred, blocked on someone else, or need a decision/confirmation — captured so we don't lose them while we keep building. Nothing here blocks the *current* build step; each item says what it blocks *later*.

**Legend:** 🔴 blocks a specific later phase · 🟡 needs confirmation, has a safe assumption for now · 🟢 nice-to-have / cleanup · ✅ resolved (kept for the record)

_Last updated: during Phase 0._

---

## A. Needs Compliance / business confirmation (you → Compliance)

| # | Item | Status | Blocks | Safe assumption we're building on |
|---|------|--------|--------|-----------------------------------|
| C1 | **Revision vs Issue increment rule.** When does `revision_number` increment vs `issue_number`? The 3CX history shows them moving independently (e.g. issue advanced on a re-issue where revision did not). PSA §7.2 increments both together. We need the *real* rule. | 🔴 | Phase 4 (revision-on-approve) | Both increment together on each approved revision — **placeholder only, must confirm before Phase 4.** |
| C2 | **Published-copy destination.** Where does the clean published document land — into the live `Policies, Procedures, …` folder (replacing//alongside the legacy PDF), or a dedicated `Published/` area? And what happens to the superseded legacy PDF? | 🟡 | Phase 3 (publish path) | Publish into the existing live library folder; keep superseded copies per DINT. Confirm before wiring the publish destination. |
| C3 | **Sign-off that the two-forms model is acceptable for controlled docs** (source-with-markers + regenerated published copy; published copy is authoritative). Get in writing (PRD GOV-1). | 🔴 | Go-live | Assumed acceptable (design approved verbally). |
| C4 | **Document library inventory** — count, types, active/high-churn set, and which PDFs are scanned images vs digital text. | 🟡 | Phase 6 sizing (migration) | Unknown size; hybrid migration pacing assumed. Read-only check shows the live library root has ONE folder: `Policies, Procedures, Manuals, Guidelines, Frameworks, Handbook, SOP`. |
| C5 | **Standard body skeleton per document type** (section headings for Procedure, Policy, SOP, Form) — a content decision Compliance owns. | 🔴 | TMPL-1 (template authoring) | Use the 3CX Procedure section list as the Procedure skeleton draft. |

---

## B. Non-code provisioning (you / SharePoint admin)

| # | Item | Status | Blocks | Notes |
|---|------|--------|--------|-------|
| P1 | Create **`Templates/`** folder at the ORGOS LIBRARY drive root; grant Compliance + Engineering write. | 🔴 | Phase 1 test upload, Phase 3 | Drive resolves fine (verified). Folder does not exist yet — `ensure_drive_folder()` can create it, or SP admin creates it manually. Decide who owns folder creation. |
| P2 | Create **`Sources/`** working-area folder; restrict to Compliance + Engineering. | 🔴 | Phase 3 | Same as P1. |
| P3 | Confirm/define the **read-only distribution area** so general staff cannot edit published copies (PSA §10). | 🟡 | Phase 8 | Likely the existing live library with tightened permissions. |
| P4 | **Author the Procedure master template `.docx`** (TMPL-1) — cover, header strip, revision-history table (using the corrected control-row layout below), body skeleton. Done in Word by Compliance + Engineering. | 🔴 | Phase 1 (real end-to-end test), Phase 3 | The long pole. See "Template authoring rules" section. |

---

## C. Environment / infra

| # | Item | Status | Blocks | Notes |
|---|------|--------|--------|-------|
| E1 | **Live write-path verification.** Read-only drive resolution is proven. The upload+download round-trip into the ORGOS LIBRARY still needs one live run (see `scripts/verify_cdt_drive.py`). Requires P1 (a folder to write to) OR uses `ensure_drive_folder`. | 🟡 | Confidence before Phase 1 build | Deferred from this session because it writes to the real library — run when ready. |
| E2 | **PDF rendering capability** (headless LibreOffice or equivalent) IF published output = locked PDF (Decision D3). | 🟡 | Phase 8 | Phases 1–4 publish `.docx`; PDF is a hardening step. Confirm the backend host can run a converter. |
| E3 | Confirm `docxtpl` in the **deployed** environment (added to requirements.txt; installed+import-verified locally on py3.14, docxtpl 0.20.2). | 🟢 | Deploy | Just ensure `pip install -r requirements.txt` runs in CI/prod. |

---

## D. Code cleanup / tech-debt discovered (🟢 not blocking)

| # | Item | Notes |
|---|------|-------|
| CL1 | **Duplicated `resolve_compliance_drive()`** in `scripts/intake_sharepoint_to_lifecycle.py`, `scripts/migrate_document_urls.py`, `scripts/count_intake_documents.py`. Now that a shared version exists in `graph/client.py`, migrate the scripts to import it and delete the copies. | Low risk, do when touching those scripts. |
| CL2 | **`graph/client.py` has a large commented-out duplicate header block** (lines ~1–345) before the real code. Consider removing for readability. | Cosmetic. |
| CL3 | **`upload_file_to_sharepoint` had no callers** and referenced an undefined `settings.sharepoint_drive_id`. Now refactored to use the compliance-drive resolver. If it stays unused, consider removing entirely in favour of `upload_bytes_to_drive`. | Resolved the landmine; deletion optional. |
| CL4 | Three parallel upload paths exist: `graph.client.upload_bytes_to_drive` (new, compliance library), `lifecycle/router.py::_upload_to_sharepoint` (orgos site default drive, `Lifecycle Documents/`), and the scripts. Decide the canonical one for CDT publish and note the split. | Architectural tidy — CDT should use the compliance-library path. |
| CL5 | **Pre-existing test failures** in `tests/test_graph_client.py::TestTokenAcquisition` (3 tests). Confirmed to fail on clean HEAD *before* any CDT change — not caused by this work. Likely a respx/httpx version mismatch (respx 0.23 + httpx 0.36). | Unrelated to CDT; fix when touching the token/test stack. |
| CL6 | **Cross-process determinism.** Merge determinism is proven byte-identical *within a process* (ME-06). For the CI audit gate, consider a cross-process/cross-machine determinism test (render the same source+context in two subprocesses). Property is expected to hold (docxtpl mutates XML text only; python-docx preserves package timestamps). | Strengthen the ME-06 CI gate later. |

---

## E. Resolved this session (✅ for the record)

| # | Item | Outcome |
|---|------|---------|
| R1 | **INFRA-1** — the `sharepoint_drive_id` gap. | Resolved: added shared `resolve_compliance_drive()` + `upload_bytes_to_drive()` + `ensure_drive_folder()` to `graph/client.py`; dead static-drive path refactored. Live read-only resolution of ORGOS LIBRARY **verified**. |
| R2 | **docxtpl viability on Python 3.14.** | Installed docxtpl 0.20.2; header + table-cell substitution, determinism (byte-identical), and repeating-row expansion all **proven by spike**. |
| R3 | **Revision-history marker layout** (design doc / PSA §4.3 was wrong). | Corrected: `{%tr for%}` / `{%tr endfor%}` go on their **own control rows** bracketing the data row, not inline. Design doc §5.2 updated. |
| R4 | `lifecycle/__init.py` typo. | Renamed to `__init__.py`. |
| R5 | CDT folder settings. | `cdt_templates_folder` / `cdt_sources_folder` added to `config.py`. |
| R6 | **Phase 1 — merge engine core.** | `lifecycle/schemas.py` (MergeContext, RevisionHistoryEntry) + `lifecycle/merge.py` (pure, deterministic, no-AI, fail-loud) built. 14 unit tests pass covering: all-zones fill, determinism (SHA-256), row expansion, empty history, unknown-marker, leftover-marker, XML escaping (`& < > "`), Unicode, corrupt source, and control-fact-contains-token guard. |
| R7 | **Phase 2 — register field wiring + bridge.** | 8 CDT fields added to `grc/schemas.py` (optional; `revision_history` as `list[dict]` to keep Tier-1 free of a CDT dependency), `DOC_FIELDS` mappings in `grc/constants.py`, read+write wired in `grc/service.py` (tolerant `_parse_json_list`, JSON-serialised history), and the `MergeContext.from_document_read()` bridge (duck-typed, no runtime grc coupling). 7 tests pass incl. full SP-item→DocumentRead→MergeContext→merge chain. Reads tolerate missing/malformed columns; writes only send provided fields. **Live writes still need DATA-1 (columns created on the list).** |
| R8 | **Template Manager (MT-01/02).** | `lifecycle/templates.py` — `validate_template()` (pure, MT-02: required markers present, no unknown/typo markers, no markers leaked into body prose — using docxtpl's `get_undeclared_template_variables` which handles run-splitting + headers) and `fetch_master_template()`/`load_master_template()` (fetch from ORGOS LIBRARY `Templates/{DocType}.docx` via the resolver, validate before use). Added `download_drive_item_by_path()` to `graph/client.py`. 12 tests pass. **Live fetch needs P1 (Templates/ folder) + a real master (TMPL-1).** |

---

## Template authoring rules (hand this to whoever authors TMPL-1)

The master template is a normal Word `.docx`. Markers go in **exactly three zones**; the body has **no markers**.

- **Scalar marker:** type `{{ field_name }}` exactly (double braces). Fields: `doc_code`, `doc_type`, `title`, `serial`, `revision`, `issue`, `approved_by`, `issue_date`, `classification`, `distribution`.
- **Zone 1 (cover)** and **Zone 2 (header strip)**: put the scalar markers in the relevant table cells / header cells. Verified that docxtpl fills markers inside headers and table cells correctly.
- **Zone 3 (revision-history table)** — use FOUR rows:
  1. Header labels row (fixed text).
  2. A **control row**: first cell = `{%tr for r in revision_history %}` (leave the other cells empty).
  3. A **data row**: cells = `{{ r.revision }}`, `{{ r.date }}`, `{{ r.issue }}`, `{{ r.purpose }}`, `{{ r.authority }}`.
  4. A **control row**: first cell = `{%tr endfor %}` (leave the other cells empty).
  Do **not** put the `for`/`endfor` tags inside the data row — docxtpl deletes the whole row a `{%tr%}` tag sits in.
- Type each marker in one go (don't let Word split it with autocorrect/spell-check mid-token); if unsure, type it, then re-select and retype cleanly.
