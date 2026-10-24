# Document standards engine and role resolution — design for discussion

> **Update, 22–24 Oct 2026.** Parts of this design are superseded. Bobby's role model replaced Accountable/Executing with one **Control owner** per control and a **Document owner** for the document; **Org Roles is the role register** (loaded from the job descriptions and staff register, so no organogram is needed); and V07 is built. See `ROLE-MODEL-CHANGE.md` for the current design. Where this document says otherwise, the newer one is right.


*21 Oct 2026. For you to mark up, and to take the "Ask Bobby" questions to him.*

> **Built since this was written (21 Oct):** the Document Standards page (see HOW-ORGOS-WORKS §1c), with checks V01 to V04, V08 to V12, V14, V15, V22 and V23, and Convert to CDT with its five proofs. Still to build: V05 to V07 (need the organogram), V13, V16 to V21, V24, wiring the checks into the Lifecycle Review gate, and everything about roles in Part B.

---

## 1. The finding that shapes everything

We assumed the "document standards engine" was something new we would design. **It isn't. Your own CDI Procedure already specifies it.**

- **Annex: validation checks V01 to V24.** Each is marked **BLOCK**, **FLAG** or **REPORT**. 18 are BLOCK, 5 are FLAG, 1 is REPORT.
- **Annex A: document metadata fields.** 26 fields, each marked mandatory or not.
- **Control fields table.** The eight control fields we already read, plus the monitoring field.
- **Annex B: reference data.** Document types, function codes, retired codes, and the **approval route for each domain**.
- **§17: roles and the organogram.** The only authority for which roles exist.

**The checker OrgOS runs today is a different, older list.** CDI-01 to CDI-15 come from the *Document Creation Standards*. The CDI Standard says it **supersedes** that document. So OrgOS enforces a retired rulebook, and doesn't enforce the current one.

**What the engine is, then:** an implementation of V01 to V24 as Bobby's CDI defines them, with CDI's own BLOCK / FLAG / REPORT levels. We aren't inventing a standard. We're making OrgOS apply the one Dragnet already wrote.

**A concrete example.** The Identity Standard we put through the pilot would have been **stopped at Review**:
| Check | Why it would have stopped |
|---|---|
| **V22** (BLOCK) | None of its 6 controls states a standards mapping |
| **V07** (BLOCK) | It names "IT and application owners", which isn't a role in any role register |
| **V23** (BLOCK) | Its file is named "…Standard **Draft**.docx", and a file name must carry no status |
| **V03** (BLOCK) | Its parent policy hadn't been approved, as far as I know |

That is exactly the drift you described, caught while the author can still fix it.

---

## 1a. In plain words: what the annexes are

The CDI Procedure is a rulebook. At the back it has three annexes. They are three different **forms** or **lists** the rules refer to:

| Annex | What it is | Think of it as | Example |
|---|---|---|---|
| **Annex A: Document Register Record** | The fields kept about **a whole document** (26 of them) | The **registration card** for a document | Code, title, owner role, parent, domain, status, version, effective date, classification |
| **Annex B: Reference Data** | **Lookup lists** the rules use | The **dropdown lists** and **approval chart** | Document types (POL, STD, PRO…), function codes (ISMS, QI, IT…), retired codes, and for each domain, who gives First Pass and Final Approval |
| **Annex C: Control Record** | The fields kept about **one control** (16 of them) | The **registration card** for a control | Control ID, requirement, trigger, accountable role, executing role, evidence, mapping, risk, failure route, exception route |

So: A describes documents, C describes controls, and B is the shared reference lists. Every control sits inside a document, which is why both cards exist.

**What the engine does with them:**
- It checks that a document's **A card** is complete and valid (V01, V02, V05, V06, V23…).
- It checks that each control's **C card** is complete (V08, V10, V22…).
- It uses the **B lists** to decide what's valid: is this function code real? Who approves for this domain?

