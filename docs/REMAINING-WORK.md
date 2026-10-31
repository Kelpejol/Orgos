# OrgOS — what is left to do

*Updated 31 Oct 2026, after the platform review (docs/PLATFORM-REVIEW-2026-10-29.md) and its fixes.*

Status: ✅ done · ⏳ waiting · ☐ not started

---

## Done
- ✅ One way in: controls enter only when a document is approved in Document Lifecycle, read by Control ID.
- ✅ Intake reads type, code, title, department and standards from the document; nothing is invented.
- ✅ Document Standards page (14 of 24 checks; convert to CDT with 5 proofs); the checks are the Review gate (advisory by default).
- ✅ One version number with a change summary; approval stamps the cover from the Register; the published copy has its own folder, so every later revision is stamped too; reversing a revision restores the Register entry.
- ✅ Role model: one Control owner per control, a Document owner per document, **Org Roles is the only role authority** with one matching rule; loaded from the job descriptions and the staff register.
- ✅ **Wrong roles are flagged the moment a document arrives**, and fixed **per control or cover field** (Fix CDI issues, Use this role); Accountable / Executing lines become "Control owner:".
- ✅ Acceptance refuses multi-role or field-name owners; job titles never make a control Active.
- ✅ Standards Map, gaps, evidence and WorkHub follow the real data (computed states, Control ID links, gaps that close and stay settled); dropped controls go to Assignment & Ownership.
- ✅ Audit Log entries for every decision; Document Register edited only through approval (or an admin correcting a migrated entry).
- ✅ Document owners can open Document Lifecycle and work on their own documents.
- ✅ Chat answers "who owns X" with the role and the people who hold it.
- ✅ A purge that backs everything up first, and a restore script.
- ✅ The full test suite passes (963 backend, 14 frontend), including the three old sign-in tests.

## 1. Waiting on Bobby
| # | Decision | Blocks |
|---|---|---|
| 1 | Do V01–V24 replace the old CDI-01..15 checker? | Switching the old checker off |
| 2 | Were any documents approved before OrgOS (a "Legacy" tier)? | How strictly existing documents are held |
| 5 | The two-step approval route (First Pass, Final) by domain | V05, V06 |
| 6 | Which libraries are the **published** and **archive** libraries? | Publishing approved copies back to the library |
| — | Reissue the CDI Procedure with the Control owner wording (docs/FOR-BOBBY-ROLE-WORDING.md) | Dropping amendment A1 |

## 2. To build
1. ☐ **Bobby's demo page** (Control View): his nine fields per control, resolved or not, plus the gaps.
2. ☐ Show the Records Catalogue's **retrieval instructions** on each control's records.
3. ☐ Read the **check frequency** from the document (the "Monitoring" field), so records schedule themselves.
4. ☐ An **Audit Log page** in OrgOS (the entries are written; there is no screen to read them yet).
5. ☐ The checks not built yet: V13, V16 to V19, V21, V24 (V05, V06 wait on Bobby #5; V20 is enforced at approval but not shown as a check).
6. ☐ Silent misses still possible: a control with fewer than 3 fields, scanned PDFs, files loose at the top of the library folder, a document that states roles only in sentences.
7. ☐ Tests for the scheduled jobs, strategic risks, Org Roles routes, the purge and intake runs.

## 3. Yours to do (before the purge)
- ☐ Push, pull on the server, `cd frontend && npm run build`, restart.
- ☐ Add the new SharePoint columns and choice values (docs/GO-LIVE-CHECKLIST.md §2): run `python scripts/provision_sharepoint_columns.py` (dry run) then `--apply`, and add the new choice values by hand.
- ☐ Run `python scripts/fix_intake_items.py` and, if right, `--apply` (removes the blanket "ISO 27001, ISO 9001, NDPA" from 42 items).
- ☐ Try on one document: arrival → role problems on the card → Fix CDI issues per control → approve → accept → records → Standards Map.
- ☐ Then the purge, in the order in docs/GO-LIVE-CHECKLIST.md §11 (`reset_data.py` backs up first).
- ☐ Set up the **Power Automate** flow for late or missing evidence; confirm intake is scheduled (`crontab -l`).

## 4. The rollout
About 120 documents to go through convert → fix roles → approve → accept, domain by domain: Standards before the Procedures that carry them out. Most still write "Accountable / Executing" or a field name where a role belongs: the role check flags each one on arrival.
