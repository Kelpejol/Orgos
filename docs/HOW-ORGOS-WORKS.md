# How OrgOS works — in plain words

*Written 19 Oct 2026. What's built, how it fits together, what's left, and what happens when the organogram arrives.*

---

## The short version

OrgOS reads Dragnet's policy documents, pulls out every **control** (a rule someone must follow), and asks a person to confirm each one. Once confirmed, a control goes into the **Control Register**, and OrgOS starts tracking the **proof** (records) that the rule is followed. If proof goes missing or a document is wrong, OrgOS raises a **gap**.

```
 Documents in SharePoint
        │  OrgOS reads them (no AI guessing for the new-style documents)
        ▼
 Review queue  ── a person accepts or rejects each control
        │
        ▼
 Control Register  ── the official list of rules, one row per Control ID
        │
        ▼
 Evidence Tracker  ── "show me the record that proves this rule ran"
        │
        ▼
 Gap Analysis & Standards Map  ── what's missing, what's late, what's wrong
```

**Is what you're seeing right?** Yes. Your two screenshots show the Extraction Review page working as intended. The details are in step 3 below.

---

## A few words you'll keep seeing

| Word | Meaning |
|---|---|
| **Control** | One rule, e.g. *"The Information Security Officer shall reassess all rights when someone changes role."* |
| **Control ID** | The control's permanent name, e.g. **ACS-L3-02**. Written in the document itself. OrgOS uses it so the same control is never entered twice. |
| **Standard (STD)** | The document that *defines* controls, e.g. DRG-ISMS-STD-IDL. Its wording is the official one. |
| **Procedure (PRO)** | Says *how* to carry a control out. It cites the control's ID and shouldn't change its wording. |
| **Record (REC-nnnn)** | A piece of proof, e.g. REC-0693 "Access request and approval". |
| **Records Catalogue** | The master list of all 729 records (from the Enterprise Records Catalogue spreadsheet). |
| **Evidence obligation** | "For control X, record Y must exist, and we check it every N days." |
| **Active / Blocked** | Active means the control has an owner OrgOS recognises. Blocked means it's recorded, but nobody can be held to it yet. The reason is shown. |
| **New / Changed** | New: OrgOS hasn't seen this Control ID before. Changed: the document has been edited since the control was accepted, and the page shows exactly what changed. |
| **Fields missing** | The document leaves out some fields the CDI Standard asks for, usually the mapping to ISO clauses. Accepting still records the control as written. The fix belongs in the document. |

---

## The pipeline, step by step

### 1. Read the library

OrgOS opens the **ORGOS CONTROL LIBRARY** in SharePoint and reads every Standard, Procedure, Policy and register. It skips drafts and superseded copies. For each document it works out the code (e.g. DRG-ISMS-STD-IDL) and the type.

*How to run it:* `python scripts/sync_control_library.py`. That's a dry run that prints a summary; add `--apply` to write.

### 2. Pull out the controls (no guessing)

New-style (v06) documents already lay out each control in a fixed pattern: *Control ID, Requirement, Trigger, Accountable / Executing, Evidence, Risk, Failure route, Exception route, Mapping*. OrgOS reads that structure directly. **No AI is involved**, so there's no confidence score. That's why your cards say **"From document"** instead of a percentage.

It also checks each control against what's already confirmed:

- **Same as before:** nothing happens and nobody is bothered.
- **New:** goes to the review queue.
- **Changed:** goes to the review queue showing only the fields that changed.

It also checks the documents against each other. Problems go to a second queue (step 4).

### 3. A person reviews: **Extraction Review** page (Zone 1)

This is the page in your screenshots.

- **The "New controls by document" panel** (your 2nd screenshot) lists each document and how many new controls it brings, e.g. *DRG-QI-STD-DP · 65 new*. **Accept all 65** accepts them together with one rationale. Each control still gets its own Control Register row and its own audit log entry. Read the cards first; this button only saves clicking.
- **Each card** (your 1st screenshot) shows the Control ID, its title, the requirement, the risk, and where it came from. Open it to see:
  - **"If accepted"**: exactly what will be created. For example: *ACS-L3-02 created; an evidence obligation for REC-0693, REC-0694, REC-0710; an audit log entry.*
  - **The full definition**: every field as the document states it.
  - **A red note** when the document leaves fields out. You can still accept.
- **There's no "Edit" option** for these controls. The wording belongs to the document. To change it, reject the control and change the document through Document Lifecycle. The next sync brings the new wording back as **Changed**.
- **Reject / Mark false positive / Request 2nd review** work as before.

### 4. Problems between documents: **Assignment & Ownership** page (Zone 2)

The 7 items there are problems in the documents, not in individual controls:

- **"Copy differs from its Standard"** (4 IT procedures): a procedure reworded a control it should copy word for word. Choose *Revise the procedure* or *Accept the difference*.
- **"Cites an undefined control"** (DP-002): three procedures point at a control that was retired. Choose *Revise the procedure* or *Define it in its Standard*.
- Other kinds you may see later: *Record not in the Catalogue*, *Cites a withdrawn record*, *Two files, one code*, *Defined twice*.

