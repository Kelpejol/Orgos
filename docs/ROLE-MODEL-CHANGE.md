# Role model change: Control owner and Document owner

*22 Oct 2026. From Bobby. This is the checklist of every part of OrgOS the change touches. Update the status as each is done.*

Status: ✅ done · 🔨 in progress · ✅ not started · — not affected

---

## 1. The change

**Before.** Every control had an "Accountable / Executing" line, read as two roles. Eight CDI controls put the words "Control Owner" or "Document Owner" in that line as a placeholder with no real role behind it, so they stayed Blocked. Roles were only checked after approval, when a control turned Blocked.

**Now (Bobby).**
1. A control has **one** responsible role, the **Control owner**, **stated in the control itself**. There is no "Accountable" and no "Executing".
2. A document has a **Document owner** (the owner on its cover).
3. The documents are **updated** to say this.
4. A role named in a document **must exist in Org Roles**. If it does not, the CDI check catches it while the document is being written:
   - it suggests the closest **existing** roles ("do you mean …?");
   - the author can **use** a suggestion (the document text is changed to the official name), **change it** to something else, or **create the role**, which opens Org Roles with the name filled in.

**Confirmed with Bobby:** exactly one role per control; he will update CDI Annex C and V08; "use this role" changes the document text.

**Consequences.**
- The "Control Owner" question (and the functional-role and "platform check" questions) in our email to Bobby no longer need an answer.
- The "executing role" item on the to-do list disappears. The evidence for a control is the Control owner's to produce.
- **Org Roles is the role register** until the organogram arrives. When it fills Org Roles, nothing in this design changes.
- The role check (V07) can be built now.

---

## 2. Rules we follow while doing it

- **Never claim the CDI says something it does not.** Until Bobby reissues the Procedure, OrgOS carries this change as a labelled **amendment** on top of the Procedure's own text, shown on the Document Standards page. When the Procedure is reissued with the change, the amendment is removed.
- **Suggestions come only from roles that exist.** Nothing is invented. A job title alone is never authority.
- **Old documents keep working.** A document still written "Accountable / Executing" is read as before (the accountable role is taken as the owner), and the check tells its author to move to "Control owner".
- **A fix to a document is scoped.** "Use this role" changes only the role value in a role field, never the same words in running text.
- **Nothing silent.** A role that cannot be matched, a field that cannot be read, a fix that cannot be applied: each is said, on screen.

---

## 3. Every part that changes

### A. The standard itself
| Part | Today | Change | |
|---|---|---|---|
| `doc_standards/cdi_reference.json` and `checks.reference()` | Annex C lists "Accountable role" and "Executing role or system"; V08 names both | An **amendment layer** (`cdi_amendments.json`) replaces them with "Control owner" and rewrites the V08 wording. Shown as "Amended" on the Document Standards page | ✅ |
| `scripts/build_cdi_reference.py` | Builds the reference from the Procedure | Warns if a listed amendment is already in the Procedure (so it can be dropped) | ✅ |
| Wording for Bobby | — | Exact replacement text: see `docs/FOR-BOBBY-ROLE-WORDING.md` | ✅ |

### B. Reading documents
| Part | Today | Change | |
|---|---|---|---|
| `cdi/fields.py` aliases | "control owner" is one more spelling of the responsibility line | **Control owner** becomes its own field; "Accountable / Executing" and the other spellings stay as the legacy form | ✅ |
| `cdi/fields.py` `split_responsibility` | Splits on "/" and ";" into two roles | Not used for a Control owner: the whole value is **one** role. Still used for the legacy form | ✅ |
| `cdi/model.py` | `Responsibility(accountable, executing, …)`; label "Accountable / Executing" | Records whether the **Control owner** form or the legacy form was used; label becomes "Control owner" | ✅ |
| `cdi/parser.py` | Builds the responsibility; raises an "ambiguous: where does it divide accountable from executing" finding | Reads a Control owner as a single role (no ambiguity possible); counts it as the responsibility core field for the "at least 3 fields" rule; a table column headed "Control owner" is read | ✅ |
| Document header | Owner read from the cover | Unchanged: this is the **Document owner** | — |

### C. Control definitions (what review and the Register hold)
| Part | Today | Change | |
|---|---|---|---|
| `control_register/definitions.py` | Candidate carries accountable, executing, `responsibility_as_written`; message "could be one role or two" | Candidate carries the **control owner**; accountable = executing = that role for the new form; the "one role or two" message applies only to the legacy form; label "Control owner" | ✅ |
| `control_register/definitions.py` `decide_status` | Active only if the accountable role is a group | Same rule, same role: the control owner. Message names the **Control owner** | ✅ |
| `control_register/sync.py` `control_fields` | Writes `OwnerRole` from the accountable role | Unchanged value; comment updated | ✅ |
| `control_register/router.py` | Shows `OwnerRole`, resolves its people | Unchanged | — |

