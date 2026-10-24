# How OrgOS works — the complete explainer

*19 Oct 2026. Written in plain words. Everything here was checked against the code, not taken from earlier plans. Where the code falls short of what it should do, this guide says so.*

> **Update, later on 19 Oct:** there is now **one way in: Document Lifecycle.** When a document is approved, OrgOS reads it with the new reader, by Control ID, and compares it only with other approved documents. The old AI extractor no longer runs on approval, and the library folder's drafts are no longer read for controls. The "shall" check (CDI-06) is now a warning. Sections 0, 1, 2, 4 and 12 describe the new behaviour.

---

## 0. Your questions, answered directly

### "What is the starting point? Is it still Document Lifecycle?"
**Yes, and now it's the only one.** A document is written, checked (CDI), commented on (sensitisation) and approved in Document Lifecycle. **At approval** OrgOS reads its controls with the new reader and sends them to Extraction Review. Nothing else puts controls in. Drafts sitting in the library folder reach Lifecycle through the **SharePoint intake**, which creates a Lifecycle entry for each new file (section 2).

### "How do we already have all the controls when the documents haven't passed Lifecycle?"
Because the earlier library sync **didn't look at approval**; it read whatever was in the folder. I checked every file: **all 123 are drafts.** 83 say "Draft" on their own cover, and 40 state no status. So the 355 controls and 7 findings now in the queue all came from drafts. **That's no longer how it works.** Run `scripts/retire_draft_library_items.py` to retire those items (it's a dry run first). Each document's controls come back when it's approved.

### "Are we sure the reading is right? Could it skip a document or make mistakes?"
**It's exact when the document follows the pattern, and it can miss things when it doesn't.** Plainly:
- **Will be read:** every .docx and .pdf in any subfolder of ORGOS CONTROL LIBRARY.
- **Will be skipped, with a message:** .doc files, password-protected files, broken files.
- **Will be skipped silently (for the document-standards engine, section 12):**
  - files loose in the top folder;
  - scanned PDFs (no text to read);
  - a control block with fewer than 3 of its fields;
  - a control whose labels are misspelled badly enough.
- **Could be wrong:**
  - two documents define the same control, and the "stronger" one wins quietly;
  - a draft and a final copy without codes are both read.
- **Was dangerous, and is fixed now:** if a file failed to download, its controls looked deleted. The sync now refuses to write in that case.

The full scenario list is in section 7.

### "Does the control pattern have to be a standard we follow when writing documents?"
**Yes.** OrgOS doesn't "understand" text; it recognises **labels**. A control is a line with its ID (e.g. `ACS-L3-01`) followed by labelled lines: `Requirement:`, `Trigger:`, `Control owner:`, `Evidence:`, `Risk:`, `Failure route:`, `Exception route:`, `Mapping:`. Your CDI v06 Standard already uses this pattern, so it's not new work. It just has to be followed every time. Section 11 is the 12-rule checklist for authors.

### "Is the Responsibilities section where the controls, or the Control owner, are checked?"
**No, they're two different things:**
- **The Responsibilities section** (CDI-05) is a **document-level** list near the front: *who has which duties under this document* (Document Owner, Information Security Officer, …). CDI-05 only checks that the section exists.
- **The Control owner line** sits **inside each control**. It names the **one role** answerable for *that one control* (and for producing its evidence). It's what decides whether a control is **Active** or **Blocked** (section 10).

The reader also uses the Responsibilities (Roles) table. Every role named anywhere in the document must be a role in **Org Roles**; the check (V07) says which are not and suggests the roles that exist.

### "What does each field mean — trigger, failure route, exception route…?"
Imagine the control *"lock the office door"*:

| Field | Plain meaning | Door example |
|---|---|---|
| **Requirement** | The rule | The last person out shall lock the front door |
| **Trigger** | When the rule applies | Every evening, when the last person leaves |
| **Control owner** | The one role answerable for it, and for its evidence | Office Manager |
| | *(There is no separate "Executing" role: older documents that still say "Accountable / Executing" keep working and are told to move to Control owner.)* | |
| **Evidence** | The proof it happened | The lock-up sheet, signed (REC-0123) |
| **Risk** | Why the rule exists; what goes wrong without it | Break-in and stolen laptops |
| **Failure route** | What to do **when it went wrong** | If found unlocked: check the CCTV, report an incident, the Office Manager follows up |
| **Exception route** | How to get **permission not to follow it**, formally | A cleaner works late: the Office Manager approves in writing, until a set date |
| **Mapping** | Which ISO / NDPA clause it satisfies | ISO 27001 A.7.1 (physical security) |
| **Governing authority** | The bigger document it serves | Physical Security Policy |

Section 5 does the same with the real control ACS-L3-01 from your screenshot.

### "What is in red?"
- **Red "Risk: …" line on a card:** just the control's Risk field, coloured to stand out. **Not an error.**
- **Red box at the bottom of an opened card** (*"The defining document does not state: Mapping"*): the document leaves out a required field. You can still accept; the document should be fixed.
- **"Deficient" badge:** the same thing, a field is missing. It shows as "Fields missing" once the update is deployed.
- **Red Reject button:** just the button colour.

### "What is the use of CDI checks like the one about 'shall'?"
The CDI checks run in Lifecycle **before** approval. They make sure a document is properly built: it has a code, a version, a date, responsibilities, standards references and correct wording. Section 3 lists each check.

**The "shall" check:** it blocks a document that writes an obligation with "should", "where possible", "ideally" and so on. It was added because the **old AI extractor** only treated a sentence as a control if it said "shall" or "must".

**It's now too strict and partly unnecessary:**
- Your own CDI Procedure allows "should" for recommendations and "may" for options, and only *reports* misuse.
- The new reader finds controls by their ID and labels, not by the word "shall".

**Done:** it's now a warning. It still shows the wording so the author can fix it, but it no longer blocks.

### "Does our CDI need to change? What is unnecessary?"

| Change | Why |
|---|---|
| "Shall" check: blocking → warning — **done** | Matches your CDI Procedure (V14); the new reader doesn't need it |
| Lifecycle approval uses the **new reader**, not the old AI extractor — **done** | No more duplicate controls without a Control ID |
| CDI-07 / CDI-08 (vague role / vague evidence) | Already switched off. The role and evidence checks now happen on each control (Blocked status, Record IDs) |
| Approved copies should go **back to the library folder** | Today they're saved somewhere else, so the library sync never sees the approved version |
| **No change needed** to the control pattern itself | Your v06 documents already follow it |

---

**Contents**
1. [The big picture: one way in](#1-the-big-picture-one-way-in)
   - [1a. Document types: who does what](#1a-document-types-who-does-what)
   - [1b. "Defined in" and "Carried out in"](#1b-defined-in-and-carried-out-in)
   - [1c. The Document Standards page](#1c-the-document-standards-page)
2. [Document Lifecycle: the way in](#2-document-lifecycle-the-way-in)
3. [The CDI checks, one by one](#3-the-cdi-checks-one-by-one)
4. [The reader at approval](#4-the-reader-at-approval-what-used-to-be-the-library-sync)
5. [The control pattern: what every field means](#5-the-control-pattern--what-every-field-means)
6. [How OrgOS finds controls in a document, and when it can miss one](#6-how-orgos-finds-controls-in-a-document--and-when-it-can-miss-one)
7. [What could go wrong when reading the library](#7-what-could-go-wrong-when-reading-the-library)
8. [The review pages: what you see and what the colours mean](#8-the-review-pages--what-you-see-and-what-the-colours-mean)
9. [After you accept: registers, evidence, gaps](#9-after-you-accept--registers-evidence-gaps)
10. [Roles](#10-roles)
11. [Rules for writing documents so OrgOS reads them correctly](#11-rules-for-writing-documents-so-orgos-reads-them-correctly)
12. [What was fixed today, and what's next](#12-what-was-fixed-today-and-whats-next)
13. [Words](#13-words)

---

## 1. The big picture: one way in

```
 ORGOS CONTROL LIBRARY (SharePoint)          Owner creates a document / revision,
 a new or changed file                       Gap remediation, Scheduled review, …
        │  SharePoint intake                                   │
        └──────────────────────┬───────────────────────────────┘
                               ▼
                  REVIEW ── CDI checks (format & wording)
                               ▼
                  SENSITISATION ── stakeholders comment
                               ▼
                  APPROVAL ── approver signs
                               ▼
           Published copy + Document Register entry (Active)
                               ▼
     NEW READER — the approved library (every Active document) is read:
       • this document's new / changed controls ──▶ Extraction Review (by Control ID)
       • problems against other APPROVED documents ──▶ Assignment & Ownership
        • Blocked controls re-checked against Org Roles
                               ▼
     You accept ──▶ Control Register · Evidence Tracker · Audit Log ──▶ Gap Analysis · Standards Map
```

- **Drafts never reach the registers.** A file in the library folder is only a document under review, until Lifecycle approves it.
- **Comparisons use approved documents only.** "Copy differs from its Standard" means *the approved Standard*. "Cites an undefined control" means *no approved document* defines it. While a Standard is still in Lifecycle, a procedure that cites its controls will show *cites an undefined control*. That's correct, and the item closes itself when the Standard is approved.
- **The old AI extractor is no longer used at approval.** If an approved document doesn't follow the control pattern, OrgOS adds a note to its Lifecycle item saying no controls were found, rather than guessing.

---

## 1a. Document types: who does what

Each document type has a different job, so OrgOS does something different when each is approved. Using the Identity documents as the example:

| Type | Its job | Identity example | What OrgOS does on approval |
|---|---|---|---|
| **Policy** | **Why**, and who has authority. Management's intent. No controls. | Access Control Policy (DRG-ISMS-POL-ACCESS) | Nothing goes to review. Controls point back to it as their **"Governing authority"** |
| **Standard** | **What** must be done: the controls. Each has an ID and its fields (requirement, trigger, roles, evidence, risk, failure and exception routes, mapping) | Identity Lifecycle and Enterprise Access Standard (DRG-ISMS-STD-IDL) defines ACS-L3-01 to 06 | **Its controls go to Extraction Review.** This is the only place a control is *defined* |
| **Procedure** | **How**, step by step: who does what, in what order | Joiner, Mover and Leaver Access Procedure (DRG-ISMS-PRO-JMLA) | Nothing new to review. OrgOS **links** its steps to the controls they carry out |
| **Specification** | **How, for a system**: technical settings, automation rules | Identity Automation Specification (DRG-ISMS-SPEC-IDAUTO) | Same as a Procedure: linked, not counted |
| **Forms / registers** | **The records**: the forms you fill in, the logs you keep | Access Forms and Registers Set (DRG-ISMS-SPEC-AFRS) | Linked to the controls it supports |

**Where a family has no Standard**, its **Procedure** does the defining. The Context and Interested Parties Procedure is an example. Then that Procedure's controls go to review instead.

**In one line:** Standards **create** controls, Procedures **carry them out**, and Policies **authorise** them. OrgOS reviews the first, links the second, and points back to the third.

The order you approve in matters:
- **Approve the Standard first, then its procedures.**
- If a procedure is approved first, the controls it carries out **wait**. Its Lifecycle item gets a note naming the Standard they're waiting for (e.g. *"ACS-L3-08 waits for DRG-ISMS-STD-AUTH"*), and they come in when that Standard is approved.

---

## 1b. "Defined in" and "Carried out in"

Take **ACS-L3-01**: *"keep a complete identity and account inventory"*.

- **Defined in DRG-ISMS-STD-IDL.** The Standard states the rule in full: requirement, trigger, roles, evidence, risk, failure and exception routes. It's written **once**, there.
- **Carried out in DRG-ISMS-PRO-JMLA §5.3 Leaver.** That section of the procedure is the *how*: when someone leaves, this is how the inventory is kept right. To make the link clear, the procedure repeats the control's ID and a **short copy** of its wording.

**Why approving the procedure raised nothing in Extraction Review:**
- If OrgOS counted the procedure's short copy as a control, the register would hold ACS-L3-01 **twice**, once from the Standard and once from the procedure.
- Bobby's instruction forbids exactly that: *"procedures … must not be counted as additional controls simply because they repeat a requirement."*

**What approving the procedure did instead:**
1. **Linked it.** ACS-L3-01 now shows **"Carried out in: DRG-ISMS-PRO-JMLA §5.3 Leaver"**. If someone asks *how* that control is followed, that's where to read. A control that no procedure carries out shows up as a gap.
2. **Compared its wording with the Standard.** Had the procedure changed the wording, you'd get **"Copy differs from its Standard"** in Assignment & Ownership. It didn't, so nothing was raised.
3. **Found the controls whose Standard isn't approved yet.** JMLA also carries out ACS-L3-08, which belongs to DRG-ISMS-STD-AUTH. That control waits, with a note on the procedure's Lifecycle item.

**The Document Register's "controls defined" count** is the number of controls a document is the definition of. That's 6 for the Identity Standard and 0 for the procedure. Before 20 Oct it wrongly counted the procedure's short copies ("5 extracted candidates").

---

## 1c. The Document Standards page

A new page in the main menu, **Document Standards**, has three tabs.

**The standard** (everyone). What every controlled document must meet, read from the CDI Procedure itself (its 24 validation checks V01 to V24, the sections a document needs, Annex A for the document's register card, Annex C for a control, and Annex B's reference lists). Pick a document type (Policy, Standard, Procedure…) to see what it must contain and which checks apply. The page says which checks OrgOS enforces today, and lists the ones it does not, with what each is waiting for.

**Check a document** (everyone). Upload a .docx or .pdf and see how it fares. **Nothing is saved**, so it can be used while writing. Every check gives one of seven answers: *passed*, *blocking problem*, *needs a decision*, *for your attention*, *could not check* (and why), *not applicable* (and why), or *not built yet*. A check that could not look never passes, and a clear result is never presented as a full clearance while checks remain unbuilt.

**Convert to CDT** (Compliance only). Brings an existing document onto the controlled template, so its code, owner, approvers, version and dates live in the Register and the file cannot drift from it.
1. Pick a document in Lifecycle Review (or upload a file to try it).
2. **Read and prove.** OrgOS reads the document's header block and builds the converted file in memory. Nothing is saved.
3. It shows exactly what changes:
   - **Taken out**: only the header rows the cover regenerates (title, code, layer, domain, parent, owner, approvers, classification, distribution, version, dates, status).
   - **Stays, unchanged**: every other header row (controls implemented, supersedes, related and child documents, standards, review cycle). The cover has no place for them and OrgOS reads them from the file; removing them changed how 42 real documents were read, which the proofs caught.
   - **The new cover**, and **what is not carried across** (a hand-typed version or date; a draft has none, approval stamps them).
   - Anything else that needs your attention (tracked changes, lists, page header and footer text that the template replaces).
4. Five **proofs** are run on the converted file, and **nothing is offered unless all hold**:
   - *body*: every body element is identical to the original;
   - *removed*: nothing was lost except rows the cover regenerates;
   - *reads-same*: OrgOS reads the same code, title, relationships and control definitions after as before;
   - *sound*: no link or list points at anything that no longer exists;
   - *merges*: the cover fills in completely.
5. **Convert this document.** The converted file becomes the Lifecycle item's **own working copy**, named as its title; the cover facts are saved on the item; the CDI checks re-run. **The original file is never changed or deleted.**

**What conversion will not do:** invent anything. A document that states no title or code, has no header block (its facts written as "Label: value" lines), has no template for its type (registers, forms), or opens with text it cannot place, is refused with the reason. On your real library, **84 of 123 documents convert with every proof holding; the other 39 are refused with the reason**, and no document fails a proof.

**What is not built yet:** 11 of the 24 checks (V05 to V07 need the Role Register; V13, V16 to V21 and V24 are not written). The old CDI checker in Lifecycle Review still runs on upload; the new checks are not yet part of the Review gate.

---

## 2. Document Lifecycle: the way in

A document goes through three stages: **Review → Sensitisation → Approval.**

### How a document enters Lifecycle
- An owner creates it by hand, or starts a **revision** of an existing approved document.
- The **Policy Drafter** (AI writes a first draft).
- **Gap Analysis**: a gap needs a new or changed document ("Gap Remediation").
- A **review-queue decision**, e.g. "Revise the procedure" in Assignment & Ownership.
- The **daily 08:00 job**: a document's review date is within 30 days ("Scheduled Review").
- The **SharePoint intake script** (`scripts/intake_sharepoint_to_lifecycle.py`): picks up new files in ORGOS CONTROL LIBRARY, runs the CDI checks, and opens a Lifecycle entry for each. **This is how the library's drafts reach Lifecycle.** It's designed to run at 06:00 and 20:00 via `scripts/setup_intake_cron.sh`. Check whether it's installed on the server with `crontab -l`. If nothing about intake is listed, it isn't scheduled.

### Stage 1: Review (the owner)
- The owner uploads the document. **The CDI checks run automatically** (section 3).
- **A "Document standard" panel** on the Review card runs the CDI Procedure's own checks (V01–V24) on the file, on request, and says where each problem is. Compliance decides any flagged check, with a reason. By default it is **advisory**: it shows what would stop the document without stopping it. When the gate is switched to **enforce**, a blocking problem, or a flag nobody has decided, stops the move to Sensitisation and stops approval. The old CDI checks still run beside it. See the go-live checklist, section 10.
- **Or edits it in the browser: "Edit in Word ↗"** opens the document in Word for the web, and it saves as you type.
  - Editing always happens on **this item's own working copy**. For a revision, OrgOS first copies the approved published file and edits the copy, so **the approved version is never changed**. A draft from the library folder is copied the same way.
  - When you've finished, click **"Done editing — re-check"** to run the CDI checks on the saved file.
  - Available in Review only, to the owner or Compliance. Only Word (.docx) files can be edited this way; for a PDF, upload a .docx.
- OrgOS can propose fixes. Some apply automatically, e.g. the wrong document-code format or a missing version.
- The owner can attach a **CDT cover**, the standard front page with code, version, effective date, approvals and revision history.
- **To move on:** a file is uploaded, the CDI result isn't *Failed*, and stakeholders are chosen.
  - ⚠ The screen currently lets you click *Progress* even when CDI failed, because the screen check was switched off. The server still refuses, so you get an error message instead of a disabled button.

### Stage 2: Sensitisation (the stakeholders)
- Stakeholders get a Teams message (via Power Automate) with a **read-only PDF link**, so nobody edits the controlled Word file.
- They leave feedback before a deadline (7 days by default). The owner can extend it.
- OrgOS can draft amendments from the feedback.
- **To move on:** an approver is chosen. If the owner chooses "skip approver", the document is **approved immediately**.

### Stage 3: Approval (the approver)
- **Approve** does the following:
  1. Stamps the cover from the Register: the version and dates follow the approver's choice (see "Versions" below), and a revision-history line is added.
  2. Saves a **published copy** to the OrgOS site under *Lifecycle Documents*.
  3. Creates or updates the **Document Register** entry (R01, R02…).
  4. **Reads the approved library with the new reader** (section 1). This document's new and changed controls go to Extraction Review, and problems against other approved documents go to Assignment & Ownership. If anything goes wrong (e.g. a published copy can't be downloaded), **nothing is written** and a note on the Lifecycle item says how to retry: `python scripts/sync_control_library.py --apply`.
- **Reject** needs a reason (20+ characters). The document goes back to Review.
- The owner can recall it, and Compliance can reverse an approval.

### Versions: one number, and what approval does to it
There is **one** version number, written **01, 02, 03…** with no "R". It follows CDI Procedure §12 and §14.

- A **draft has no version.** The number is given when the document is issued.
- The **Document Register is the master** of the version, the effective date, the next review date and the approver. Approval **stamps the cover from the Register**; nobody types them into the file.

**When someone approves a document, they say how it treats the version:**

| Situation | Choices |
|---|---|
| **First issue** | It becomes **version 01**. The approver writes what the document is and why it is being issued |
| **A revision** (including a scheduled review) | **New version**: a real change; the number goes up and both dates move. **Correction, no new version**: a typo, a broken cross-reference or formatting; nothing moves, it is logged. **Annual review, no change**: the version stays and only the next review date moves |

- A **new version needs a change summary** (at least 20 characters) saying what changed and why. "Issued for use", "Approved", "Updated" and similar are refused: CDI §14.2 says they don't count. A correction needs a short note saying what was corrected. An annual review needs no words; it is logged as "Annual review, no change".
- The choice is made on the approval screen, and also when the approver is skipped (skipping approves and publishes, so it needs the same choice). It is checked **before** anything moves, so a refusal never leaves a document stranded in Approval.
- The approval preview shows what the choice will do before you confirm it, for example "version 02 → 03, new effective date and review date".

**Things to know:**
- A first issue is always **01**, even if the cover has a hand-typed version such as "05". The approval preview warns when that will happen. If the document already had issued versions elsewhere, say so in the change summary. (Convert to CDT drops a hand-typed version for the same reason.)
- Existing Register entries written as "R02" are still read correctly. `python scripts/migrate_versions.py` (dry run first) rewrites them as "02".

### What's still open
- **The published copy doesn't go back to the library folder.** It's saved under *Lifecycle Documents* on the OrgOS site, and that's the copy the reader uses. The folder keeps the draft. Whether approved copies should replace the folder file is for the document-standards discussion.

---

## 3. The CDI checks, one by one

CDI is the house standard for how a document is written ("Control of Documented Information"). The checks run in Review, and **only "Blocking" ones stop a document moving on.**

| Check | What it looks for | Blocking? | Why it matters |
|---|---|---|---|
| CDI-01 Document code | A valid code like `DRG-ISMS-STD-IDL` | **Yes** | It's the document's key in every register |
| CDI-02 Revision history | A revision-history table | No | Shows what changed and when |
| CDI-03 Purpose | A purpose section | No | |
| CDI-04 Scope | A scope section | No | |
| CDI-05 Responsibilities | A roles / responsibilities section | **Yes** | Without it nobody owns the controls |
| **CDI-06 Wording** | Obligations written with "shall" / "must", not "should", "where possible", "ideally", etc. | No (warning since 19 Oct) | See below |
| CDI-07 / 08 | Vague role / vague evidence | Switched off | |
| CDI-09 Standards | Mentions ISO 27001 / 9001 / NDPA, or a clause like A.5.15 | **Yes** | Feeds the Standards Map |
| CDI-10 Related documents | Section present | No | |
| CDI-11 Classification | e.g. "Internal use only" | No | |
| CDI-12 Owner | Document owner / approver named | No | |
| CDI-14 Effective date | A real date | Yes, once versioned | |
| CDI-15 Version | A real version number | **Yes** | Versioning and covers depend on it |

For the wording and section checks, an AI looks first. A second AI opinion can turn a fail into a pass, never the other way. If the AI is down, simple word-matching is used instead.

### The "shall" rule (CDI-06), and why it needs changing
**What it does:** it flags any obligation written with "should", "ideally", "where possible", "as appropriate" and so on, and asks for "shall" or "must". It used to **block** the document; it's now a warning.

**Why it exists:** the old AI extractor only recognised a sentence as a control if it said *shall / must / is required to / will*. A "should" sentence was invisible to it.

**The problem:** your own CDI Procedure (§7.5) says: *"SHALL or MUST means mandatory; SHOULD means recommended; MAY means optional. Do not use should where shall is meant."* Its check **V14** only **reports** misuse; it doesn't block. The CDI Standard says Guidelines *use should and may*. So OrgOS is **stricter than your own standard**. It can block a Guideline or Standard that uses "should" correctly for a recommendation.

**And it's no longer needed for its original reason.** The new reader (section 6) finds controls by their **Control ID and labelled fields**, not by the word "shall".

**Done:** CDI-06 is now a warning, as V14 says. Checking normative words properly, inside each control's Requirement, belongs to the document-standards engine (section 12).

**Note on "shall log → logs"** in your Assignment & Ownership screenshot: that isn't the CDI-06 check. It's the *"copy differs"* comparison (section 8), which flags any change in wording when a procedure copies a control.

---

## 4. The reader at approval (what used to be the "library sync")

**What it reads:** every document the **Document Register** holds as current, from its **published copy**:
- **Active:** approved and in force.
- **Under Review:** a revision is in Lifecycle, and the approved version still governs.
- Withdrawn and Superseded documents, and anything not yet approved, are not read.

**When:** automatically, every time Lifecycle approves a document. By hand: `python scripts/sync_control_library.py` (a dry run that prints a summary; `--apply` to write). Use it to retry after a failed approval note, or after the Role Catalogue changes, so Blocked controls are re-checked.

**What it does:**
1. Reads each approved document: its code, type (Standard, Procedure, Policy, …), and the controls it defines or carries out.
2. Works out **which document defines each control**. A Standard beats a Procedure, which beats a Policy. If two equally ranked documents both define it, the one that states more fields wins. If they tie exactly, the control is **not synced** and a *Defined twice* item is raised.
3. Compares each control with the Control Register:
   - **unchanged:** nothing happens;
   - **new:** a review item;
   - **changed:** a review item showing what changed.
4. Checks approved documents against each other and against the Records Catalogue, and raises Zone 2 items (section 8).
5. Closes Zone 2 items whose problem has gone, and re-checks every Blocked control's role.
6. **If any approved document can't be downloaded, nothing is written.** A missing document would make its controls look deleted.

**To survey the library folder itself**, drafts included, without writing anything, use `python scripts/cdi_library_census.py`. It prints every document, how it was read, and every problem found. That's useful before approving documents.

---

## 5. The control pattern: what every field means

This is control **ACS-L3-01** from your screenshot, field by field.

| Field | What it means | ACS-L3-01 says |
|---|---|---|
| **Control ID** | The control's permanent name. Never reused. OrgOS keys everything on it. | `ACS-L3-01` |
| **Title** | A short name | *Identity and account inventory* |
| **Requirement** | **The rule itself**: who must do what, by when | *The Information Security Officer shall maintain a unique … inventory … no later than 24 hours after creation …* |
| **Trigger** | **When the rule kicks in**: an event or a schedule | *Creation; authoritative HR or approved app/service event.* |
| **Control owner** | The **one** role answerable for the control and its evidence. It must be a role that exists in Org Roles. | *Information Security Officer* |
| **Evidence** | **The proof the rule was followed**, ideally with Record IDs | *Account inventory entry and identity creation log. Record IDs: REC-0691; REC-0692.* |
| **Risk** | **What goes wrong if the rule isn't followed**, i.e. why the control exists | *An account could remain unidentified … resulting in uncontrolled privilege …* |
| **Failure route** | **What happens when the control has failed**: the clean-up and who fixes it | *Quarantine an unowned identity; IT reconciles the inventory and the ISO opens a gap …* |
| **Exception route** | **How someone gets formal permission not to follow the rule**: who records it, where, for how long | *The ISO records scope, reason, compensating measure, owner, expiry … in REC-0696 …; high-rated acceptance requires ExCo.* |
| **Mapping** | **Which standard clauses this control satisfies**, e.g. ISO 27001 A.5.16 | *(not stated — that's why the card says "Fields missing")* |
| **Governing authority** | The higher document this control serves | *DRG-ISMS-POL-ACCESS Access Control Policy.* |

In short, the difference between the last few:
- **Risk** answers *why the rule exists*.
- **Failure route** answers *what we do when it breaks*.
- **Exception route** answers *how you're allowed not to follow it*.
- **Mapping** answers *which ISO / NDPA clauses it counts towards*.

**Required fields** (CDI): Requirement, Trigger, Control owner, Evidence, Risk, Failure route, Exception route, Mapping. Title and Governing authority are optional. If any required field is missing, the card is marked **Fields missing** (shown as "Deficient" until the frontend update is deployed), with the red note *"The defining document does not state: …"*.

---

## 6. How OrgOS finds controls in a document, and when it can miss one

**No AI is used.** OrgOS recognises structure. That's why the result is exact, and also why **the documents must follow the pattern.**

### What it recognises
1. **A control heading:** a line that is a Control ID, optionally followed by a title, e.g. `ACS-L3-01 Identity and account inventory`. The ID looks like `ABC-01`, `ACS-L3-01` or `IT-09`. Word heading styles aren't needed.
2. **Labelled fields under it:** `Requirement:`, `Trigger:`, `Control owner:`, `Evidence:`, `Risk:`, `Failure route:`, `Exception route:`, `Mapping:`, `Governing authority:`, and the common alternatives (e.g. "Control statement", "Risk treated", "Standards mapping").
   - Labels can be paragraphs, a two-column table, or columns of a table with one control per row (first column "Control ID", plus a requirement column).
3. **Record IDs:** any `REC-` followed by four digits, in Evidence, in a "Record IDs" field, or in a records table.
4. **Procedures that carry out a control:** a heading ending "(ACS-L3-01)", a line "Implements ACS-L3-01, ACS-L3-02", "This procedure implements …", a "Controls implemented" field, or a control-map table. Ranges like "CM-01 to CM-06" work.

It also handles PDFs (as long as they contain real text) and accepts Word tracked changes as if they were accepted.

### When a control can be missed or misread

| Situation | What happens today |
|---|---|
| A block has **fewer than 3** of the main fields | **Not counted as a control. Silently dropped** (unless it's in a Procedure) |
| A label is **misspelled**, e.g. "Requirment:" | The field shows as missing. If that leaves fewer than 3 fields, the control is dropped silently |
| The **same ID twice** in one document | Only the first is read |
| **No pattern at all** (plain prose) | No controls found from that document |
| **Scanned PDF** (a picture, no text) | Nothing read, and no warning in the sync |
| A PDF table row that can't be lined up | That row is dropped |

The reader *does* record each of these as a finding. But **the sync doesn't show them to anyone yet.** Only the separate census script prints them. Showing them to authors is the job of the document-standards engine (section 12).

**How good is it today?** Across the real library, the reader understands about **98% of the control layouts** in use (it was 60% before the reader was rewritten). The remaining 2% are documents with no control structure.

---

## 7. What could go wrong when reading the library

| Scenario | What happens | Handled? |
|---|---|---|
| A file **fails to download** during the run | Previously its controls looked deleted, so pending items could be closed by mistake and false "cites an undefined control" items raised. **Now the run refuses to write and asks you to re-run.** | ✅ Fixed today |
| A **draft** sits next to the final version | Drafts aren't read for controls any more; only the approved, published copy is | ✅ Fixed |
| Every document is a **draft** (true today) | No controls until documents are approved in Lifecycle | ✅ By design now |
| A file sits **loose in the top folder** of ORGOS CONTROL LIBRARY | Intake and census only look in subfolders | ⚠ Keep files in subfolders, or we change it |
| A document is **moved** between subfolders | No effect, which is fine | ✅ |
| A document is **deleted**, or a control is **removed** from it | The register keeps the control. The script prints "no longer defined" but **nothing is withdrawn**, deliberately, so a deletion can't silently remove a control. Procedures still citing it get flagged | ⚠ Retiring should be a Lifecycle decision; not built yet |
| **Two Standards define the same ID** | The one with more fields wins quietly. Only an exact tie raises *Defined twice* | ⚠ Should always raise it |
| `.doc`, password-protected or corrupt file | Shown as UNREADABLE with the reason; skipped | ✅ Listed in the output |
| SharePoint unreachable at the start | The whole run stops; nothing is written | ✅ |
| A document has **no code** | It's shown by its file name, e.g. *IT and Infrastructure Control Standard*. Type is guessed from the title ("Standard" → STD) | ⚠ Give every document a code |
| A procedure **rewords** a copied control | *Copy differs from its Standard* (section 8) | ✅ |
| A document cites a **REC ID not in the Catalogue** | *Record not in the Catalogue* | ✅ Once the Catalogue is imported |

---

## 8. The review pages: what you see and what the colours mean

### Extraction Review (Zone 1): one card per control

| Part of the card | Meaning |
|---|---|
| Blue tag `ACS-L3-01` | Control ID |
| **New** / **Changed** | Never seen before / the document's wording changed since it was accepted |
| **Fields missing** (amber) | The document leaves out some required fields; the red note says which |
| Grey title, then bold text | The control's title and its Requirement |
| **Red "Risk: …" line** | The control's Risk field: what goes wrong without it. Red only to stand out, **not an error** |
| "From document" | Read from the document, not guessed by AI, so there's no confidence score |
| Blue "If accepted" box | Exactly what Accept will create |
| **Red box at the bottom** | The fields the document doesn't state. You may still accept; the fix belongs in the document |

**What the buttons do**
- **Accept:** enters the control in the Control Register, as written.
- **Reject:** it doesn't go in. If the document is unchanged, OrgOS won't ask again.
- **Mark false positive:** this isn't a real control.
- **Request 2nd review:** ask another colleague.

**Accept all (per document):** the same as accepting each card, with one rationale shared. Changed controls are always reviewed one by one.

### Assignment & Ownership (Zone 2): problems between documents

| Label | Meaning | Your choices |
|---|---|---|
| **Copy differs from its Standard** | A procedure copies a control but changed the words. OrgOS ignores capital letters and punctuation; any other change in a near-identical copy is flagged, including "shall log" → "logs". The Standard's wording prevails. | *Revise the procedure* (sends a task to Document Lifecycle) or *Accept the difference* (the wording is deliberately different) |
| **Cites an undefined control** | A procedure carries out a control (e.g. DP-002) that no document defines, usually because it was retired | *Revise the procedure* or *Define it in its Standard* |
| **Record not in the Catalogue** | A REC ID that doesn't exist | *Correct the citation* |
| **Cites a withdrawn record** | A REC ID that was retired as a duplicate | *Correct the citation* |
| **Two files, one code** | Probably an old copy left in the library | *Withdraw or recode* |
| **Defined twice** | Two equally ranked documents define the same ID | Choose the governing document |

**About your screenshot:** all four *Copy differs* items compare against *"IT and Infrastructure Control Standard **Draft**.docx"*, a draft with no document code. The comparison is correct, and the IT procedures do differ from it. But if that draft isn't the version you mean to keep, fix the Standard first, then decide these. The DP-002 items are real: DP-002 was retired and three procedures still cite it.

These items **close themselves** on the next sync once the documents are fixed.

---

## 9. After you accept: registers, evidence, gaps

1. **Control Register:** one row per Control ID, created or updated, never duplicated.
    - **Active** if its Control owner is a role in Org Roles.
   - **Blocked**, with the reason, if not. Today most will be Blocked (section 10).
2. **Evidence Tracker:** one *evidence obligation* per record the control names, e.g. "REC-0691 must exist for ACS-L3-01".
   - It starts **Unscheduled** until Compliance sets how often it's checked. OrgOS suggests a frequency for 62; it never guesses the rest.
   - A **daily job at 07:30** sets each obligation's state: OK, Due soon, Late, Missing, Stale, Rejected.
   - A Power Automate flow (still to be set up) can notify owners.
3. **Audit Log:** who decided, when, why.
4. **Gap Analysis** (runs every 3 days, or on demand): finds controls with no owner, missing fields, nobody carrying them out, unknown records, and so on. These gaps **close themselves** when fixed.
5. **Standards Map:** green / amber / red per ISO / NDPA clause. It depends on **Mapping**, so controls with no mapping don't appear against any clause.

---

## 10. Roles

**A role counts as recognised only if it is a role in Org Roles** (by its name or an agreed alias). A Microsoft job title alone doesn't count; Bobby was clear on that. A name like *"Control Owner"*, *"Document Owner"* or *"Custodian Role"* is the name of a field, not a role, so a control that says it stays **Blocked** until its document names a real role. That's safe: the control is recorded, evidence is tracked, and the reason is shown.

**How a document gets its roles right:**
1. **Org Roles is the role register.** It is loaded from the job descriptions and the staff register; people are added to roles. There is no separate organogram step.
2. **While a document is in Review, the Document standard panel (V07) lists every role it names that does not exist**, with the nearest existing roles. The author can **Use this role** (the document text is changed to the official name), choose another, **keep the wording as an alias** (Compliance), or **Create role** (opens Org Roles with the name filled in).
3. **The next library sync re-checks every Blocked control** and turns it Active by itself if its role is now recognised. Nothing needs accepting again.
4. **Real people become answerable:** evidence reminders and gaps go to the people who hold the role. When someone changes job, you change the role's members once and every control follows.
5. **What's still Blocked is a real document problem** (no Control owner, a field name in its place, or a role that doesn't exist) and becomes a gap for the document owner.

**What we need:** for each role, its title, department, who it reports to, who holds it (name or email), whether it's vacant, and who is acting in it and until when. Any format is fine.

---

## 11. Rules for writing documents so OrgOS reads them correctly

**Yes, the control pattern has to be a drafting rule.** Your CDI v06 Standard already uses it; this list just makes it explicit for authors.

1. **Every document has a code**, e.g. `DRG-ISMS-STD-IDL`, in the header's *Document code* field. Never "Not assigned".
2. **Each control starts with its ID on its own line**, optionally followed by the title: `ACS-L3-01 Identity and account inventory`.
3. **Use the standard labels**, spelled exactly, each followed by a colon:
   `Requirement:` · `Trigger:` · `Control owner:` · `Evidence:` · `Risk:` · `Failure route:` · `Exception route:` · `Mapping:` · `Governing authority:` (optional)
4. **One Control owner**, named exactly as the role is in Org Roles. One role, not two ("X and Y").
5. **Cite records by ID**: `Record IDs: REC-0691; REC-0692`.
6. **Mapping names the clause**: `Mapping: ISO 27001 A.5.16; NDPA s.39`.
7. **A control is defined in exactly one document**, normally the Standard. **Procedures cite it by ID** (`Implements ACS-L3-01`). If they copy the requirement, they copy it word for word.
8. **Retired IDs are never reused**, and documents that cite them are updated.
9. **Save as .docx**, not .doc. PDFs must contain real text, not a scan.
10. **Keep files in a subfolder** of ORGOS CONTROL LIBRARY, never loose at the top.
11. **Drafts can stay in the library folder.** They reach Lifecycle through intake, and only approved copies are read for controls. Old, replaced copies should still be removed.
12. Use **shall / must** for obligations, **should** only for recommendations, and **may** for options, as CDI §7.5 says.

---

## 12. What was fixed today, and what's next

### Fixed today
- **Extraction Review's Accept button was broken.** It called a server endpoint that had been removed.
- **Control definitions now display properly on the review pages you use:** Control ID, New / Changed, the full definition, and a correct "If accepted" preview.
- **Library findings were all labelled "JD → No policy".** Each kind now has its own label and choices.
- **A failed download during a sync** could close review items by mistake. The sync now refuses to write when the read is incomplete.
- **Approving a document set its next review date to the sensitisation deadline**, so the daily review job immediately opened a review for it. Now it's set a year after the effective date.
- **Approving a scheduled review created a second Document Register entry** instead of updating the existing one. Fixed.

### Done after your decisions
- **One way in.** Approval reads the approved library with the new reader. The old AI extractor no longer runs on approval or in the approval backfill script (`publish_approved_lifecycle.py`), and `reextract_by_code.py` is removed.
- **CDI-06 is a warning.**
- **Cleanup script for the draft-derived queue items:** `python scripts/retire_draft_library_items.py`, a dry run that lists them. Add `--apply` to retire them as Superseded with an explanatory note. Decided items and the old extractor's items are left alone.

### For the document-standards discussion (later)
A **document-standards engine**, separate from CDI, that checks a document **fits the control pattern** before approval, so nothing is missed silently:
- controls with too few fields, misspelled labels, the same ID twice;
- scanned PDFs, .doc files, files loose in the top folder;
- missing code, two Standards defining one ID;
- Record IDs that don't exist;
- normative words (shall / should / may) used correctly inside each Requirement;
- the controlled document templates (CDT).

The reader already detects most of these per document (`scripts/cdi_library_census.py` prints them). The engine would show them to the author in Lifecycle Review and could block approval on the serious ones.

Also for then:
- **The other old-extractor tools.** The Extractor page, "extract" in the SharePoint browser and `bulk_extract.py` still use the old AI extractor. They also handle contracts, job descriptions, regulations and audit reports, which aren't CDI control documents, so whether they stay is part of that discussion.
- **Whether approved copies should replace the folder file.**

---

## 13. Words

| Word | Meaning |
|---|---|
| **CDI** | *Control of Documented Information*: Dragnet's standard for how documents are written, coded, approved and kept |
| **CDT cover** | The standard front page: code, version, dates, approvals, revision history |
| **Standard / Procedure / Policy** | Standard *defines* controls; Procedure says *how* to carry them out; Policy sets the *intent* |
| **Control** | One rule someone must follow, with its ID |
| **Records Catalogue** | The master list of 729 records (REC-nnnn), imported from the Enterprise Records Catalogue spreadsheet |
| **Evidence obligation** | "Record Y must exist for control X, checked every N days" |
| **Active / Blocked** | Has a recognised owner / doesn't yet (the reason is shown) |
| **Zone 1 / Zone 2** | Extraction Review (controls) / Assignment & Ownership (problems between documents) |
| **Approved library** | Every document the Document Register holds as Active or Under Review, read from its published copy |
| **Old extractor** | The earlier AI that guesses controls from text; no longer used at approval |
