# How OrgOS works — the complete explainer

*19 Oct 2026. Written in plain words. Everything here was checked against the code, not taken from earlier plans. Where the code falls short of what it should do, this guide says so.*

**Contents**
1. [The big picture: two ways in](#1-the-big-picture-two-ways-in)
2. [Way in #1: Document Lifecycle](#2-way-in-1--document-lifecycle)
3. [The CDI checks, one by one](#3-the-cdi-checks-one-by-one)
4. [Way in #2: the library sync](#4-way-in-2--the-library-sync)
5. [The control pattern: what every field means](#5-the-control-pattern--what-every-field-means)
6. [How OrgOS finds controls in a document, and when it can miss one](#6-how-orgos-finds-controls-in-a-document--and-when-it-can-miss-one)
7. [What could go wrong when reading the library](#7-what-could-go-wrong-when-reading-the-library)
8. [The review pages: what you see and what the colours mean](#8-the-review-pages--what-you-see-and-what-the-colours-mean)
9. [After you accept: registers, evidence, gaps](#9-after-you-accept--registers-evidence-gaps)
10. [Roles and the organogram](#10-roles-and-the-organogram)
11. [Rules for writing documents so OrgOS reads them correctly](#11-rules-for-writing-documents-so-orgos-reads-them-correctly)
12. [What was fixed today, and the decisions that are yours](#12-what-was-fixed-today--and-the-decisions-that-are-yours)
13. [Words](#13-words)

---

## 1. The big picture: two ways in

OrgOS has **two separate ways** a document's controls can get in. That's the most important thing to understand, because **they aren't joined up yet.**

```
 WAY 1 — Document Lifecycle                  WAY 2 — Library sync
 (one document at a time, with people)       (the whole library at once, a script)

 Owner uploads a document                    ORGOS LIBRARY › ORGOS CONTROL LIBRARY
        │                                     (SharePoint, all subfolders)
        ▼                                            │
 REVIEW ── CDI checks (format & wording)             ▼
        │                                     Read every .docx / .pdf
        ▼                                     Find the control blocks (no AI)
 SENSITISATION ── stakeholders comment               │
        │                                            ▼
        ▼                                     New / changed controls ──▶ Extraction Review
 APPROVAL ── approver signs                   Problems between documents ──▶ Assignment & Ownership
        │
        ▼
 Published copy + Document Register entry
        │
        ▼
 OLD AI extractor reads it ──▶ Extraction Review (no Control IDs)
```

- **Way 1** checks that a document is properly written and approved. At the end it still uses the **old AI extractor**, which guesses controls from the text.
- **Way 2** is what you're using now. It reads the controls exactly as written, by Control ID, with no guessing. But **it doesn't check whether a document is approved.**

**So, to your question "how do we already have all the controls when the documents haven't passed Document Lifecycle?":** they came in through Way 2, which reads the library as it is today. **All 123 documents in the library are drafts.** 83 say "Draft" in their own status field, and 40 don't state a status. So every control in your queue comes from a draft. Section 12 explains what to decide about that.

---

## 2. Way in #1: Document Lifecycle

A document goes through three stages: **Review → Sensitisation → Approval.**

### How a document enters Lifecycle
- An owner creates it by hand, or starts a **revision** of an existing approved document.
- The **Policy Drafter** (AI writes a first draft).
- **Gap Analysis**: a gap needs a new or changed document ("Gap Remediation").
- A **review-queue decision**, e.g. "Revise the procedure" in Assignment & Ownership.
- The **daily 08:00 job**: a document's review date is within 30 days ("Scheduled Review").
- The **SharePoint intake script**: picks up new files in the library. It's designed to run twice a day, but isn't scheduled on the server yet.

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
  4. Runs the **old AI extractor** on the approved document, which puts items in Extraction Review.
- **Reject** needs a reason (20+ characters). The document goes back to Review.
- The owner can recall it, and Compliance can reverse an approval.

### Two gaps between Lifecycle and the library
- **The published copy doesn't go back to the library.** It goes to *Lifecycle Documents* on the OrgOS site. The library sync never reads that folder.
- **Approval uses the old extractor, not the new reader.** So approving a Standard gives you a second set of controls in the queue, without Control IDs, that duplicates the library sync's set. See decision 2 in section 12.

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
| **CDI-06 Wording** | Obligations written with "shall" / "must", not "should", "where possible", "ideally", etc. | **Yes** | See below |
| CDI-07 / 08 | Vague role / vague evidence | Switched off | |
| CDI-09 Standards | Mentions ISO 27001 / 9001 / NDPA, or a clause like A.5.15 | **Yes** | Feeds the Standards Map |
| CDI-10 Related documents | Section present | No | |
| CDI-11 Classification | e.g. "Internal use only" | No | |
| CDI-12 Owner | Document owner / approver named | No | |
| CDI-14 Effective date | A real date | Yes, once versioned | |
| CDI-15 Version | A real version number | **Yes** | Versioning and covers depend on it |

For the wording and section checks, an AI looks first. A second AI opinion can turn a fail into a pass, never the other way. If the AI is down, simple word-matching is used instead.

### The "shall" rule (CDI-06), and why it needs changing
**What it does:** it flags any obligation written with "should", "ideally", "where possible", "as appropriate" and so on, and asks for "shall" or "must". It **blocks** the document.

**Why it exists:** the old AI extractor only recognised a sentence as a control if it said *shall / must / is required to / will*. A "should" sentence was invisible to it.

**The problem:** your own CDI Procedure (§7.5) says: *"SHALL or MUST means mandatory; SHOULD means recommended; MAY means optional. Do not use should where shall is meant."* Its check **V14** only **reports** misuse; it doesn't block. The CDI Standard says Guidelines *use should and may*. So OrgOS is **stricter than your own standard**. It can block a Guideline or Standard that uses "should" correctly for a recommendation.

**And it's no longer needed for its original reason.** The new reader (section 6) finds controls by their **Control ID and labelled fields**, not by the word "shall".

**Recommendation:** make CDI-06 a warning, as V14 says. Flag "should" only where the sentence sits inside a control's Requirement. See decision 3 in section 12.

**Note on "shall log → logs"** in your Assignment & Ownership screenshot: that isn't the CDI-06 check. It's the *"copy differs"* comparison (section 8), which flags any change in wording when a procedure copies a control.

---

## 4. Way in #2: the library sync

**What it reads**
- **Where:** SharePoint site *everybody* › library **ORGOS LIBRARY** › folder **ORGOS CONTROL LIBRARY** › **every subfolder**, at any depth.
- **Which files:** `.docx` and `.pdf`. `.doc` files are listed but can't be read; they show as *unreadable* ("save it as .docx"). Excel and everything else is ignored.
- **What it skips:** **nothing.** That includes drafts and old copies. A filename like "Draft" or "old" isn't treated specially, because nearly every file in the library is called Draft.
- **How it's run:** by hand, `python scripts/sync_control_library.py`. It's a dry run that prints a summary; add `--apply` to write. **It isn't scheduled**, so nothing changes until someone runs it.

**What it does**
1. Reads each document: its code, type (Standard, Procedure, Policy, …), and the controls it defines or carries out.
2. Works out **which document defines each control**. A Standard beats a Procedure, which beats a Policy. If two equally ranked documents both define it, the one that states more fields wins. If they tie exactly, the control is **not synced** and a *Defined twice* item is raised.
3. Compares each control with the Control Register:
   - **unchanged:** nothing happens;
   - **new:** a review item;
   - **changed:** a review item showing what changed.
4. Checks the documents against each other and against the Records Catalogue, and raises Zone 2 items (section 8).
5. Closes Zone 2 items whose problem has gone, and re-checks every Blocked control's role.

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

The reader *does* record each of these as a finding. But **the sync doesn't show them to anyone yet.** Only the separate census script prints them. Decision 4 in section 12 proposes showing them.

**How good is it today?** Across the real library, the reader understands about **98% of the control layouts** in use (it was 60% before the reader was rewritten). The remaining 2% are documents with no control structure.

---

## 7. What could go wrong when reading the library

| Scenario | What happens | Handled? |
|---|---|---|
| A file **fails to download** during the run | Previously its controls looked deleted, so pending items could be closed by mistake and false "cites an undefined control" items raised. **Now the run refuses to write and asks you to re-run.** | ✅ Fixed today |
| A **draft** sits next to the final version | Both are read. If both have the same code, a *Two files, one code* item is raised. **If neither has a code, nothing notices.** | ⚠ See decision 1 |
| Every document is a **draft** (true today) | Controls are read and can be accepted as if final | ⚠ See decision 1 |
| A file sits **loose in the top folder** of ORGOS CONTROL LIBRARY | **Never read.** Only subfolders are read | ⚠ Keep files in subfolders, or we change it |
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
11. **Drafts and old copies should live outside the library**, or follow whatever rule you choose in decision 1.
12. Use **shall / must** for obligations, **should** only for recommendations, and **may** for options, as CDI §7.5 says.

---

## 12. What was fixed today, and the decisions that are yours

### Fixed today
- **Extraction Review's Accept button was broken.** It called a server endpoint that had been removed.
- **Control definitions now display properly on the review pages you use:** Control ID, New / Changed, the full definition, and a correct "If accepted" preview.
- **Library findings were all labelled "JD → No policy".** Each kind now has its own label and choices.
- **A failed download during a sync** could close review items by mistake. The sync now refuses to write when the read is incomplete.
- **Approving a document set its next review date to the sensitisation deadline**, so the daily review job immediately opened a review for it. Now it's set a year after the effective date.
- **Approving a scheduled review created a second Document Register entry** instead of updating the existing one. Fixed.

### Decisions needed
**1. Drafts.** Every document in the library is a draft. Options:
- **(a) Leave it as now.** Drafts are read and can be accepted. *Fast, but the register is built on unapproved text.*
- **(b) Read drafts, but label them** ("from a draft, not yet approved") and accept them as **provisional**. They become final when the document is approved in Lifecycle. ← **recommended**: Bobby gets the control view now, and the approval rule is still respected.
- **(c) Read approved documents only.** *Strict, but today that means zero controls until all 123 go through Lifecycle.*

**2. Join the two ways in.** When Lifecycle approves a document with the control pattern, run the **new reader** on it (by Control ID), not the old AI extractor. Keep the old extractor only for old-style prose documents. Also publish the approved copy back to the library, so the sync and Lifecycle look at the same file. ← **recommended**; without it, every approval creates duplicate queue items with no Control ID.

**3. CDI-06 ("shall" rule).** Make it a warning, in line with CDI Procedure V14, and allow "should" and "may" for recommendations and options. ← **recommended**

**4. Silent misses.** Show the reader's own findings: dropped controls, misspelled labels, scanned PDFs, files at the top of the folder, two Standards defining one ID. They would appear as Zone 2 items or as a report at the end of each sync. ← **recommended**

**5. Schedule the sync** (e.g. nightly) once decisions 1 and 2 are settled. Today it only runs by hand.

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
| **Library sync** | The script that reads the whole ORGOS CONTROL LIBRARY |
| **Old extractor** | The earlier AI that guesses controls from text; still used at Lifecycle approval |