### D. Screens
| Part | Change | |
|---|---|---|
| `components/shared/ControlDefinitionReview.jsx` | Row label "Accountable / Executing" → "Control owner" (legacy documents show what they wrote) | ✅ |
| `pages/ControlRegister/ControlDefinitionView.jsx` | "Accountable" / "Executing" rows → one "Control owner" row; a legacy control that still has two shows them as before, marked legacy | ✅ |
| `pages/ExtractionReview` ("If accepted" text) | "Active if its accountable role is recognised" → "…its control owner is recognised" | ✅ |
| `pages/RecordTracker`, `StandardsMap` | Show `OwnerRole` | — |

### E. The role check (new)
| Part | Change | |
|---|---|---|
| `doc_standards/roles.py` (new) | Org Roles as a role book: exact and alias matching; scored suggestions from existing roles only | ✅ |
| `doc_standards/service.build_context` | Loads Org Roles (names and aliases) into the context | ✅ |
| `doc_standards/checks.py` **V07** | Built: every control's Control owner, the Document owner, and the cover approvers must exist in Org Roles. A placeholder ("Control Owner", "Document Owner", "Custodian Role") is called out as a field name, not a role. Findings carry the role and its suggestions | ✅ |
| Legacy-form check | A control still written "Accountable / Executing" is reported with the instruction to move to "Control owner" | ✅ |
| `lifecycle/router.py` **role-fix** endpoint | "Use this role": changes the role value (only in role fields) in the item's own working copy; refused unless in Review; respects the document write mode; the original is never changed | ✅ |
| **Alias** endpoint (Compliance) | "Keep my wording": adds the spelling as an alias of the chosen role, then controls re-check | ✅ |
| `StandardResults.jsx`, `StandardCheckPanel.jsx` | Under a V07 finding: the suggestions, **Use this role**, **Keep as alias**, **Create role** | ✅ |
| **Create role** | Opens Org Roles with the name filled in (`GroupsPanel`, `App.jsx` navigation) | ✅ |
| `groups/` | Already re-checks every control when a role changes | ✅ |

### F. Evidence
| Part | Change | |
|---|---|---|
| `evidence/obligations.py` | Owner was "executing, else accountable"; the new form has one role, so the owner is the **control owner**. Legacy controls behave as before | ✅ |
| Custodian (Records Catalogue) | Unchanged: who holds the record | — |

### G. Gaps
| Part | Change | |
|---|---|---|
| `agents/gap_analyzer/control_gaps.py` | "name no single accountable role" → "name no control owner"; the "ambiguous" case only for the legacy form; text about "accountable role and the executing role" updated | ✅ |

### H. The Document Standards engine
| Part | Change | |
|---|---|---|
| V08 (`checks.py`) | A control must state a **Control owner** (not accountable and executing) | ✅ |
| V01 | Document owner stays the cover's Owner | — |
| Standard tab | Shows the amendment and the new Annex C rows | ✅ |
| Convert to CDT | Cover Owner unchanged; a legacy "Accountable / Executing" line in the body is left as written (conversion never rewrites body text) | — |

### I. Lifecycle
| Part | Change | |
|---|---|---|
| Review card panel | Shows the role suggestions and actions (see E) | ✅ |
| Approval | Approvers stay people; their *roles* on the cover are checked by V07 | ✅ |

### J. The demo page (Control View)
| Part | Change | |
|---|---|---|
| Responsible role | **Control owner**, resolved to people through Org Roles. No accountable/executing split | ☐ (page not built yet) |

### K. Tests
`tests/cdi/test_fields.py`, `test_parser.py`, `test_real_documents.py`, `test_library.py`, `tests/cdi/builders.py` (a Control owner control), `tests/control_register/*`, `tests/evidence/test_obligations.py`, `tests/agents/test_control_gaps.py`, `tests/doc_standards/test_checks.py` and `helpers.py`. New tests for roles matching, suggestions, V07, role-fix, alias, and the legacy-form check. ✅

### L. Documents
`docs/HOW-ORGOS-WORKS.md` (sections 5, 10, 11), `docs/DESIGN-DOCUMENT-STANDARDS-AND-ROLES.md` (Part B and the Ask-Bobby list), `docs/REMAINING-WORK.md`, `docs/GO-LIVE-CHECKLIST.md`. ✅

---

## 4. Not affected

- **The old AI extractor** (`agents/extractor`, `ProposedOwnerRole`): it handles contracts, job descriptions and audits, not CDI documents.
- **The Tier-1 Role Register** (`grc/`: role titles, job-description references): a different list.
- **A Lifecycle item's person owner** (`OwnerEntraId`): the person managing the item, not a role.
- **Approvers** are people. Only the *role names* on the cover are checked.
- **The Records Catalogue custodian.**
- **Controls already accepted** stay as they are; they re-check when a role changes.

---

## 5. Order of work

1. The amendment layer, and reading **Control owner** as one role.
2. Role matching and suggestions; V07; the legacy-form check.
3. The role-fix and alias actions; the Create-role link; the screens.
4. The renames across definitions, screens and gap messages; evidence owner.
5. Tests and documents; the wording for Bobby.
