# OrgOS — Completion Plan

**Purpose:** one place that says what is done, what is left, in what order, and what blocks what — covering the compliance-meeting commitments, the ownership rework, and CDT.

Status legend: ✅ done · 🟡 partial · ❌ not started · ⛔ blocked on someone else

---

## 0. The through-line

Two structural shifts drive almost everything left:

1. **Ownership is a ROLE, not a person.** Controls/evidence store `OwnerRole` (job title, group name, or group alias); `OwnerEntraId` is never populated. Everything that asks "is this owned / can this user act?" must resolve the role through `ownership/resolver.py`. *(Fixed — see §1.)*
2. **The role vocabulary is Entra job titles + OrgOS groups — read LIVE.** The meeting's complaint was an *outdated Entra **export*** (a static snapshot copied into the old SharePoint Role Register). That list is gone; OrgOS now reads Entra live on every request, so it cannot go stale the same way. What's still wanted on top: group emails, multiple departments, multiple emails per entry. *(See §2.4 and §3.1.)*

---

## 1. Done ✅

**Document lifecycle & review**
- Approver is **selectable** at progression (person picker) — nothing hard-coded.
- Owner/drafter may also be the approver (both `owner != approver` blocks removed).
- **Feedback routes to the drafter**, not the approver.
- **Approver sees a clean brief only** — stakeholder comments removed from their view; replaced with a neutral approval brief (purpose, scope, standards, CDI, key controls, readiness) + a neutral change summary.
- **AI-assisted revision loop**: AI turns stakeholder feedback into exact edits (replace *and* insert), drafter accepts / edits / declines each, applied deterministically to the `.docx`, new version saved, CDI re-run.
- **CDI auto-fix**: located, verified, reversible confirm-and-apply; PDFs guidance-only.

**Roles, groups, ownership**
- **Job titles are the role vocabulary** for extraction and the owner pickers.
- **OrgOS Groups**: create/manage groups + members (Compliance/Admin), usable as owners.
- **Aliases** (up to 6 per group) — documents using any variant resolve to the same group.
- **Owner reassignment** for **evidence** and **controls** (job title or group).
- **Ownership resolution wired through** Standards Map, Gap Analyzer, Evidence, WorkHub — fixing three latent bugs that would have fired the moment controls were registered:
  - every clause showing **Red**,
  - a **false ownership gap on every control**,
  - **nobody able to submit evidence**.
- Stale "Role Register" UI copy removed (that register was deleted in the ERP merge).

**Approver correction (meeting commitment)**
- **Change the approver after submission** — Compliance or the document owner, without sending the document back a stage.
- **Reverse a wrong approval** — the document returns to Approval and its Document Register entry is **withdrawn** (never hard-deleted); a reason is required and both actions are audit-logged.

**Ownership visibility (§2.7)**
- `OwnerDisplay` everywhere (controls, evidence, standards): the role, a **GROUP / JOB TITLE / UNASSIGNED** badge, **who actually holds it** (expandable), and an **alias note** ("matched via alias X → Y").
- **Org roles**: "Show all staff" toggle (38 org-role holders ↔ all 98 internal staff) and an **"Owns"** column with controls/evidence counts per role; same counts on group cards.
- **"Blocked"** now consistently means *the role resolves to nobody*, worded the same everywhere.

**CDI**
- **Combined POL-PRO documents no longer flagged** — detected by naming convention; CDI-01 accepts the compound type.
- Collective terms ("All Staff") no longer flagged as unregistered roles.

---

## 2. Next — no external dependency

Ordered by value/risk. All can start immediately.

### 2.1 Control-number format ❌ *(quick, and currently wrong)*
Drop the trailing date suffix and adopt the standalone function codes.
- New: `DRG-{FUNCTION}-{TYPE}-{DOCID}` e.g. `DRG-QI-PRO-CDI`.
- `DOC_CODE_PATTERN` currently **requires** `-\d{2}-\d{2}`, so the new format is flagged as malformed today.
- Must accept **both** old and new during transition, and keep the combined `POL-PRO` form working.
- Rationale (Paul): the year suffix confuses the AI on annual updates.

### 2.2 Word-only drafts ❌ *(quick)*
Officers submit **.docx**, not PDF.
- Enforce/guide at upload: reject or clearly warn on PDF, with the reason.
- This is a **hard prerequisite** for CDI auto-fix, the AI revision loop, and CDT merge — all of which require a real `.docx`.
- Legacy PDFs stay readable; they just can't be auto-fixed or merged.

### 2.4 Register enrichment 🟡 *(foundation for §3)*
Extend the groups/role model with what the meeting asked for:
- **Group email** per group/role.
- **Multiple departments** per entry (currently one free-text category).
- **Multiple emails** per entry.
- Manual role entries (not just groups) so Compliance can add e.g. "Customer Success Team".
- ⚠️ Each new field needs a **manual SharePoint column** — the app cannot create columns (403). Writes are already gated so a missing column degrades instead of breaking.

### 2.5 Re-enable CDI-07 with register-backed suggestions 🟡
- Vague-role checking is **off** (turned off after "All Staff" false positives).
- With aliases + a real register it becomes safe: flag a vague role, then **offer valid options from the register** to pick.

