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
**Yes.** OrgOS doesn't "understand" text; it recognises **labels**. A control is a line with its ID (e.g. `ACS-L3-01`) followed by labelled lines: `Requirement:`, `Trigger:`, `Accountable / Executing:`, `Evidence:`, `Risk:`, `Failure route:`, `Exception route:`, `Mapping:`. Your CDI v06 Standard already uses this pattern, so it's not new work. It just has to be followed every time. Section 11 is the 12-rule checklist for authors.

### "Is the Responsibilities section where the controls, or the Accountable role, are checked?"
**No, they're two different things:**
- **The Responsibilities section** (CDI-05) is a **document-level** list near the front: *who has which duties under this document* (Document Owner, Information Security Officer, …). CDI-05 only checks that the section exists.
- **The Accountable / Executing line** sits **inside each control**. It says who answers for, and who carries out, *that one control*. It's what decides whether a control is **Active** or **Blocked** (section 10).

The reader also uses the Responsibilities (Roles) table: its role names help it work out where "Accountable / Executing" splits into two roles, and later they'll seed the Role Catalogue.

### "What does each field mean — trigger, failure route, exception route…?"
Imagine the control *"lock the office door"*:

| Field | Plain meaning | Door example |
|---|---|---|
| **Requirement** | The rule | The last person out shall lock the front door |
| **Trigger** | When the rule applies | Every evening, when the last person leaves |
| **Accountable** | The one person who answers for it | Office Manager |
| **Executing** | Who actually does it | Whoever leaves last |
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
2. [Document Lifecycle: the way in](#2-document-lifecycle-the-way-in)
3. [The CDI checks, one by one](#3-the-cdi-checks-one-by-one)
4. [The reader at approval](#4-the-reader-at-approval-what-used-to-be-the-library-sync)
5. [The control pattern: what every field means](#5-the-control-pattern--what-every-field-means)
6. [How OrgOS finds controls in a document, and when it can miss one](#6-how-orgos-finds-controls-in-a-document--and-when-it-can-miss-one)
7. [What could go wrong when reading the library](#7-what-could-go-wrong-when-reading-the-library)
8. [The review pages: what you see and what the colours mean](#8-the-review-pages--what-you-see-and-what-the-colours-mean)
9. [After you accept: registers, evidence, gaps](#9-after-you-accept--registers-evidence-gaps)
10. [Roles and the organogram](#10-roles-and-the-organogram)
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
       • Blocked controls re-checked against the Role Catalogue
                               ▼
     You accept ──▶ Control Register · Evidence Tracker · Audit Log ──▶ Gap Analysis · Standards Map
```

- **Drafts never reach the registers.** A file in the library folder is only a document under review, until Lifecycle approves it.
- **Comparisons use approved documents only.** "Copy differs from its Standard" means *the approved Standard*. "Cites an undefined control" means *no approved document* defines it. While a Standard is still in Lifecycle, a procedure that cites its controls will show *cites an undefined control*. That's correct, and the item closes itself when the Standard is approved.
- **The old AI extractor is no longer used at approval.** If an approved document doesn't follow the control pattern, OrgOS adds a note to its Lifecycle item saying no controls were found, rather than guessing.

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
  1. Updates the cover: version goes up (Draft → 01 → 02…), effective date = today, next review = one year later, and a revision-history line is added.
  2. Saves a **published copy** to the OrgOS site under *Lifecycle Documents*.
  3. Creates or updates the **Document Register** entry (R01, R02…).
  4. **Reads the approved library with the new reader** (section 1). This document's new and changed controls go to Extraction Review, and problems against other approved documents go to Assignment & Ownership. If anything goes wrong (e.g. a published copy can't be downloaded), **nothing is written** and a note on the Lifecycle item says how to retry: `python scripts/sync_control_library.py --apply`.
- **Reject** needs a reason (20+ characters). The document goes back to Review.
- The owner can recall it, and Compliance can reverse an approval.

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
| **Accountable / Executing** | **Accountable** = answers for it (one role). **Executing** = does the work. | *Information Security Officer; IT and application owners.* |
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

**Required fields** (CDI): Requirement, Trigger, Accountable / Executing, Evidence, Risk, Failure route, Exception route, Mapping. Title and Governing authority are optional. If any required field is missing, the card is marked **Fields missing** (shown as "Deficient" until the frontend update is deployed), with the red note *"The defining document does not state: …"*.

---

## 6. How OrgOS finds controls in a document, and when it can miss one

**No AI is used.** OrgOS recognises structure. That's why the result is exact, and also why **the documents must follow the pattern.**

### What it recognises
1. **A control heading:** a line that is a Control ID, optionally followed by a title, e.g. `ACS-L3-01 Identity and account inventory`. The ID looks like `ABC-01`, `ACS-L3-01` or `IT-09`. Word heading styles aren't needed.
2. **Labelled fields under it:** `Requirement:`, `Trigger:`, `Accountable / Executing:`, `Evidence:`, `Risk:`, `Failure route:`, `Exception route:`, `Mapping:`, `Governing authority:`, and the common alternatives (e.g. "Control statement", "Risk treated", "Standards mapping").
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
   - **Active** if its accountable role is recognised.
   - **Blocked**, with the reason, if not. Today most will be Blocked (section 10).
2. **Evidence Tracker:** one *evidence obligation* per record the control names, e.g. "REC-0691 must exist for ACS-L3-01".
   - It starts **Unscheduled** until Compliance sets how often it's checked. OrgOS suggests a frequency for 62; it never guesses the rest.
   - A **daily job at 07:30** sets each obligation's state: OK, Due soon, Late, Missing, Stale, Rejected.
   - A Power Automate flow (still to be set up) can notify owners.
3. **Audit Log:** who decided, when, why.
4. **Gap Analysis** (runs every 3 days, or on demand): finds controls with no owner, missing fields, nobody carrying them out, unknown records, and so on. These gaps **close themselves** when fixed.
5. **Standards Map:** green / amber / red per ISO / NDPA clause. It depends on **Mapping**, so controls with no mapping don't appear against any clause.

---

## 10. Roles and the organogram

**Today** a role counts as recognised only if it matches an **OrgOS group** (Org Roles page). A Microsoft job title alone doesn't count; Bobby was clear on that. Documents also use roles like *"Accountable Department Head"*, or two roles at once (*"Information Security Officer; HR and application owner"*). So **most accepted controls will be Blocked for now.** That's safe: the control is recorded, evidence is tracked, and the reason is shown.

**When the organogram arrives:**
1. It becomes the **Role Catalogue**: each role with its holder, any acting holder and until when, vacancy, and who it reports to. The *Roles* tables in the documents are added with their duty descriptions.
2. **Different spellings are linked to one role.** "Head of IT", "IT Head" and "Head of IT and Infrastructure" become one. Spellings OrgOS can't place go to Assignment & Ownership with suggested matches. Choosing one teaches OrgOS that spelling for next time.
3. **The next library sync re-checks every Blocked control** and turns it Active by itself if its role is now recognised. Nothing needs accepting again.
4. **Real people become answerable:** evidence reminders and gaps go to actual people. When someone changes job, you change the role holder once and every control follows.
5. **What's still Blocked is a real document problem** (no accountable role, or two named) and becomes a gap for the document owner.

**What we need:** for each role, its title, department, who it reports to, who holds it (name or email), whether it's vacant, and who is acting in it and until when. Any format is fine.

---

## 11. Rules for writing documents so OrgOS reads them correctly

**Yes, the control pattern has to be a drafting rule.** Your CDI v06 Standard already uses it; this list just makes it explicit for authors.

1. **Every document has a code**, e.g. `DRG-ISMS-STD-IDL`, in the header's *Document code* field. Never "Not assigned".
2. **Each control starts with its ID on its own line**, optionally followed by the title: `ACS-L3-01 Identity and account inventory`.
3. **Use the standard labels**, spelled exactly, each followed by a colon:
   `Requirement:` · `Trigger:` · `Accountable / Executing:` · `Evidence:` · `Risk:` · `Failure route:` · `Exception route:` · `Mapping:` · `Governing authority:` (optional)
4. **One accountable role**, named as in the organogram. Use "Accountable: X; Executing: Y", not "X and Y".
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