"Revise …" raises a task in **Document Lifecycle** for the document owner. **When the document is fixed, the next sync closes the item by itself.**

### 5. Accepting writes the registers

When you accept a control:

1. **Control Register:** one row per Control ID, created or updated, never duplicated. It's Active if its accountable role is recognised, otherwise Blocked with the reason.
2. **Evidence Tracker:** one evidence obligation for each record the control names (REC-nnnn).
3. **Audit Log:** who decided, when, and why.

### 6. Evidence obligations (the "proof" side)

Each obligation answers one question: *has this record been produced, recently enough?*

- An obligation starts **Unscheduled** until Compliance sets how often it's checked. OrgOS suggests a frequency for 62 of them based on the control's trigger. It never guesses the rest.
- A **daily job at 07:30** updates each obligation's state: *OK, Due soon, Late, Missing, Stale, Rejected.*
- A Power Automate flow (still to be set up) can notify the owner when the state turns bad.

### 7. Gaps and the Standards Map

- **Gap Analysis** checks every control: no owner, missing fields, no procedure carrying it out, records not in the Catalogue, and so on. These gaps are filed under Standard **CDI**, and they **close themselves** once the problem is fixed.
- **Standards Map** shows each ISO / NDPA clause as green, amber or red, depending on whether the controls mapped to it have owners and up-to-date proof.

---

## What's done and what's left

**Every stage of the pipeline is built and tested.** The "stage 8" in the build plan is *evidence obligations*, and that's done (step 6 above). What's missing isn't a stage. It's one input: **who holds which role.** That's the organogram.

| Part | State |
|---|---|
| Reading the library, Control IDs, New/Changed detection | ✅ Built |
| Records Catalogue in OrgOS (729 records) | ✅ Built (needs importing once) |
| Review pages: Extraction Review, Assignment & Ownership, Accept all | ✅ Built, and what your screenshots show |
| Control Register by Control ID, Active/Blocked with reason | ✅ Built |
| Evidence obligations, daily 07:30 job | ✅ Built |
| Gap Analysis on every control, self-closing gaps | ✅ Built |
| SharePoint columns and lists | ⏳ Manual setup, listed in [GO-LIVE-CHECKLIST.md](GO-LIVE-CHECKLIST.md) §2 |
| Power Automate notification flow | ⏳ To set up |
| **Role Catalogue** (the official list of roles and who holds them) | ⏳ **Waiting for the organogram** |
| Role suggestions in the review queue | ⏳ Built after the Role Catalogue exists |

### Why so much will be Blocked today

For now, OrgOS only recognises a role if it matches an **OrgOS group** (Org Roles page). An Entra job title doesn't count on its own, because Bobby was clear that a job title isn't authority. Documents also use roles like *"Accountable Department Head"* or *"Information Security Officer; HR and application owner"* (two roles at once).

So when you accept today, **many controls will be recorded as Blocked**. **That's expected and safe.** The control is in the register, its evidence is tracked, and the reason it's Blocked is shown. Nothing needs redoing later.

---

## When the organogram arrives

**What we need:** for each role, its title, department, who it reports to, who currently holds it (name or email), whether it's vacant, and who is acting in it and until when. Excel, CSV, a PDF chart or a plain list are all fine.

**What happens then:**

1. **We build the Role Catalogue from it.** Each role gets its holder (a real Entra person), its acting holder if it's vacant, and who it reports to. Roles from the documents' own *Roles* tables are added too, with their duty descriptions.
2. **Different spellings get linked to one role.** "Head of IT", "IT Head" and "Head of IT and Infrastructure" become one role. Spellings OrgOS can't place show up in Assignment & Ownership with suggested matches. Choosing one teaches OrgOS that spelling for next time.
3. **The next library sync re-checks every Blocked control.** If its role is now recognised, it turns **Active by itself**. You don't need to accept anything again.
4. **Real people become accountable.** Evidence obligations, notifications and Gap Analysis now point at actual people. When someone leaves or changes role, you update the role holder once and every control follows.
5. **What stays Blocked is genuinely broken in the document.** For example, a control that names two roles as accountable, or none at all. Those become gaps for the document owner to fix. They aren't work for OrgOS.

---

## What to do now, in order

1. Finish the SharePoint setup and the first run in [GO-LIVE-CHECKLIST.md](GO-LIVE-CHECKLIST.md) (you're at step 4).
2. **Extraction Review:** read each document's controls, then accept them (Accept all per document is fine). Changed controls are reviewed one by one.
3. **Assignment & Ownership:** decide the 7 document problems.
4. **Evidence Tracker → Unscheduled:** set how often each record is checked.
5. **Gap Analysis:** run it once.
6. Send the organogram when it's ready.

### Two document tidy-ups your screenshot shows

- **Two documents have no code.** *IT and Infrastructure Control Standard* and *Context and Interested Parties Procedure … Draft 2026-09-28.docx* appear under their file names. The second also looks like a draft that shouldn't be in the library.
- **Codes are written two ways.** Some include the year (DRG-ISMS-STD-ICLP-**01-26**) and others don't (DRG-ISMS-STD-IDL). Both work, but picking one style would keep things tidy.