**What these checks look like on the real library today** (only controls in the document that *defines* them count):
- 24 documents define controls (347 controls in total).
- **Only 1 of the 24 states every field of every control**: the CDI Standard.
- **23 lack a standards mapping** on some control (V22).
- **17 lack some other required field** (V08), and **6 lack a risk statement** (V10).
- **8 documents have no document code** at all (V02), and **29 break the file-name rule** (V23): 27 carry a status, version or date, and 2 differ from the title.

That's a measure of the work, and shows the engine would find real, specific problems.

---

## 2. Part A: the engine

### 2.1 The checks, and what each needs

| Check | Enforcement | What it checks | Can OrgOS check it today? |
|---|---|---|---|
| V01 | BLOCK | All mandatory register fields complete | Mostly: most come from the document header |
| V02 | BLOCK | Code is unique, built from current reference data, no retired function code | Yes, once Annex B is loaded as reference data |
| V03 | BLOCK | Parent link exists and the parent is **approved** | Yes: header names the parent; the Register holds approval |
| V04 | FLAG | Type matches layer; content matches type (no steps in a Policy) | Partly |
| V05 | BLOCK | Domain valid, and the approval route **resolves to role holders** | Needs the Role Register |
| V06 | BLOCK | First Pass and Final Approval are different roles **and different people** | Needs the Role Register |
| V07 | BLOCK | **Every role named in the text exists in the Role Register** | Needs the Role Register |
| V08 | BLOCK | Each control has all its fields | Yes: we already compute "missing fields" |
| V09 | BLOCK | Every evidence reference is a Catalogue Record ID, declared evidence at source, or a logged admission request | Yes, with the Catalogue imported |
| V10 | BLOCK | Every control has a risk statement; no risk IDs | Yes |
| V11 | BLOCK | No control duplicates an ID or restates it with a changed requirement, role, evidence or trigger | Yes: we detect both today, but only after approval |
| V12 | FLAG | No vague qualifier in a requirement, trigger or step | Yes: a word list |
| V13 | BLOCK | No drafting notes, pending lists, predecessor citations or **individuals' names** in controlled text | Partly: notes and markers yes; names are hard |
| V14 | REPORT | Normative words used correctly | Yes: this is today's CDI-06 |
| V15 | FLAG | Required sections present | Yes: today's CDI-03/04/05 |
| V16 | BLOCK | Layer 4 steps each name a responsible role | Partly |
| V17 | BLOCK | Automated steps declare their evidence output and source system | Partly |
| V18 | BLOCK | No local record type, retention, custodian or disposition in the text | Partly: text patterns |
| V19 | FLAG | Similar existing documents shown to the author | Later |
| V20 | BLOCK | A version increment carries a change summary; a material change carries a version increment | Yes, at approval |
| V21 | BLOCK | Stakeholder consultation recorded; sensitisation recorded where required | Yes: Lifecycle already records these |
| V22 | BLOCK | Every QMS/ISMS control has a **per-control standards mapping** | Yes |
| V23 | BLOCK | File name equals title, with no status, version or date | Yes |
| V24 | FLAG | AI Involvement field completed; standards cited are current | Partly |

### 2.2 Where it runs
- **Document Lifecycle → Review.** Results show beside each document: what blocks, what's flagged, and where in the document.
- **BLOCK** stops the move to Sensitisation. **FLAG** needs a decision by the Compliance Executive (QMS & NDPA), who "decides FLAG results" (CDI). **REPORT** is shown only.
- **Approval re-runs it**, so a document edited after Review can't slip through.
- **It replaces the old CDI-01 to 15.** Most carry over: CDI-01 becomes V02, CDI-05 becomes V15, CDI-09 becomes V22.
- **Roles are checked here too (V07).** A role the document names that isn't in the Role Register is reported to the author **before** approval, instead of showing up afterwards as a Blocked control.

### 2.3 Transition: the hard part
Applying all 18 BLOCKs to the 123 existing documents would stop nearly all of them. CDI anticipates this: **"Transition status: Legacy, In transition, Aligned"** is a mandatory field, and the Compliance Executive keeps a "transition list".