### 2.6 AI revision loop — "no, use this wording" 🟡
- Today the drafter edits the replacement text directly.
- Target: drafter replies with a **comment**, and the AI picks the final wording from it.

---

## 3. Blocked / needs a decision ⛔

### 3.1 Job titles: one question to confirm, not an integration ✅/❓ *(Isaac)*

**Largely already solved.** The meeting's complaint was an outdated Entra **export**. That static list was deleted in the ERP merge; OrgOS now reads Entra **live** (≈1h cache), so it refreshes itself.

**Verified data (checked against the live tenant):**

| | count |
|---|---|
| Enabled accounts | 194 |
| ...of which **Guests** (external orgs) | 96 |
| **Dragnet staff accounts** | **98** |
| → with a job title | **77** |
| → without | 21 — almost all shared/booking mailboxes & bots (`info@`, `DiscoverCall@`, `boardroom-bot@`, `BirthdayCalendar@`), only ~5 real people |
| **Distinct job titles (owner vocabulary)** | **55** |

So coverage is good — an earlier note in this plan claiming "117 of 198 have no job title" was wrong; it counted guests and mailboxes.

**The one open question (process, not code):**
> When HR changes a job title in Seamless HR, does that change reach **Entra**?

- **Yes** → nothing to build; OrgOS picks it up within the hour.
- **No** → titles will drift; someone should sync them into Entra, exactly as the ERP already does for `org_roles` via `extensionAttribute1`.

Either way **no OrgOS integration is required.** Only if a decision is made to bypass Entra and read Seamless HR directly would we build a sync — and that is not currently needed.

Still genuinely wanted from HR/Compliance (see §2.4): team/group entries **labelled distinctly from individuals**, with **group emails**.

### 3.2 Notifications ⛔ *(needs a channel decision)*
"Sensitisation notifies all team members" and "notify the group" are **not possible today** — there is no email/Teams/webhook anywhere in OrgOS.
- Decide: Microsoft Graph `sendMail` vs Teams webhook vs both.
- Group emails from §2.4/§3.1 make group notification natural once a channel exists.
- Stakeholders *can* already submit reviews; only the notify half is missing.

### 3.3 Procedure naming alignment ⛔ *(Victoria, after the register lands)*

---

## 4. CDT (Controlled Document Templating) — parked

**State:** designed and partly built, deliberately **uncommitted** (`lifecycle/merge.py`, `lifecycle/templates.py`, `lifecycle/schemas.py`, `tests/lifecycle/`, plus CDT edits in `config.py`, `graph/client.py`, `grc/*`). Never pushed.

**Principle (unchanged):** AI never edits the document; a deterministic `docxtpl` merge writes controlled metadata (version, dates, approver) into the file.

**Why it can't just resume:**
1. The **ERP merge rewrote its foundations** — `config.py`, `graph/client.py`, `grc/*` all changed underneath it. The parked work restored cleanly but sits on shifted ground.
2. It was designed against **CDI v05**; **v06** changes the model — single `Version` field, `Domain`, two-step approval (First Pass + Final), 8 function codes.
3. It assumes **.docx sources** — so §2.2 is a prerequisite, and the PDF-only library needs a manual rebuild.

**Sequence when we pick it up:**
1. Land §2.1 (code format) and §2.2 (Word-only) first — CDT depends on both.
2. Re-align the CDT design to v06 (Version/Domain/two-step approval/function codes).
3. Rebase the merge engine onto the post-ERP `graph/client.py` + `config.py`.
4. Re-run the byte-for-byte determinism test (currently failing — expected, it's WIP).
5. Migrate templates; PDF-only documents get rebuilt as `.docx` once.

---

## 5. Suggested order of work

| # | Work | Depends on | Why now |
|---|---|---|---|
| 1 | Control-number format (§2.1) | — | Actively wrong; blocks correct new codes |
| 2 | Word-only drafts (§2.2) | — | Prerequisite for auto-fix, revision loop, CDT |
| 3 | Register enrichment (§2.4) | SharePoint columns | Foundation for HR sync + CDI-07 |
| 4 | Confirm title propagation to Entra (§3.1) | Isaac (a question, not a build) | Keeps the vocabulary current |
| 5 | CDI-07 re-enable (§2.5) | §2.4 | Safe only once aliases/register are real |
| 6 | Notifications (§3.2) | channel decision | Completes "sensitisation is a team activity" |
| 7 | CDT (§4) | §2.1, §2.2 | Highest effort; needs a stable base |


---

## 6. Standing constraints

- **CDT stays uncommitted** until deliberately resumed. Shared files (`graph/client.py`, `config.py`, `grc/*`) are committed with a selective-stage so CDT never leaks.
- **The app cannot create SharePoint lists or columns** (403). Any new list/column is a **one-time manual admin step**; code must degrade gracefully when one is missing.
- **Deploy:** `git pull` + restart for backend. Frontend changes additionally need `cd frontend && npm install && npm run build` — a plain pull does **not** rebuild the UI.
