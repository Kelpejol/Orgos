# OrgOS platform review — 29 October 2026

Six reviewers read the code against one product model (what OrgOS is meant to be), each in one area:
document entry and Lifecycle; approval to the Control Register; roles; evidence, gaps and the Standards
Map; the screens; scripts, purge, configuration, tests and documentation. Nothing was changed and nothing
was written to SharePoint. Findings marked **(checked)** were re-verified in the code after the review.
One reviewer finding was wrong and is left out: the approval button is not limited to the owner.

The product model used as the yardstick is at the end of this file.

## Verdict

The core of the product is right: documents enter through Lifecycle, controls are read from approved
documents by Control ID, nothing reaches the Control Register except through review, and the new checks
and the Control owner model are in place. But it is **not yet in sync as a whole**. The main problems are:
the file handling around approval, three different ways of matching role names, the numbers on the
Standards Map and WorkHub, controls that are never retired, and a purge that would lose work and data.
None of these show up in the automated tests, which all pass.

**Do not purge until Batch 1 is done.**

---

## Batch 1 — must fix before any purge (data safety and the way in)

1. **Approval writes the published copy over the item's working copy.** (checked) The published file is
   uploaded to `Lifecycle Documents/{item_id}/` under the working copy's own name
   (`lifecycle/router.py:1252`). A revision then starts from the published file (`revise_doc`, ~:686).
   Likely effect, to be proven by a test: from version 02 on, the cover is no longer re-stamped with the
   new version and dates. *Fix:* publish under its own path; start revisions from the source.
2. **Several Lifecycle write actions have no stage or owner guard.** Upload, Fix CDI apply, amendment
   apply, attach cover and cover edit can change the file of an item that is already approved, outside
   Review, and only upload makes a working copy (`router.py:2429, 3176, 3489, 2203, 1963`). *Fix:* every
   write goes through `_editable_item` and `_ensure_working_copy`.
3. **Skip-approver can strand a document in Approval** when its code is invalid, because that check runs
   after the stage moves (`router.py:782-800`, `:1171`).
4. **Duplicate Document Register entries.** Approving a document whose code already exists, with no
   "revision of" link (intake, review-queue tasks), creates a second entry at 01; a revision whose Register
   entry can't be read is published as a new entry (`router.py:1195-1203`; intake dedups by URL only).
5. **Reverse approval of a revision withdraws the live document** and does not roll back the version
   (`router.py:1677`).
6. **The purge would lose work and data** (`scripts/reset_data.py`):
   - It hard-deletes the **Audit Log, Compliance Calendar, Contract Register and Strategic Risks**, which
     cannot be rebuilt from documents. No backup is taken and there is no restore script.
   - All Review work (CDT conversions, role fixes, CDI fixes, published copies) lives only in
     `Lifecycle Documents/`. Re-intake reads the original library files, so that work is lost unless it
     is copied back into ORGOS CONTROL LIBRARY first.
   - The intake checkpoint (`scripts/intake_lifecycle_checkpoint.json`, 113 items) is not cleared, so
     re-intake would skip those documents unless `--reset` is used. (checked)
   - Deletes are one by one with no retry; a long purge can stop half-done.
7. **Three scripts work against the model.** (checked) `cdi_triage.py` puts documents straight into the
   Document Register (bypasses Lifecycle); `patch_bare_lifecycle_items.py` writes the blanket
   "ISO 27001, ISO 9001, NDPA"; `publish_approved_lifecycle.py` writes "R01" register rows. Retire them.

## Batch 2 — roles (the requirement: flag at entry, fix per control, update the document)

**Precondition — one way of matching role names.** (checked in part)
- V07 and role fixes use `doc_standards/roles.py` (`&`, `/` read as "and", punctuation ignored); control
  status, gaps, the Standards Map and "owned by me" use `ownership/resolver.py` (case and spaces only);
  the duplicate-role check uses a third rule (`groups/service.py:229`). A role V07 accepts
  ("IT & Security Lead" for "IT and Security Lead") can still leave the control Blocked.
- An agreed alias spelled like an Entra job title is ignored: job titles are loaded first and an alias
  never overwrites them (`resolver.py:56-69`). (checked) The control is Blocked "matches only an Entra job title".
- If Org Roles fails to load, the recheck marks every Active control Blocked (`resolver.py:156`,
  `control_register/status.py:36`).
- Two roles that differ only in "&"/"and" can both be created.

