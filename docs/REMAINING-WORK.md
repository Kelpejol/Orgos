# OrgOS — what is left to do

*Agreed 22 Oct 2026. Grouped by what each item is waiting for. Update the status as things move.*

Status: ✅ done · 🔨 being built · ⏳ waiting · ☐ not started

---

## Done so far
- ✅ One way in: controls enter only when a document is approved in Document Lifecycle.
- ✅ Pilots: Identity, then the CDI Standard and its procedures.
- ✅ Intake reads type, code, title, department and standards from the document instead of guessing.
- ✅ Changing a role on Org Roles re-checks every control at once.
- ✅ Edit in Word on a Lifecycle item.
- ✅ Document Standards page: the standard, check a document, convert to CDT (13 of 24 checks; 5 conversion proofs).
- ✅ The CDI checks as a gate in Lifecycle Review (advisory by default), and one version number with a change summary (22 Oct).

---

## 1. Waiting on Bobby: 8 decisions
| # | Decision | Blocks | Status |
|---|---|---|---|
| 1 | Do V01–V24 replace the old CDI-01 to 15 checker? | Switching the old checker off | ⏳ |
| 2 | Were any documents approved before OrgOS (a "Legacy" tier)? | How strictly existing documents are held | ⏳ |
| 3 | Who is **Control Owner**, and where is it recorded? | 8 Blocked controls | ✅ answered: one Control owner per control, in the control itself |
| 4 | Do Document Owner, Control Owner and Custodian sit in the Role Register? | V07; resolving 24 controls | ✅ answered: Control owner and Document owner only; roles live in Org Roles |
| 5 | Implement the two-step approval route (First Pass, Final) by domain? | V05, V06 | ⏳ |
| 6 | Which libraries are the **published** and **archive** libraries? | Publishing approved copies properly | ⏳ |
| 7 | Do "platform check Vnn" entries name the validation platform itself? | Resolving the executing role | ✅ no longer needed (no executing role) |
| 8 | **The organogram** (via Daniel and Wani) | Not needed: Org Roles is loaded from the job descriptions and staff register | ✅ dropped |

## 2. Was waiting on the organogram (no longer: Org Roles is loaded from the job descriptions and staff register)
- ⏳ The Role Catalogue and Role Register: titles, holders, acting holders, vacancies.
- ⏳ Controls with an official accountable role turn Active by themselves.
- ⏳ Resolving a **person** for each role.
- ⏳ Checks V05 to V07 (approval route, roles exist).
- ⏳ Two-step approval (First Pass and Final Approval).
- ⏳ Suggested role matches in the review queue (accepting one adds an alias).

## 3. To build
**In progress (22 Oct): the role model change from Bobby.** One Control owner per control and a Document owner, no Accountable/Executing; roles checked against Org Roles with suggestions and a Create-role link. The full checklist of every part it touches is in **[ROLE-MODEL-CHANGE.md](ROLE-MODEL-CHANGE.md)**. It answers Bobby questions 3, 4 and 7, and removes the "executing role" item.

**Core**
1. ✅ Put the new checks into the Lifecycle Review gate, running beside the old ones until Bobby answers #1. *(Built 22 Oct: a "Document standard" panel on the Review card; mode `advisory` by default, `enforce` when you are ready; FLAGs decided by Compliance with a reason. To do on your side: add the `StandardsDecisions` column, and choose when to switch to `enforce` once Bobby answers #1.)*
2. ✅ Fix versions: one number with no "R", a change summary for new versions, approval stamping the cover from the Register. *(Built 22 Oct. To do on your side: run `scripts/migrate_versions.py` to rewrite existing "R02" entries as "02". Publishing to the published and archive libraries still waits on Bobby #6, item 13.)*

**Next**

3. ☐ **Bobby's demo page**: the control view with his nine fields per control, resolved or not, plus the gaps.
4. ☐ Show the Records Catalogue's **retrieval instructions** on each control's records.
5. ☐ Read the **check frequency** from the document (CDI's "Monitoring" field), so records can schedule themselves.
6. ☐ **Executing role handling**: a role versus a system, and who uploads the evidence.
7. ☐ An **Audit Log page** in OrgOS.

**Later**

8. ☐ The checks not built yet: V13, V16 to V19, V21, V24 (V05 to V07 wait on the organogram; V20 comes with item 2).
9. ☐ **Silent misses** the new checks don't report yet: a control with fewer than 3 fields (dropped silently), scanned PDFs, files loose at the top of the library folder, one Standard quietly overriding another.
10. ☐ **Retiring things**: a document or control removed from the library is currently only reported, not withdrawn.
11. ☐ Decide whether the old extractor tools stay (they also handle contracts, job descriptions and audits).
12. ☐ Look into the 3 old Microsoft-sign-in tests that have always failed.
13. ⏳ Publish approved copies to the published library and move the old version to the archive (needs Bobby #6).

## 4. Yours to do
- ☐ Send Bobby the questions.
- ☐ **Trial one conversion** on the Document Standards page, open the working copy in Word, and report what you see.
- ☐ Reject the 8 old-extractor items in Extraction Review.
- ☐ Confirm **intake is scheduled** on the server (`crontab -l`).
- ☐ Set check schedules on the CDI and Identity records.
- ☐ Set up the **Power Automate** flow for late or missing evidence.
- ☐ Still unconfirmed live: the Identity revision result (R02, nothing new in review) and Edit in Word.

## 5. Document fixes for authors
The engine can now say exactly what to fix.
- 8 documents have no document code.
- 23 documents define controls with no standards mapping; 17 lack another required field.
- 29 file names carry "Draft", a version or a date.
- 7 documents have controls with no risk statement, or a risk ID.
- Three procedures still cite the retired control DP-002.
- Four IT procedures reworded the IT Standard's controls.

## 6. The rollout
About 120 documents still to go through convert → fix → approve → accept, domain by domain: Policy first, then Standard, then Procedures. Identity and CDI are done; the other Information Security families are the natural next batch.

---

**Order we agreed:** items 1 and 2 → Bobby's demo page → the rest, while Bobby answers and the organogram arrives.


---

**Role model (Control owner / Document owner): built** (V07, suggestions, Use this role, Keep as alias, Create role, renames, tests). Wording for Bobby: `docs/FOR-BOBBY-ROLE-WORDING.md`. Remaining: reissue of the Procedure by Bobby; the Control View demo page.
