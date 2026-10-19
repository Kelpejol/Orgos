# OrgOS GRC framework — go-live checklist

Everything below is built and tested on the `dev` branch. Nothing has been written to SharePoint yet. Work through the steps in order; each one says who does it.

---

## 1. What we still need from you

| Item | Why | Format |
|---|---|---|
| **The organogram** | It becomes the Role Catalogue. Until then almost every control is *Blocked* (its accountable role isn't recognised), and the ~110 role spellings in the documents can't be resolved. | Any of: Excel/CSV, a PDF chart, or a list. For each role: **title, department, reports to, current holder (name or email), acting holder and until when, vacant or not**. |

That is the only input needed to finish building. Everything else uses the defaults already agreed.

---

## 2. SharePoint setup (a SharePoint admin, on the OrgOS site)

OrgOS can write list items but cannot create lists or columns, so these are manual. Column names must match exactly (no spaces). "Plain text" means *Multiple lines of text* with rich text **off**.

### 2.1 New list: **Records Catalogue**

| Column | Type |
|---|---|
| Title *(exists)* | holds the Record ID, e.g. REC-0623 |
| RecordName | Single line of text |
| Payload | Multiple lines, plain text |

Then copy the list's ID into the server `.env` as `RECORDS_CATALOGUE_LIST_ID=…`.

### 2.2 Control Register — add columns

| Column | Type |
|---|---|
| ControlId | Single line of text (**indexed**) |
| DefinitionJson | Multiple lines, plain text |
| MappingJson | Multiple lines, plain text |
| BlockedReason | Multiple lines, plain text |

If **Status** is a Choice column, it must allow: Active, Blocked, Under Review, Superseded, Withdrawn.

### 2.3 AI Review Queue — add columns

| Column | Type |
|---|---|
| ControlId | Single line of text (indexed) |
| ChangeKind | Single line of text |
| ResolutionKey | Single line of text (indexed) |
| CandidateJson | Multiple lines, plain text |
| DiffJson | Multiple lines, plain text |

If **ReviewStatus** is a Choice column, add **Superseded**.

### 2.4 Evidence Tracker — add columns

| Column | Type |
|---|---|
| ObligationKey | Single line of text (indexed) |
| RecordId | Single line of text |
| Custodian | Single line of text |
| State | Single line of text |
| StateDetail | Single line of text |
| SuggestedFrequencyBasis | Single line of text |
| ScheduleSetBy | Single line of text |
| OperatingTrigger | Multiple lines, plain text |
| SuggestedFrequencyDays | Number |
| CheckFrequencyDays | Number |
| FreshnessDays | Number |
| ScheduledFrom | Date |
| LastRecordDate | Date |
| PendingRecordDate | Date |

`NextDue` already exists. If **Status** is a Choice column, add **Rejected** and **Withdrawn**.

### 2.5 Gap Analysis

No new columns. If **Standard** is a Choice column, add **CDI** and **ISO 22301**.

---

## 3. Deploy (server, `/opt/orgos`)

1. Deploy the `dev` branch.
2. `pip install -r requirements.txt` — new: `pdfplumber`, `openpyxl`.
3. Add `RECORDS_CATALOGUE_LIST_ID` to `.env` (step 2.1).
4. Rebuild the frontend (`npm run build`) and restart OrgOS as usual.

---

## 4. First run (server, in this order)

Every script is a **dry run** unless given `--apply`. Run it without first and read the summary.

| # | Command | Expect |
|---|---|---|
| 1 | `python scripts/import_records_catalogue.py` | "create 729" |
| 1a | `… --apply` | 729 records written |
| 2 | `python scripts/sync_control_library.py` | ~347 new control items; 7 Zone 2 items (DP-002 cited by 3 procedures; 4 IT procedures edited their copy of the IT Standard) |
| 2a | `… --apply` | items appear in the AI Review Queue |

Then, in OrgOS:

1. **AI Review Queue → Extraction:** accept the control definitions. Each accept creates or updates one Control Register row and its evidence obligations. A re-run of step 2 afterwards should report nothing new.
2. **AI Review Queue → Orphan:** decide the 7 findings ("Remove from policy" sends a revision to Document Lifecycle).
3. **Evidence Tracker → Unscheduled:** set how often each record is confirmed. 62 have a suggested frequency from their control's trigger.
4. **Gap Analysis:** run it once. Expect ~86 control-framework gaps under Standard **CDI**, each grouped per document or per control; they close themselves once fixed.

From then on, a daily job (07:30) keeps evidence obligations in step with the controls and updates their state.

---

## 5. Power Automate (whoever maintains the flows)

Add one flow on the **Evidence Tracker** list: when **State** changes to *Missing, Late, Stale, Rejected* or *Due soon*, notify the holders of **OwnerRole** (and Compliance for Missing/Late).

---

## 6. Tidy up existing data

- **8 old AI Review Queue items** from the previous extractor are still pending. Reject them with a note ("superseded by library sync"); the library sync replaces them.
- **16 existing Gap Analysis items** stay as they are.

---

## 7. For document owners (OrgOS raises these itself)

After the first run, Gap Analysis and the review queue will show them; listed here so nobody is surprised:

- **101 controls name no accountable role**, and many name several jointly ("DPO + Legal"). CDI expects one accountable role per control.
- **302 of 347 controls leave CDI fields unstated** — mostly mapping, failure route and exception route.
- **Two documents have no document code:** *IT and Infrastructure Control Standard* ("Not assigned") and *Context and Interested Parties Procedure*.
- **DP-002 was retired** but three procedures still cite it.
- **Four IT procedures** changed the IT Standard's wording when copying it (IT-01, IT-03, IT-04, IT-09).
- **20 controls are defined but no procedure carries them out** (e.g. the RRS and RSR records rules, DP-065/066).

---

## 8. Still to build — after the organogram arrives

- **Role Catalogue:** roles with kind (positional, functional, team, system), status, reports-to and acting holders; role assignments by scope; seeded from the organogram and the documents' Roles tables.
- **Role resolution in the review queue** for unrecognised role spellings, and scored role suggestions a reviewer accepts with one click (accepting adds an alias, so the same spelling resolves next time).

Once those are in, Blocked controls clear themselves on the next sync.