**Other ways a wrong role still becomes Active**
- Legacy (contract/JD/audit) accept makes a control Active for any non-empty owner text
  (`review_queue/acceptance.py:49`), and legacy rows are never re-checked (`control_register/sync.py:151`).
- Control Register "Reassign owner" offers job titles, counts a job title as an owner, goes Active if the
  check errors, and writes no Audit Log (`control_register/router.py:209-224`).
- Multi-role owners are only detected with ";" — "CISO and DPO", "Head of IT, ISMS Lead" pass
  (`doc_standards/roles.py:168`).
- Cover and approval fields suggest Entra job titles, not Org Roles (`JobTitleInput.jsx`,
  `CdtCoverPanel.jsx`, `lifecycle/cover_suggest.py:380-410`).
- Approval writes the approving **person's name** into the cover's Final approval when it is empty
  (`router.py:1229`); V07 then flags it as not a role.

**Your requirement — where it stands**
- **Not automatic.** Entry paths (intake, upload, revise, convert) run only the old checker; V07 runs
  only on "Check against the standard" or inside Fix CDI. Nothing is stored on the card.
- **"Fix CDI issues" hides role problems:** the button shows only when the old checker found something,
  and only to the owner (`DocumentLifecycle/index.jsx:1879`).
- **Not per control.** A fix replaces that wording in every role field of the document; two controls with
  the same wrong role cannot get different roles (`role_fix.py:164`).
- **Old lines stay old.** "Accountable / Executing: X; Y" keeps its old form; the executing half is never
  checked by V07. Some forms cannot be fixed at all ("X / Y" split by a slash; "Final approval: X (via ExCo)").
- **Too wide in one place:** a role fix also rewrites a record's "Owner" (custodian) field.
- **Other spellings left behind:** only the first spelling V07 saw is replaced.
- Sensitisation, Approval and PDF documents cannot be fixed (expected), but the panel still offers the button.

**Proposed design (smallest that meets the requirement)**
1. On create, revise, upload and convert, run V07 against Org Roles and store the result on the item. The
   card shows "N role problems".
2. V07 lists each use separately: control ID, or cover owner / first pass / final approval, or Roles table.
3. One Roles panel: a row per control or cover field, each with its own picker limited to Org Roles,
   pre-filled with the best suggestion, plus "apply to all". Keep alias and Create role.
4. The edit is scoped to that control's field; an old "Accountable / Executing" line is rewritten as
   "Control owner: <role>", proven like today's edit; CDT covers update their cover facts.
5. Review stage only; other stages and PDFs show the problem read-only with "Return to Review" /
   "Upload the .docx".

## Batch 3 — after acceptance (the numbers people rely on)

1. **The Standards Map never counts records against controls from approved documents.** (checked)
   Records are filed under the Control ID but looked up by SharePoint row number
   (`standards_map/router.py:104, 146`).
2. **Its lights read a status nothing sets.** (checked) It looks for a stored "Overdue"; late, missing or
   stale evidence never turns a clause Red (`router.py:66-79`). Use each obligation's computed state.
3. **A gap accepted as a risk comes back as a new Open gap every run** (`gap_analyzer/service.py:104`).
4. **Withdrawn and superseded controls still count as coverage** (gap analyzer and Standards Map).
5. **Clause gaps never close themselves**; only CDI gaps do (`service.py:356`).
6. **Controls removed from a document are never retired.** They stay Active, keep their evidence
   obligations and stay on the map. The reader knows ("no longer defined") but only the CLI prints it
   (`control_register/sync.py:163`).
7. **While a Standard is still in Lifecycle**, two procedures copying a control raise a false "Defined
   twice"; and when a Standard drops a control, a procedure's short copy becomes its definition.
8. **Evidence owner** for older-form controls is the executing role, while the control's owner is the
   accountable role (`evidence/obligations.py:119`).
9. **Anyone signed in can submit evidence**; the server does not check the owner (`record_tracker/router.py:281, 322`).
10. **No Audit Log** for: record verify, schedule and reassign; gap status and accept-risk; risk create and
    update; role create, alias and delete.
11. **"Request 2nd review" breaks the queue** (checked): it writes "Second Review Requested", which the
    second reviewer cannot accept and the next sync duplicates. It should be "Pending Second Review".
12. Smaller: gap and risk IDs missing on some paths; open gaps never refresh their text; the 3-day gap job
    restarts its count on every app restart; state named "Current" where the product says "OK".

