# Controlled Document Templating (CDT) — Implementation Plan

**Dragnet Solutions Limited · OrgOS GRC Platform**
**Drives:** PRD `DRG-PRD-CDT-01-26` · PSA `DRG-PSA-CDT-01-26`
**Companion design:** [DOCUMENT-TEMPLATING-DESIGN.md](DOCUMENT-TEMPLATING-DESIGN.md)
**Status:** Build plan — read the "Decisions to lock before coding" section first
**Grounded against actual code as of this branch** (not the PRD's assumed file layout)

---

## 0. How to read this plan

This is a *delivery* plan, not a restatement of the PRD/PSA. It covers three kinds of work, because the system will not function if only the code ships:

- **🟦 Decisions** — architectural forks that must be settled before code, because they change what we build.
- **🟩 Non-code work** — SharePoint provisioning, template authoring, permissions, training, governance. These are on the critical path and are frequently the *long pole*.
- **🟧 Code work** — grounded in the files that actually exist today.

Every phase ends with an explicit **Definition of Done**. Nothing is "done" until its DoD is met, including the non-code items.

> **The single most important finding from grounding this plan against the code:** CDT is **not** a greenfield module. OrgOS already has a mature, DINT-governed document lifecycle in [lifecycle/router.py](../lifecycle/router.py) — `create_doc`, `revise_doc` (DINT §5.3.2), `progress_doc`, `approve_doc`, `reject_doc`, `recall_doc`, `upload_doc_file`, `download_doc_file`, and version bumping via `_next_version` (`R01 → R02`). The PRD/PSA describe a fresh `lifecycle/merge.py` + "Issue New Revision" action as if none of this exists. **We must integrate CDT into the existing lifecycle, not run a competing revision mechanism beside it.** This reconciliation is Decision D1 below and shapes the whole build.

---

## 1. 🟦 Decisions to lock before coding

These are genuine forks. Each has a recommendation; confirm them before Phase 1.

### D1 — "Issue New Revision" vs the existing DINT revise→approve flow *(blocking)*

The PSA §7 specifies a standalone atomic "Issue New Revision" action that bumps numbers and re-merges. But [lifecycle/router.py](../lifecycle/router.py) **already** implements the revision lifecycle: `revise_doc` puts an Active document back into the lifecycle, and `approve_doc` bumps the version in the register in place. Building a second, independent revision path would create two sources of truth for "what revision is this document."

- **Recommendation:** Do **not** build a separate Issue New Revision action. Instead, make the **merge a step inside the existing approval flow** — when `approve_doc` finalises a revision and bumps the register version, it (a) writes the new revision-history entry and (b) triggers the merge to publish the clean copy. The officer-facing "issue a revision" experience becomes the DINT revise→progress→approve flow they already use, now with automatic re-publishing at the end. The PRD's IR-01…IR-05 acceptance criteria are satisfied *through* the approval step rather than a new endpoint.
- **Consequence for the plan:** PSA's `lifecycle/merge.py` and `lifecycle/templates.py` are still built, but `lifecycle/router.py` is *modified* (merge hook in approve) rather than gaining a parallel `/issue-revision` route.

### D2 — Version model: `revision_number` + `issue_number` vs existing `current_version` ("R03") *(blocking)*

The register today stores one `current_version` string (`R01`, `R03`) — see `DocumentBase.current_version` in [grc/schemas.py](../grc/schemas.py). The 3CX document (and the PRD) track **two independent numbers**: Revision (`03`) *and* Issue (`04`), which increment on different events.

- **Recommendation:** Add `revision_number` and `issue_number` as the authoritative controlled fields (they drive the template). Keep `current_version` as a **derived display string** (e.g. `f"R{revision_number:02d}"`) so nothing downstream that reads `current_version` breaks. Define precisely *when each increments* — the PSA §7.2 increments both together, but the 3CX history shows issue incrementing on re-issues where revision did not (Rev 02→02, Issue 03→… ). **Confirm the real business rule with Compliance before coding**; the increment logic is trivial but the rule is a compliance decision, not an engineering one.

### D3 — Published output format: editable `.docx`, locked PDF, or both

PSA §10 "Merge immutability" and the PRD risk table both lean to **locked PDF for distribution**. But merging produces a `.docx`; PDF requires a converter (LibreOffice/headless Word) in the environment.

- **Recommendation:** Phase 1–4 publish `.docx` (no new infra). Add locked-PDF rendering in the distribution-hardening phase (PSA calls this Phase 8). Confirm whether the environment can run a headless converter; if not, this becomes a provisioning task (see §2, INFRA-3).

### D4 — Revision-history storage: JSON column vs dedicated list

PSA §5.2 specifies a `RevisionHistory` "Multiple lines of text" column holding a JSON array. The design doc offered a dedicated list as the alternative.

- **Recommendation:** Follow the PSA — **JSON column**. It is the lowest-friction choice and one read returns the whole history. Only revisit if Compliance later needs to query/report across revision histories independently.

### D5 — Migration policy: eager, lazy, or hybrid

- **Recommendation:** Hybrid, as the design doc and PRD G5 already state — active/high-churn documents eagerly (target: within 90 days of go-live per PRD success metric), the long tail rebuilt on each document's next scheduled revision. This needs the **document count** (still unknown) to size Phase 6 — see §2, GOV-2.

---

## 2. 🟩 Non-code prerequisites (start these NOW — they are the long pole)

These do not depend on any code and several have external lead time. Start them in parallel with Phase 1.

| ID | Item | Why it blocks | Owner | Depends on |
|----|------|---------------|-------|-----------|
| **INFRA-1** | **Confirm/add `sharepoint_drive_id` in [config.py](../config.py).** `upload_file_to_sharepoint` in [graph/client.py](../graph/client.py) already references `settings.sharepoint_drive_id`, but no such field is declared in `config.py`. Publishing **cannot work** until this is resolved. | Every publish/upload path | Paul | — |
| **INFRA-2** | Create SharePoint **`Templates/`** folder in ORGOS LIBRARY; set permissions (Compliance + Engineering write). | Master templates have nowhere to live (MT-01) | Paul / SP admin | — |
| **INFRA-3** | Create SharePoint **`Sources/`** working-area folder; restrict to Compliance + Engineering. Create/confirm the **distribution** (published) area as read-only to general staff. | Source docs and published copies need distinct homes with correct access (PSA §10) | Paul / SP admin | — |
| **INFRA-4** | Decide & provision **PDF rendering** capability if D3 = PDF/both (headless LibreOffice or equivalent in the backend environment). | Locked-PDF output (PSA Phase 8) | Paul / Platform | D3 |
| **DATA-1** | Add the **7 new columns + `RevisionHistory`** to the Document Register SharePoint list, PascalCase per convention. | Register cannot store control facts (DR-01/02) | Paul | D2, D4 |
| **TMPL-1** | **Author the Procedure master template `.docx`** — cover, header strip, revision-history table with markers, and body skeleton. This is a **content/design task done in Word by Compliance + Engineering together**, not a coding task. Use the 3CX Procedure as the reference layout. | Nothing merges without a template (MT-01…03, dependency in PSA §9) | Compliance Officer + Paul | INFRA-2, zone spec (PSA §4) |
| **TMPL-2** | Agree the **standard body skeleton** per type (section headings) with Compliance. | MT-03 | Compliance | — |
| **GOV-1** | **Compliance sign-off that this approach is acceptable for controlled documents** — the two-forms model, deterministic merge, published-copy-is-authoritative. Get it in writing before go-live. | Risk of rework if Compliance rejects the model late | Head of Eng + Compliance | design doc |
| **GOV-2** | **Inventory the existing document library**: count, types, which are active/high-churn, and (critical) which PDFs are **scanned images vs digital text**. | Sizes migration (Phase 6); scanned PDFs need the OCR path | Compliance | — |
| **GOV-3** | Confirm the **revision/issue increment business rule** (feeds D2). | Wrong rule = wrong version numbers = the exact nonconformity we're preventing | Compliance | — |
| **TRAIN-1** | Plan the **officer training + change-management session**: the two-forms model, "never hand-edit the published copy," how to author body content, how migration works. PRD risk table flags officer resistance as the top integrity risk. | Adoption; prevents reintroduced inconsistency | Compliance lead + Paul | working system (Phase 3) |
| **TRAIN-2** | Write the **1-page operating standard** for officers ("what CDT changes about your job"). | Sustained correct use | Paul | Phase 3 |

> **Do not treat TMPL-1 as trivial.** Authoring a clean, correctly-marked Word master — with markers that survive Word's run-splitting, living in the section header and inside table cells — is fiddly and is the thing most likely to cause Phase-1 rework. Budget real time and pair Compliance (layout authority) with Engineering (marker correctness).

---

## 3. 🟧 Code workstreams — grounded in the real codebase

### Current-state facts the plan relies on

- `lifecycle/` contains **only** `router.py` (~69KB) and a **misnamed** `__init.py` (should be `__init__.py`). There is **no** `lifecycle/schemas.py` yet — PSA's "modify schemas.py" is actually "create it." *(Fix the `__init.py` typo as housekeeping.)*
- `docxtpl` is **not** in [requirements.txt](../requirements.txt). It is the one new dependency (PSA §3).
- `pypdf` **is** already present and used by the CDI checker — reuse for migration extraction. `azure-ai-formrecognizer` (OCR fallback) is also present — **reuse it for scanned legacy PDFs** (not mentioned in PSA but available and relevant to GOV-2).
- Audit-log writes have an established pattern: `_write_audit_log` in [control_register/router.py](../control_register/router.py) writing to the "Audit Log" list. The merge audit event should mirror its column shape.
- `upload_file_to_sharepoint(folder=...)` and `download_file_from_sharepoint(web_url)` already exist in [graph/client.py](../graph/client.py) — the merge/publish path builds on these, not new Graph plumbing.
- `agents/policy_drafter/service.py::draft_document` already builds a `.docx` via `docx_builder.build_docx`. The PD integration (PSA §8) hooks in *after* draft generation.

### Module build order (mirrors PSA §11 file list, corrected for reality)

| File | New/Modified | Work |
|------|--------------|------|
| [config.py](../config.py) | Modified | Add `sharepoint_drive_id` (INFRA-1) + any `Templates/`/`Sources/`/distribution folder settings. |
| [requirements.txt](../requirements.txt) | Modified | Add `docxtpl>=1.0.0` (pin, test import). |
| [grc/schemas.py](../grc/schemas.py) | Modified | Extend `DocumentBase` with the 7 fields + `RevisionHistoryEntry` model + `revision_history: list[...]`. Keep `current_version` derived (D2). |
| [grc/constants.py](../grc/constants.py) | Modified | Add the 7 SharePoint column mappings + `RevisionHistory` to `DOC_FIELDS`. |
| `lifecycle/templates.py` | **New** | Template Manager: copy correct master for a type, validate markers present in zones & absent from body, manage `Templates/`. |
| `lifecycle/merge.py` | **New** | Merge engine: load source via docxtpl → read register → build context → render → **validate zero unresolved markers** → write published copy → write merge audit event. **No AI import; deterministic.** |
| `lifecycle/schemas.py` | **New** | `MergeRequest`, `MigrationSession`, `RevisionHistoryEntry`, etc. (Pydantic v2). |
| [lifecycle/router.py](../lifecycle/router.py) | Modified | (a) hook merge into `approve_doc` per D1; (b) "create from template" in `create_doc`; (c) `/merge` endpoint for manual re-publish; (d) migration endpoints. Fix `__init.py` typo. |
| `lifecycle/migrate.py` | **New** | Migration tooling: pypdf (+OCR fallback) extract → metadata candidates → officer-confirmation payload → body scaffolding. **No auto PDF→Word conversion** (MG-05). |
| [agents/policy_drafter/service.py](../agents/policy_drafter/service.py) | Modified | After draft, place body into master template body, leave zones as markers, save as source, present for review (PD-01…03). |

---

## 4. Phased delivery

Sequenced so that **value lands at Phase 3** (new documents fully working) and migration never blocks it. Each phase lists code, the non-code items it depends on, and a Definition of Done.

### Phase 0 — Foundations & decisions *(no user-facing value; unblocks everything)*
- **Do:** Lock D1–D5 (§1). Kick off all §2 non-code items. Resolve **INFRA-1** (`sharepoint_drive_id`) — verify uploads actually work end-to-end with a throwaway file. Add `docxtpl`, confirm it imports. Fix `__init.py`.
- **DoD:** Decisions signed off (GOV-1 in writing). `Templates/`, `Sources/`, distribution folders exist with correct permissions. A test file uploads to and downloads from SharePoint successfully. `docxtpl` installed.

### Phase 1 — Merge engine (the deterministic core)
- **Code:** `lifecycle/merge.py`, `lifecycle/templates.py`, `lifecycle/schemas.py`. Marker validation (fail-loud, ME-02). Revision-history row expansion (ME-03). Merge audit event (ME-04, mirror `_write_audit_log`).
- **Non-code dep:** **TMPL-1** (a real Procedure master template to test against).
- **Spike first (PRD risk #1):** prove `docxtpl` correctly substitutes markers **inside the Word section header and table cells** on the actual 3CX-style master before building the rest. If header substitution fails, resolve the template structure now, not later.
- **DoD:** Given the master + a hand-made register entry, the engine produces a published `.docx` with **zero visible `{{ markers }}`**, all three zones consistent, N history rows = N register entries; a second run is **byte-identical** (determinism, ME-06 via SHA-256); an unfilled marker **blocks** publish with a named error; a merge event lands in the Audit Log. No AI import anywhere in the merge path (code-review gate, ME-05).

### Phase 2 — Register wiring
- **Code:** `grc/schemas.py` + `grc/constants.py` changes (D2/D4). `RevisionHistory` JSON parse/serialise on read/write. `next_review_date` computed (DR-03), following the stateless-status pattern already in `grc/service.py`.
- **Non-code dep:** **DATA-1** (columns exist on the list).
- **DoD:** All 7 fields + `RevisionHistory` round-trip through the register (create/read/update); malformed `RevisionHistory` JSON is rejected with a 422; `current_version` still returns the expected string for existing consumers; `next_review_date` never stored, always derived.

### Phase 3 — New-document flow *(first real value)*
- **Code:** `create_doc` copies the correct master for the selected type (ND-01), auto-generates the code (ND-02, reuse policy_drafter's code generator), sets initial control facts (ND-03), saves a source in `Sources/`. Officer authors body; **merge on publish** produces the clean copy.
- **DoD:** An officer creates a new Procedure end-to-end without typing any metadata into the document; the published copy is consistent across all zones; the officer never edited cover/header/history by hand (PRD G1 for new docs).

### Phase 4 — Revision via the existing lifecycle (D1) + Policy Drafter integration
- **Code:** Hook merge into `approve_doc` — on approval of a revision, append the revision-history entry, bump revision/issue per D2, re-merge, re-publish, audit-log (satisfies IR-01…IR-05 through the DINT flow). Policy Drafter places AI body into the template body only, zones untouched (PD-01/02), officer review step (PD-03).
- **DoD:** Approving a revision auto-publishes a clean copy with incremented numbers and a new history row, atomically (no partial state on failure); a code-review gate confirms **no AI output path can reach the three zones** and markers remain intact after PD body insertion.

### Phase 5 — Migration tooling (PDF-only)
- **Code:** `lifecycle/migrate.py` — pypdf extract (+ **Azure OCR fallback for scanned PDFs**, per GOV-2), metadata-candidate confirmation payload (officer confirms every value, MG-03), raw body text scaffolded into a template copy for human reformatting (MG-04). **No auto conversion** (MG-05).
- **DoD:** Proven on the 3CX Procedure: extract → officer confirms metadata into the register → body rebuilt in template → initial merge → published copy visually matches the original PDF; nothing committed to the register without explicit confirmation.

### Phase 6 — Paced back-catalogue migration *(operational, not code)*
- **Do:** Migrate active/high-churn docs eagerly (PRD target: 100% of active within 90 days); leave the tail to be rebuilt on next scheduled revision. Track via a `source_path`-populated count.
- **DoD:** All active documents migrated within the target window; migration status visible in the register.

### Phase 7 — Expand document types
- **Do:** Author master templates for Policy, SOP, Form (repeat TMPL-1 per type); repeat Phases 1-test/3 validation per type.
- **DoD:** Each supported type has a marker-validated master and a passing new-doc + merge round-trip.

### Phase 8 — Distribution hardening
- **Code/Infra:** Locked-PDF output (D3/INFRA-4), read-only distribution enforcement (PSA §10), complete merge-event audit logging.
- **DoD:** Published copies are non-editable in the distribution area; every publish is traceable end-to-end for an ISO auditor (NFR Auditability).

---

## 5. Testing strategy

Follow the existing `pytest` + `respx` conventions (`asyncio_mode = auto`; all Graph calls mocked).

- **Merge engine (highest value):** golden-file tests — fixed master + fixed register → assert exact published output and **SHA-256 stability** across runs (ME-06); unresolved-marker → raises; N-history-rows expansion; **assert no AI gateway import/call** in the merge path (this is the compliance guarantee, so test it explicitly).
- **Register:** field round-trips, `RevisionHistory` JSON parse/validate (incl. malformed → 422), `current_version` derivation, `next_review_date` computation.
- **Revision-on-approve (D1):** atomicity — inject a failure mid-way and assert the register is left in its pre-action state and no partial publish occurred.
- **Policy Drafter boundary:** after body insertion, assert all zone markers still present (AI never wrote a zone).
- **Migration:** extraction on a digital PDF and a scanned PDF (OCR path); assert no register write occurs before confirmation.
- **Security:** all CDT routes 401 without a token (matches OrgOS convention).
- **Manual/UAT:** Compliance officer runs the full new-doc and revision flows on real content before go-live (TRAIN-1 doubles as UAT).

---

## 6. Cross-cutting guarantees to hold throughout (from PSA §10 / NFRs)

1. **Determinism:** no non-deterministic component (no AI, no `Date.now()`-style nondeterminism beyond the intended timestamp) in the merge path. Tested, not assumed.
2. **Fail-loud on markers:** a published document with a visible `{{ marker }}` must never be written. Enforced in the engine + tested.
3. **Auditability:** every publish → one Audit Log entry (who/when/values/output URL).
4. **AI boundary:** AI touches only the *body draft*; the three zones and the merge are AI-free, enforced at code level (not by prompt).
5. **Immutability of published copies:** distributed copies are read-only; re-publishing goes through the lifecycle, never a hand edit.
6. **No new infra beyond docxtpl** (+ optional PDF renderer for D3). No new DB, no new service.

---

## 7. Risks & mitigations (delta to the PRD risk table)

| Risk | Mitigation |
|------|-----------|
| **`sharepoint_drive_id` gap (INFRA-1)** blocks all publishing and is currently latent. | Resolve in Phase 0 with an end-to-end upload test *before* building the engine. |
| **Building a parallel revision path** (ignoring D1) creates two version sources of truth. | D1: integrate merge into `approve_doc`; do not add a competing action. |
| **docxtpl header/table-cell substitution fails** on the real template. | Phase-1 spike on the 3CX-style master before full build (PRD risk #1). |
| **Version model mismatch** (D2) breaks downstream `current_version` consumers. | Keep `current_version` as a derived field; confirm increment rule with Compliance (GOV-3). |
| **Scanned legacy PDFs** yield no text for migration. | Use the existing Azure OCR fallback; flag scanned docs during GOV-2 inventory. |
| **Officer resistance / hand-editing published copies.** | TRAIN-1/2 + locked-PDF distribution (Phase 8) + Compliance sign-off (GOV-1). |
| **Migration underestimated** (unknown library size). | GOV-2 inventory before committing the 90-day target; hybrid pacing (D5). |

---

## 8. Immediate next actions (this week)

1. **Confirm D1–D5** (owner: Head of Eng + Compliance + Paul). D1, D2, GOV-3 are blocking.
2. **INFRA-1:** verify/add `sharepoint_drive_id`; prove upload+download works. *(One afternoon; unblocks everything.)*
3. **INFRA-2/3:** create `Templates/`, `Sources/`, distribution folders + permissions.
4. **GOV-2:** start the document-library inventory (count + scanned-vs-digital).
5. **TMPL-1:** begin authoring the Procedure master template against the 3CX layout.
6. Add `docxtpl`; run the **header/table-cell substitution spike**.

Once 1-2 are green and a first master exists, Phase 1 coding starts against a real template.

---

*This plan integrates CDT into OrgOS's existing DINT document lifecycle rather than treating it as a standalone module. Where the PRD/PSA and the current code disagree, the code's reality wins and the divergence is called out above.*

---

## Appendix A — Verified integration facts (from codebase review)

Concrete, file:line-grounded findings that make the phases buildable. Verified by reading the actual code, not the PRD.

### A1 — The exact merge hook point (Decision D1)
`lifecycle/router.py::approve_doc` (lines ~903-1123) is where a revision/new doc is finalised:
- It updates the **Document Register in place** for a revision (version bump via `_next_version`, `R01→R02`, lines ~973-1002) or **creates** a new register item for a new document (lines ~1015-1049).
- It does **not** upload or merge any file — it just points the register's `SharePointUrl` at the *existing* lifecycle file URL (best-effort PATCH, lines ~1051-1066).
- **Hook the merge here:** after the `DocumentCode` validation (~line 960) and around the register write, render the master template + merge register values → upload the published `.docx` to the ORGOS LIBRARY → set both the register `SharePointUrl` **and** `doc["SharePointFileUrl"]` to the published copy **before** the extraction call at ~line 1092 (otherwise extraction runs on the pre-merge file).
- **Also update** the read-only preview `approval_impact` (GET `/documents/{id}/approval-impact`, ~787-900) so the approver's preview reflects the merge.
- `_next_version` quirk: a blank/unparseable version returns `R02` (not `R01`); new docs hard-code `R01`. Keep that behaviour.

### A2 — The site/drive split (feeds Clock C2/CL4)
Two different SharePoint locations are in play:
- **Lifecycle working files** upload via `lifecycle/router.py::_upload_to_sharepoint` to `Lifecycle Documents/{lifecycle_item_id}/…` on the **orgos site's default drive**.
- **CDT masters/sources/published** should live in the **ORGOS LIBRARY** on the **compliance site** (verified reachable via the new `resolve_compliance_drive()`), where the real controlled documents already are.
- Decision needed (C2): does the published copy land in the live `Policies, Procedures, …` folder or a dedicated area, and what happens to the superseded file. This does **not** block Phases 1-2.

### A3 — Wiring the new register fields (Phase 2)
Each new field touches **four** places (per the `grc/service.py` pattern): `DOC_FIELDS` in `grc/constants.py` → `_sp_item_to_doc` (read, ~260-286) → `create_document` (write, ~478-498) → `update_document` (write, ~501-528), plus the `grc/schemas.py` models.
- **Dates:** write `.isoformat()`, read `_parse_date` (first 10 chars).
- **`revision_history` (JSON):** no existing precedent — add a `json.dumps`/`json.loads`-with-guard helper alongside the parsing utils (~387-433). Store in a "Multiple lines of text" column.
- **`approved_by`:** model as a **plain string** (the approving authority is a name, e.g. "Arek Bawa"), **not** a person/PersonRef — avoids the `OwnerId`-write vs `OwnerEntraId`-read asymmetry that documents currently have.
- **`next_review_date`:** documents currently **store** it (not computed, unlike obligations/contracts). PSA DR-03 wants it computed. Resolution: compute it in the CDT write/approve path and **store the computed value** — satisfies DR-03 without changing the read path or breaking existing consumers.

### A4 — Policy Drafter integration is a reshape, not just an insert (Phase 4/PD)
`agents/policy_drafter/service.py::draft_document` (~576-693) is a pure generator: it produces six **body** section strings (`purpose, scope, policy_statement, responsibilities, procedure, records`) and calls `build_docx`. Today `docx_builder.py` stamps its **own** cover, header/footer, version (`1.0`), DRAFT badges, revision-history and approval tables — i.e. it currently owns the metadata chrome that **CDT's template will replace**. So PD integration = route the six AI body sections into the **master template body** and stop using `build_docx`'s chrome (or add a body-only builder). The AI must never populate the three marker zones (PD-02).

### A5 — Testing conventions (all phases)
- Endpoint tests: `TestClient(app)` + module-level `app.dependency_overrides[get_current_user] = override_auth`; for compliance-gated routes also override `require_compliance_lead`.
- House pattern mocks the **service layer**, not Graph HTTP: `patch("<router>.service.<fn>", new_callable=AsyncMock)`, then assert status, `response.json()`, and `mock.assert_called_once_with(...)`.
- **Merge engine** is pure logic over in-memory `.docx` (proven in the Phase-0 spikes) — unit-test it directly with no Graph mocking, including the SHA-256 determinism check and the fail-loud unresolved-marker check.

### A6 — Phase-0 spike results (done, passing)
docxtpl 0.20.2 on Python 3.14: marker substitution inside Word **headers and table cells** ✅; **byte-identical determinism** across renders ✅; repeating revision-history rows expand correctly ✅ — with the corrected authoring rule that `{%tr for%}`/`{%tr endfor%}` sit on **their own control rows** bracketing the data row (design doc §5.2 and Clock updated).