**But is this a problem for us?** The "Legacy" concern is about documents that were **already approved** before the rules existed. Every one of the 123 documents in the library is a **draft** (83 say "Draft", 40 state no status), and none has been approved through OrgOS. So today there's nothing "legacy" in the CDI sense: they are all *new documents that haven't been approved yet*. Purging OrgOS's own data wouldn't change that: the **files** are the issue, not OrgOS's registers.

**So the simplest answer:** treat all of them as new. Each must meet the standard before approval, and the engine tells the author exactly what to fix, and where. The transition tier only matters if Dragnet has documents it formally approved before OrgOS, and Bobby can say so (Ask Bobby, #1).

---

## 3. Part B: roles

### 3.1 Three kinds of role
The documents use role names of three kinds, and OrgOS has to treat them differently:

| Kind | Examples | What it is | How it resolves to a person |
|---|---|---|---|
| **Organisational role** | Information Security Officer, HR Manager, Chief Compliance Officer, Compliance Executive (QMS & NDPA) | A post on the **organogram** | Role Register → the verified directory identity holding it (acting holder if vacant) |
| **Functional role** | **Document Owner, Control Owner, Custodian Role** | A role defined **by context**: "the owner of *this* document / control / record" | By context, see 3.2 |
| **System** | "platform check V11", "platform checks V09, V17" | An automated check, not a person | Shown as automated; the validation engine itself is the system |

### 3.2 How functional roles resolve (CDI already defines them)
| Role | CDI definition | Resolve from |
|---|---|---|
| **Document Owner** | The author; the register's **"Owner role"** | The **defining document's owner role**: its cover already states it (e.g. DRG-QI-STD-CDI → Compliance Executive (QMS & NDPA)). **Data exists today** |
| **Custodian Role** | "The role that holds and can retrieve a record in its context" | The **Records Catalogue entry** names the custodian for each record (e.g. REC-0691: "Kept by Information Security Officer"). **Data exists today** |
| **Control Owner** | "The role accountable for operating a control, **as recorded on its control record**" | **Not in the document.** The control block has no Control Owner field. It has to be recorded when the control is confirmed (see Ask Bobby #3) |

**Effect:** Document Owner (11 controls) and Custodian Role (4) can resolve **now**, with no new data. Only Control Owner (8) needs a decision.

### 3.3 People
- A role resolves to a person through the **Role Register**, which "reflects the controlled organogram and the verified identity directory" (CDI 17.3).
- **A job title alone is never authority** (Bobby). Resolution runs role → assignment → verified directory identity.
- **Vacancy and acting holders:** an assignment can carry an acting holder and an end date. The BCDR Procedure already relies on this: *"the CTO holds the duty while the title is vacant."*
- **"Roles govern, individuals execute."** When a person leaves, only the organogram changes. Controls and documents don't.

### 3.4 Accountable and executing
- **Accountable** answers for the control. **Executing** does the work and produces the record.
- CDI says executing may be a **role or a system**.
- **Proposal:** an evidence obligation goes to the **executing** role when it is a person's role. For a system, or an unresolved role, it goes to the **accountable** role. The executing role is then flagged to the author via V07.
- **"IT and application owners"** is neither a role in the organogram nor one of the three functional roles. Under V07 it would be reported to the author, to be replaced by a real role.

### 3.5 Approval routes (CDI Annex B)
CDI requires **two approvals** on a route set by the document's **Primary Domain**: a **First Pass** and a **Final Approval**, by different roles and different people. Examples:
| Domain | First Pass | Final Approval |
|---|---|---|
| Information Security | Information Security Officer | Chief Compliance Officer |
| Quality & Compliance | Chief Compliance Officer | Managing Director / CEO |
| IT & Infrastructure | Head of IT and Infrastructure | Chief Compliance Officer |

**OrgOS has one approver, chosen by the owner.** That doesn't match CDI. The routes become reference data, the Role Register supplies the people, and V05 and V06 check them. This needs the organogram (Ask Bobby #5).

---

## 3a. Part C: converting existing documents onto the CDT

The engine's **second job** is not only checking but **converting**: bringing a SharePoint document onto the **CDT (controlled document template)** so its control facts live in the Register, and the file can't drift from it.

**What the CDT is, in plain words:** a standard front cover and header, with **placeholders** for the facts that change (code, version, effective date, approver, next review). The Register holds the real values, and software fills the placeholders when the document is viewed, downloaded or published. Nobody types them into the file, so the file and the Register cannot disagree.

**What already exists:**
- master templates with the placeholders;
- the merge that fills them in, and stamps version, dates and approver at approval;
- "Attach CDT cover" (`lifecycle/graft.py`): puts the template's cover in front of an existing document's body;
- cover detection: whether a document already has one.

**What doesn't exist yet, and is exactly what you described:**
1. **Reading the document's own header block.** Every v06 document opens with a table of facts (code, title, owner, parent, approvers, classification, standards, supersedes…). The CDI parser already reads it. The current cover logic does **not**: it guesses facts from the Register and the folder name instead.
2. **Removing that old header block** after conversion. Today the graft keeps the whole document, so the hand-typed block would sit next to the new cover and the two could disagree.
3. **Showing what was carried over**, for the author to confirm, before anything is saved.

**The convert flow (proposal)**
1. The author clicks **Convert to CDT** in Review.
2. OrgOS **reads the header block** and fills the Register's fields (Annex A) from it.
3. It shows a **before and after**: what was read, what will go on the cover, what's missing.
4. On confirmation it builds the new file: template cover and header with placeholders, then the **body unchanged**, with the old header block removed.
5. **Safety check:** OrgOS compares the document body before and after and **proves no controlled text changed**. Anything else stops the conversion.
6. From then on the Register is the master. Version, dates and approver are stamped at approval, and the file name is set to the title (V23).

**What conversion can't do:** it can only carry over facts the document already states. If a control has no mapping, or a role isn't a real role, conversion won't invent one. Those are the engine's *checks*; the author must fix them.

**How the two jobs fit together:** convert first (mechanical problems vanish: file name, dates, version, header drift), then check (content problems remain: mapping, roles, missing fields). Many of the 123 documents' mechanical failures would disappear in one step.

---

## 3b. "Not pretending": how we make sure each check really works

A check that silently can't run is worse than no check. These rules go into the engine:
1. **Every check returns one of four answers:** Pass, Fail, Flag, or **"Could not check"** with the reason. It can never quietly pass when it couldn't look.
2. **Every check has a test on the real documents** with a known right answer (e.g. "the CDI Standard passes V22; the Identity Standard fails it").
3. **A proof run:** after any change, the engine runs against the whole library and prints how many documents pass and fail each check. Any surprise is visible.
4. **Failures to write are shown, not hidden.** Several earlier problems were silent: audit entries failing, evidence obligations not created, stale CDI results blocking. The engine reports its own failures on screen.

---

## 4. Other decisions that CDI already settles

| Topic | What CDI says | Consequence for OrgOS |
|---|---|---|
| **Versions** (§12, §14) | One field, **Version**: *"set on issue"*, replaces Revision and Issue. Drafts **have no version number**. A review with no substantial change **keeps** the version; correcting typos or formatting doesn't increment it. Every issued version needs a **change summary** (V20) | Retire the Register's "R01". One number (01, 02…). At approval the approver chooses **new version** (requires a change summary) or **correction / no change** (logged) |
| **Check frequency** | The control table has **"Monitoring method, frequency, role and evidence freshness"**, *where the control is monitored*. The Standard itself writes it as "Monitoring declared: method, frequency, responsible role" | We don't need a new field. The parser should read this one, and schedule automatically when it's stated. When absent: Unscheduled, as today |
| **Where approved copies live** (§12.1, §13.3, §15.1) | Drafts are in the **working area**. The controlled copy is the approved version in **"the GRC platform or its published library"**. Superseded versions move to a **read-only archive library** | Our library folder is the working area, and that's correct. Approval should publish to the **published library** and move the previous version to the **archive**. We need to know which libraries those are (Ask Bobby #6) |
| **Documents carry the platform's data** (§6.3) | The platform generates the code; *"year of first issue, version and sequence are held as fields, not built into the code"* | Matches our direction: the Register, not the file, is master. Required CDT cover and file name rule (V23) follow |
| **Order of approval** | V03: the **parent must be approved** | Approve Policy → Standard → Procedure. OrgOS enforces it instead of us remembering |

---

## 5. Ask Bobby

Each has my recommended answer, so he can confirm or correct.

1. **Transition.** *Has Dragnet formally approved any document before OrgOS, so that some documents are genuinely "Legacy"?* If not, we treat all 123 as new documents and skip the transition tier. **Recommended:** treat all as new; if some are genuinely legacy, downgrade only those BLOCKs to FLAGs until their next revision.
2. **Replacing the old checker.** *Confirm CDI V01–V24 replace CDI-01–15 (from Document Creation Standards, which CDI supersedes).* **Recommended:** yes.
3. **Control Owner.** CDI defines it as "as recorded on its control record", but the control block has no field for it, and eight controls name it as accountable. *Who assigns it, and where?* **Recommended:** the reviewer records it when confirming each control, defaulting to the defining document's owner role.
4. **Functional roles in the Role Register.** *Do Document Owner, Control Owner and Custodian Role sit in the Role Register as roles resolved by context, as proposed in 3.2?* V07 says every named role must exist there. **Recommended:** yes.
5. **Approval routes.** *Should OrgOS implement the two-step Annex B routing now, so V05 and V06 can be enforced?* It needs the organogram first. **Recommended:** yes, as soon as the organogram is in.
6. **Libraries.** *Which libraries are the "published library" and the "read-only archive"? Is the ORGOS CONTROL LIBRARY the "working area"?* **Recommended:** yes to the working area; he names the other two.
7. **"Platform check Vnn" as an executing system.** *Confirm these name the validation platform itself*, so they resolve as automated, not as unrecognised roles.
8. **The organogram.** Title, department, reports to, current holder (name or email), acting holder and until when, vacant or not. Daniel and Wani were copied on his email for this.

---

## 6. Decide between us

| # | Decision | My recommendation |
|---|---|---|
| A | Build order | Reference data (Annex A/B) → engine checks that need nothing new (V02, V03, V08–V12, V14, V15, V22, V23) → Role Register and V05–V07 when the organogram arrives → the rest |
| B | Should BLOCK stop a document at Review, or only at approval? | At Review, so authors fix problems while writing; approval re-checks |
| C | Who sees engine results | The owner, in Lifecycle Review, with where-in-the-document for each finding. FLAGs go to the Compliance Executive for decision |
| D | Old extractor tools | Keep the Extractor page for contracts, job descriptions and audits (not CDI documents); stop offering it for control documents |
| E | What happens to controls already accepted | Nothing: they stay. The engine applies to the next approval of each document |

---

## 7. Phases

1. **Reference data and the checks that need nothing new.** V02, V03, V08 to V12, V14, V15, V22, V23 and the version rule (V20). A rewritten results panel in Lifecycle Review. **No dependency.**
2. **Roles.** Functional-role resolution (Document Owner and Custodian first). Executing-role handling and the system kind. V07 against Org Roles groups until the organogram exists.
3. **Organogram and the Role Register.** Role kinds, acting holders, assignments. V05, V06 and the two-step approval route.
4. **The rest.** V13, V16 to V19, V21, V24. Publishing to the published and archive libraries.
5. **Bobby's control view**, which gets better with every phase above.

Phase 1 needs nothing from Bobby except Ask Bobby #1 and #2.