## Batch 4 — the screens

1. **Document owners cannot open Document Lifecycle.** (checked) It is Compliance-only, so an owner can't
   upload, edit or fix their own document. *Decision needed:* open it to owners, showing their own cards.
2. **Owner as approver contradicts itself.** (checked) Approval allows the owner to be the approver, but the
   approval preview refuses it, so the Confirm button is disabled.
3. **The Document Register has a second way in.** (checked) "+ Register document" creates entries directly,
   and Edit lets anyone change version and dates by hand.
4. **WorkHub numbers are wrong** (two reviewers): wrong filter names (queue, gaps), wrong field names, and
   "overdue" counts a status that never exists. It also lacks the cards that matter now: my documents in
   Review, Blocked controls with reasons, role problems.
5. **Two checkers, both called "CDI"**, with different counts; "Re-check CDI" runs only the old one.
6. **Harmonisation** still renames roles and merges controls inside the register, outside documents.
7. Wording: "Owner" means three things; menu group "Extraction & Lifecycle"; "Defaults to ISO 27001,
   ISO 9001, NDPA"; download named "_v1.0_DRAFT"; register column "Rev".
8. Control Register offers "Reassign owner" on controls that are defined by documents (the server refuses);
   the detail shows a generic Blocked text, not the reason; Org Roles opens on the People tab and counts
   ownership by job title.
9. Dead code: Extractor and AI Review Queue pages (unreachable), prototype code in `App.jsx` with sample
   data that includes real staff names, an approval modal that can never open, ~300 commented-out lines.

## Batch 5 — documentation, configuration, tests

- **Docs that are now false**: CLAUDE.md (evidence routes are `/api/v1/records/*`; Role Register,
  `sync_roles.py`, 14 routers, old library folder, "controls come from the extractor", "Ollama only");
  README (flow and tests); HOW-ORGOS-WORKS (11 checks not built and no gate; CDI-06 blocks);
  REMAINING-WORK (13 checks; Role Catalogue; executing role; organogram); GO-LIVE-CHECKLIST.
- **Configuration**: `INTAKE_OWNER_EMAIL` is never read from `.env`; `STANDARD_GATE` and several others
  are missing from `.env.example`; the intake cron script looks for `orgos_env`, the repo uses `myenv`.
- **SharePoint columns** the code needs that the provisioning script does not create (Review Queue
  `ControlId`, `CandidateJson`…; Lifecycle `CDTCoverFacts`, `RevisionHistory`…; DocumentType has no
  "Standard"). Matters if a list is ever recreated; a purge keeps the columns.
- **Tests**: 902 pass; 3 graph tests fail because they depend on the local `.env`. No tests for Org Roles
  routes, strategic risks, the gap router, the scheduled jobs, the purge or intake runs, or token
  validation. Scheduled jobs would run once per worker if the server runs several workers.

---

## Rebuild order after a purge (only after Batch 1)

1. Stop cron. Back up every list by hand (there is no script).
2. Copy working and published copies from `Lifecycle Documents/` back into ORGOS CONTROL LIBRARY.
3. `scripts/reset_data.py` (dry run), then `--confirm`.
4. `scripts/intake_sharepoint_to_lifecycle.py --reset`, then run intake with `--owner-email`.
5. Check Org Roles and the Records Catalogue are still there (the purge keeps them).
6. In OrgOS: Review (role check, Fix CDI, Convert to CDT, decisions) → Sensitisation → Approval.
   Approve Standards before the Procedures that carry them out.
7. Accept in Extraction Review; resolve Assignment & Ownership.
8. `scripts/sync_evidence_obligations.py`; officers set frequencies.
9. Run gap analysis (API), rebuild the chat index (API).
10. Re-enter Calendar, Contracts and Risks if they were not backed up. Turn cron back on.

---

## Product model used as the yardstick

See the "OrgOS — the product as it is meant to be" model: one way in through Document Lifecycle;
controls defined only in approved documents, read by Control ID, accepted in Extraction Review; V01–V24
as the standard (14 built), the old CDI-01..15 beside it until Bobby decides; one version number; one
Control owner per control and a Document owner per document, both roles in Org Roles, which is the only
role register (no job titles, no organogram, no Role Catalogue); evidence produced by the Control owner;
Audit Log for every decision; soft delete everywhere except the purge; Standards Map and Gap Analysis
driven by each control's own mapping and state.
