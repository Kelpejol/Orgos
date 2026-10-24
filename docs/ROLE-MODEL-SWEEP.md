# Role-model sweep

## Decisions and implementation status

1. **D1 — DONE — Multiple Control owners at review.** Task A implements refusal, not Blocked acceptance. `review_queue/acceptance.py:definition_refusal` uses names_several/is_placeholder before any register write; both single and bulk acceptance use it. The reason names the Control ID and owner text and instructs the document author to revise to exactly one role in Org Roles. Both queue cards show the same reason and disable acceptance. Bulk returns each refusal separately and proceeds with eligible items. V07 checks invalid spellings before RoleBook exact/alias lookup. Valid older Accountable / Executing documents remain readable and retain their existing owner interpretation.
2. **D2 — DONE — Legacy queue and policy entry points.** Keep contracts, regulatory documents, JDs and audits. A shared gate refuses controlled policy/procedure/standard/SOP extraction through text, file, SharePoint, the low-level model runner and bulk extraction, with Document Lifecycle approval / approved-library guidance. Existing AI-derived policy proposals also cannot be accepted; deterministic ControlId definitions remain on their approved-library path. Audit severity and evidence-preview defects are fixed below. Regulatory authority/role semantics remain deferred under D3.
3. **D3 — One role authority across resolution and permissions.** Recommend Org Roles/RoleBook for recognized names, aliases and holders. Decide compatibility for legacy Entra-title-based records, permission checks, gap detection and traffic lights before removing the resolver fallback or closest-title prompt behavior.
4. **D4 — Legacy evidence ownership.** Decide how independently assigned legacy EvidenceOwnerRole values should migrate to the Control owner. Preserve the older-form executing-else-accountable rule and Records Catalogue custodian until that policy is explicit.
5. **D5 — DONE — Assignment & Ownership navigation.** Keep the existing JD-to-document, document-to-JD, conflict and library decisions. Pending document findings have a “Fix role spelling in document” link to Document Lifecycle, carrying the source code and focusing matching entries. Guidance points to the existing Document standard “Use this role” / “Create role” and “Fix CDI issues” actions; a document absent from Lifecycle is directed to + Revise existing. No alternate role editor or membership action was added. An unfamiliar role string is not automatically classified as a spelling mistake.
6. **D6 — Remediation role proposals and stored data.** Decide how contextual labels such as Document Owner and freely proposed LLM roles become actual existing-role assignments. Do not guess role names, rewrite historical rows, recheck live controls, migrate evidence or edit catalogues in this sweep.
7. **D7 — Chat ownership retrieval/indexing.** Recommend deterministic ControlId retrieval, Org Roles member resolution, correct empty personal results, role-aware vector metadata and an explicit answer policy. Reindexing changes data and needs separate authorization.

## Scope and method

24 October 2026. Read CLAUDE.md, ROLE-MODEL-CHANGE.md and FOR-BOBBY-ROLE-WORDING.md, then reviewed the eight requested areas in order. Both pasted requests were applied; the second adds self-review and restricts docs commits to this report. No live SharePoint reads/writes, import --apply, status rechecks, reset scripts or vector rebuilds are part of this review. Screenshots are assessed against source paths and synthetic fixtures, not reproduced against the live site.

**Original wording sweep:** 74 reviewed findings: 31 fixed through wording/comments and 43 left with reasons. Task A subsequently completes F01, F02, F09, F20, F73 (audit defect) and F74: 37 findings addressed and 37 retain their earlier disposition. These counts include intentional compatibility/source-provenance findings, not just defects. The written review was created before the fixes; this final version records the actions and source lines after them.

## Findings in review order

- **F01 — DONE — Extraction Review.** `review_queue/acceptance.py:definition_refusal`; `review_queue/router.py:_definition_accept_cascade`, `accept_document_definitions`; both review screens and `ControlDefinitionReview.jsx`. Refuse a multi-role or field-name Control owner before any writes, even if that literal spelling was registered. Show the reason on collapsed cards and disabled Accept actions; bulk reports individual refusals while accepting the others. Refused items remain pending and are never accepted as Blocked. Existing single-owner status rules are unchanged (D3).

- **F02 — DONE — Extraction Review.** `doc_standards/checks.py:v07`. is_placeholder/names_several now run before RoleBook exact/alias lookup, so invalid registered names and aliases cannot bypass V07. Existing valid alias, slash/and role-name and older-form outcomes remain covered.

- **F03 — FIXED — Extraction Review.** `frontend/src/pages/ExtractionReview/index.jsx:188`. The legacy chain preview says Owner rather than Control owner. **Action:** Use Control owner; preserve the stored ProposedOwnerRole value and cascade.

- **F04 — FIXED — Extraction Review.** `frontend/src/pages/ExtractionReview/index.jsx:749`. The generic Fields missing badge does not distinguish missing control-definition fields from legacy extractor completeness. **Action:** Label the definition badge Control fields missing and clarify its tooltip. No completeness calculation changed.

- **F05 — FIXED — Extraction Review.** `frontend/src/pages/ExtractionReview/index.jsx:827`; `frontend/src/pages/AIReviewQueue/index.jsx:531`; `frontend/src/components/shared/reviewWording.js:2`. Decided cards repeat Accepted — Accept and use raw decision wording for edited acceptance. **Action:** Show Accepted or Accepted after edits using a shared display-label helper. Stored status/decision enums remain unchanged.

- **F06 — FIXED — Extraction Review.** `frontend/src/pages/ExtractionReview/index.jsx:363`; `frontend/src/pages/AIReviewQueue/index.jsx:587`; `frontend/src/pages/Extractor/index.jsx:872`. Owner role / Proposed owner does not identify which owner is meant. **Action:** Use Control owner for editing and Proposed control owner for legacy model proposals. Do not relabel a proposed value as a confirmed role.

- **F07 — FIXED — Extraction Review.** `frontend/src/pages/ExtractionReview/index.jsx:237`; `frontend/src/pages/AIReviewQueue/index.jsx:163`. The legacy evidence panel/edit hint treats a directory job title as authority and does not distinguish its independently stored evidence owner. **Action:** Label this Record owner (legacy extraction); replace the job-title hint with a role-in-Org-Roles hint. Separate evidence-owner behavior remains unchanged pending D4.

- **F08 — LEFT — Older review queue.** `review_queue/router.py:160`; `frontend/src/pages/AIReviewQueue/index.jsx:587`. Accountable Department Head is source/model data, not a hard-coded UI label to replace with a guessed role. **Action:** Keep the value as written. Org Roles/V07 must decide whether it is a real role; no live data was read or rewritten.

- **F09 — DONE — Older review queue.** `agents/extractor/ollama_client.py:require_legacy_extraction`; `agents/extractor/service.py`; `sharepoint/router.py`; `scripts/bulk_extract.py`; `review_queue/acceptance.py`. Controlled policies/standards are refused at legacy extraction entry points and legacy acceptance, with the Document Lifecycle / approved-library route stated. Bulk prints REFUSED and the reason without downloading or extracting those files. STD/SOP codes and Standard filenames are recognised; NDA filename matching uses a word boundary so “Standard” is not mistaken for a contract. Contract, regulatory, JD and audit pipelines remain enabled.

- **F10 — LEFT — Older review queue.** `agents/extractor/ollama_client.py:210`; `agents/extractor/service.py:786`. Legacy role prompts select the closest directory title, and the service combines directory titles with Org Roles names. This is not V07 role matching. **Action:** D3: recommend preserving the written role and presenting RoleBook suggestions for an explicit choice. Prompt and matching behavior left unchanged.

- **F11 — LEFT — Older review queue.** `review_queue/router.py:310`; `review_queue/router.py:1201`. The legacy accept cascade and preview make a control Active for any nonempty owner string, without checking Org Roles. **Action:** D3: align with registered-role validation only after agreeing the legacy-flow policy. No status logic changed.

- **F12 — LEFT — Older review queue.** `review_queue/router.py:340`. Legacy evidence rows can have an independent EvidenceOwnerRole/override, and a blank existing evidence-owner field can suppress fallback to the Control owner. **Action:** D4: agree how legacy evidence ownership should migrate; preserve existing contract/JD/audit behavior and all fields.

- **F13 — LEFT — Older review queue.** `agents/extractor/service.py:432`; `frontend/src/pages/ExtractionReview/index.jsx:144`. 75% Low comes from a default 0.75 extraction score and the existing <80% Low threshold; it is not a statement of role validity. **Action:** Retain confidence for legacy AI items. Definition cards already show From document instead of a score.

- **F14 — LEFT — Older review queue.** `frontend/src/pages/AIReviewQueue/index.jsx:76`; `review_queue/router.py:563`; `control_register/router.py:415`. Mark false positive and Request 2nd review still have queue/review workflows. A reviewer is a person, not the Control owner. **Action:** Retain these decisions and enum values; decide future legacy-screen scope under D2, not through label removal.

- **F15 — LEFT — Older review queue.** `control_register/sync.py:185`; `review_queue/router.py:160`; `agents/classifier/service.py:180`; `scripts/bulk_extract.py:265`; `scripts/provision_sharepoint_columns.py:157`. ProposedOwnerRole remains a SharePoint compatibility column; sync also puts the document-stated Control owner there for definition queue rows. **Action:** Keep its name and mapping. In definition rows Candidate is authoritative; the column name does not mean that the owner was inferred.

- **F16 — FIXED — Older review queue.** `review_queue/router.py:1172`. The impact warning promises a future Role Catalogue and implies only library sync clears a blocked role. **Action:** Refer to the Control owner in Org Roles and the existing role-change recheck / next library sync.

- **F17 — FIXED — Older review queue.** `review_queue/router.py:412`. Definition acceptance docstring calls the current owner the accountable role. **Action:** Use Control owner and Org Roles, preserving all cascade logic.

- **F18 — FIXED — Older review queue.** `frontend/src/pages/Harmonisation/index.jsx:499`. The empty state claims role-vocabulary comparison and says the classifier is not built, though the classifier currently detects duplicate controls and conflicts. **Action:** Describe the implemented near-duplicate control workflow; do not invent a role-matching stage.

- **F19 — LEFT — Older review queue.** `agents/classifier/service.py:571`; `agents/classifier/service.py:237`. Classifier compares control statements and contradictory requirements; it does not canonicalise role names through RoleBook. **Action:** Keep its two jobs. Role suggestions/aliases belong to the explicit Org Roles/document workflow; integrating that is D3.

- **F20 — DONE — Assignment & Ownership.** `frontend/src/pages/AssignmentOwnership/index.jsx:RoleDocumentLink`; `frontend/src/App.jsx`; `frontend/src/pages/DocumentLifecycle/index.jsx`. Retained document-gap/conflict/library decisions. Role-spelling guidance links to the existing source-document flow and carries its code; matching Lifecycle entries are focused, and a missing entry has revision guidance. No duplicate role-correction or role-membership flow was introduced. The link is available on pending document findings without guessing that every unregistered role is a spelling error.

- **F21 — FIXED — Assignment & Ownership.** `frontend/src/pages/AssignmentOwnership/index.jsx:613`. Page description only describes JD orphans, omitting conflicts and deterministic library findings already shown here. **Action:** Describe the current cases without changing decisions or routing.

- **F22 — LEFT — Assignment & Ownership.** `ownership/resolver.py:56`; `ownership/resolver.py:166`. OwnershipIndex still resolves Entra job titles and uses the result for has_owner/owns/roles_for_user. This can affect permissions, filters, gaps and traffic lights beyond V07. **Action:** D3: move role authority to Org Roles while explicitly deciding compatibility for legacy items; do not silently change access checks in a wording sweep.

- **F23 — LEFT — Assignment & Ownership.** `ownership/resolver.py:39`; `ownership/resolver.py:67`; `doc_standards/roles.py:34`. OwnershipIndex normalises only case and whitespace; RoleBook also normalises punctuation and and/&. A spelling accepted by V07 can fail ownership resolution, and job-title precedence can hide an agreed alias. **Action:** D3: canonicalise through RoleBook before looking up members; preserve explicit conflict behavior. Left for a behavior decision.

- **F24 — FIXED — Control Register.** `frontend/src/pages/ControlRegister/index.jsx:114`; `control_register/router.py:198`; `frontend/src/components/shared/JobTitleInput.jsx:24`. Legacy detail/reassignment labels and placeholders still suggest a job title as a Control owner. **Action:** Use Control owner and an Org Roles hint. Keep reassignment paths, payload keys and the defined-control source guard.

- **F25 — FIXED — Control Register.** `frontend/src/pages/ControlRegister/index.jsx:173`; `frontend/src/components/shared/OwnerDisplay.jsx:43`. Blocked/unresolved guidance tells people to set a real job title and conflates role recognition with assigning people. **Action:** Tell users to check the role in Org Roles and its members; do not claim a directory title is authority or guess the cause of every Blocked state.

- **F26 — FIXED — Control Register.** `control_register/definitions.py:152`; `control_register/definitions.py:156`. Missing/ambiguous-owner messages use accountable as current terminology. **Action:** Name Control owner, mark the ambiguous source as the older responsibility form, and ask for a source-document revision. No predicate or status changed.

- **F27 — LEFT — Control Register.** `frontend/src/pages/ControlRegister/ControlDefinitionView.jsx:81`; `frontend/src/pages/ControlRegister/ControlDefinitionView.jsx:108`. Accountable (older form) / Executing (older form) are intentionally shown when a legacy definition has different values. **Action:** Retain the labelled historical fields; new-form definitions already show one Control owner.

- **F28 — FIXED — Control Register.** `frontend/src/components/shared/ControlDefinitionReview.jsx:107`; `frontend/src/pages/ControlRegister/ControlDefinitionView.jsx:113`. Ambiguous legacy text says the Role Catalogue or Org Roles settles the line, rather than telling the author to revise the definition. **Action:** Explain that the older responsibility line needs a source-document revision naming one Control owner in Org Roles. Keep acceptance-as-Blocked behavior.

- **F29 — LEFT — Control Register.** `control_register/router.py:207`; `frontend/src/pages/ControlRegister/index.jsx:56`; `frontend/src/pages/ControlRegister/index.jsx:291`. The defined-control view, existing All/Active/Blocked/Legacy filters and stored BlockedReason display already use the current definition model. **Action:** Keep the source-document ownership guard, filters and data rendering. Historical BlockedReason text would need a data recheck/migration, not a text substitution.

- **F30 — FIXED — Records.** `frontend/src/pages/RecordTracker/index.jsx:708`; `frontend/src/pages/RecordTracker/index.jsx:599`. The legacy record reassignment UI says Owner role (job title) and offers a directory-title placeholder. **Action:** Use Record owner role and an Org Roles hint. Obligation rows continue to show Produced by and prohibit independent ownership changes.

- **F31 — LEFT — Records.** `evidence/obligations.py:119`; `control_register/definitions.py:57`; `cdi/parser.py:763`. Obligations use executing else accountable. This is correct for the supported older form; the new form stores its single Control owner in both compatibility fields. **Action:** Keep the expression and legacy fallback. It does not create two owners for a new-form definition.

- **F32 — LEFT — Records.** `records_catalogue/model.py:41`; `frontend/src/pages/ControlRegister/ControlDefinitionView.jsx:56`. Records Catalogue custodian is who keeps the record, not a second owner of its control. Source custodians may include Accountable Department Head. **Action:** Retain custodian fields, catalogue data, retention rules and Kept by display untouched.

- **F33 — FIXED — Records.** `record_tracker/router.py:440`. The reassignment endpoint docstring describes a real job title even though defined obligations are source-owned and cannot be reassigned here. **Action:** Describe legacy-row reassignment, the obligation guard and Org Roles without changing validation or writes.

- **F34 — LEFT — Records.** `record_tracker/router.py:150`; `standards_map/router.py:59`. Record authorization/filtering and map ownership still inherit the resolver job-title fallback. **Action:** Same behavior decision as D3; no authorization or traffic-light changes.

- **F35 — FIXED — Gap analysis / Standards Map.** `agents/gap_analyzer/control_gaps.py:107`. Comments and the visible remediation narrative name a Role Catalogue. **Action:** Replace with Org Roles and the current one-Control-owner wording. Do not choose or add any role.

- **F36 — FIXED — Gap analysis / Standards Map.** `agents/gap_analyzer/service.py:192`. The legacy ownership-gap reason says a role does not match a job title or group, including cases where a registered role simply has no members. **Action:** Report that the Control owner has no resolved role holder and direct review to Org Roles. Preserve all gap conditions.

- **F37 — LEFT — Gap analysis / Standards Map.** `agents/gap_analyzer/control_gaps.py:110`; `agents/gap_analyzer/control_gaps.py:221`. Remediation roles arrays contain Document Owner / Control owner placeholders and a hard-coded compliance role. These are workflow context labels, not proven existing Org Roles names. **Action:** D6: separate responsibility context from actual assigned roles, or resolve a known document/control owner. Do not invent a role or rewrite stored remediation packages.

- **F38 — LEFT — Gap analysis / Standards Map.** `agents/gap_analyzer/service.py:269`; `agents/gap_analyzer/service.py:307`. Legacy LLM remediation can propose a plausible role and falls back to Compliance without RoleBook validation. **Action:** D6: require explicit selection of an existing Org Roles entry before treating a proposal as an assignment; retain current output contracts.

- **F39 — FIXED — Gap analysis / Standards Map.** `standards_map/router.py:47`; `agents/gap_analyzer/service.py:167`; `record_tracker/router.py:141`. Comments/documentation present job-title resolution as the normative role model. **Action:** Describe the Control owner and explicitly identify the still-supported legacy resolver fallback; leave its behavior for D3.

- **F40 — FIXED — Org Roles.** `frontend/src/pages/OrgRoles/index.jsx:165`. People-directory copy labels ERP org_roles access tags as Org roles, conflating application access with registered business roles. **Action:** Label those values Access tags and clarify the People tab comments/search/empty-state wording. Preserve directory data and the Create-role handoff.

- **F41 — FIXED — Org Roles.** `groups/service.py:263`; `groups/service.py:265`; `groups/router.py:112`. User-facing role validation/errors and generic failure contexts still say group. **Action:** Use role in messages/contexts; keep groups function names, /api/v1/groups, OrgOS Groups, column names and cache keys.

- **F42 — FIXED — Org Roles.** `groups/service.py:2`; `groups/router.py:2`; `frontend/src/components/shared/GroupsPanel.jsx:4`. Module/panel comments describe people groups rather than the role register and contain obsolete auto-provisioning claims. **Action:** Describe Org Roles, its holders and the actual on-demand list/column setup. No provisioning behavior changed.

- **F43 — FIXED — Org Roles.** `doc_standards/roles.py:4`; `control_register/status.py:4`. RoleBook and status-recheck comments wait for an organogram / future Role Catalogue. **Action:** State that Org Roles is the role register loaded from JDs and staff titles; Control owner and agreed aliases are authoritative.

- **F44 — LEFT — Org Roles.** `groups/service.py:122`; `groups/service.py:81`; `groups/router.py:109`. Normal list reads may auto-provision a list/columns; mutations schedule status rechecks that update SharePoint. **Action:** No live reads through provisioning helpers, rechecks, alias writes or import --apply were run. Deciding data repairs/rechecks is outside this sweep.

- **F45 — FIXED — Chat assistant.** `agents/nl_search/response_generator.py:253`; `agents/nl_search/response_generator.py:500`; `agents/nl_search/response_formatter.py:73`; `agents/nl_search/response_formatter.py:122`. Control and document answer/context labels are generic Owner / Owner role. **Action:** Use Control owner and Document owner labels without changing retrieved fields, identity resolution or the LLM system policy.

- **F46 — LEFT — Chat assistant.** `agents/nl_search/compliance_search.py:333`; `agents/nl_search/compliance_search.py:779`. ControlId is absent from the mapped result and keyword fields. A query who owns control SWEEP-01 need not retrieve that exact control by its ID. **Action:** D7: add deterministic ControlId lookup and carry the ID through response/context, before semantic fallback. Verified with mocked retrieval, no live calls.

- **F47 — LEFT — Chat assistant.** `agents/nl_search/compliance_search.py:922`; `agents/nl_search/compliance_search.py:717`. Chat uses OwnerEntraId to resolve/filter controls, while role-owned rows intentionally have it empty. It returns the OwnerRole string but cannot report the people holding that role. Personal filtering falls back to all rows when no person-ID match exists. **Action:** D7: resolve Control owner through Org Roles membership and respect empty personal results; keep Document/Lifecycle person owners distinct.

- **F48 — LEFT — Chat assistant.** `review_queue/router.py:394`; `agents/nl_search/router.py:287`; `agents/nl_search/compliance_search.py:832`. Legacy vector indexing stores the accepting reviewer as owner_oid; rebuild omits OwnerRole/ControlId. Semantic fallback can attribute a control to its reviewer or lose its role. **Action:** D7: repair indexing metadata and rebuild only after approval. No vector or SharePoint data changed.

- **F49 — LEFT — Chat assistant.** `agents/nl_search/response_generator.py:52`. The broad chat system prompt permits general role explanations and contains no explicit distinction between an Org Roles entry, a directory title and a field-name placeholder. **Action:** D7: agree and test role-grounded answer policy together with retrieval fixes. Leave prompts unchanged in this wording-only sweep.

- **F50 — LEFT — Chat assistant.** `agents/nl_search/response_generator.py:641`; `agents/nl_search/response_formatter.py:217`; `frontend/src/components/chat/SourcesAccordion.jsx:4`. Procedural steps legitimately involve multiple roles; chat protocol role values user/assistant/system and contact lists are not Control owner fields. **Action:** Retain procedural role lists, chat message roles and source links. No Accountable/Executing UI was found in chat components.

- **F51 — FIXED — Supporting modules.** `lifecycle/router.py:1086`. The no-controls error gives Accountable as the primary control-block example. **Action:** Show Control owner first and explicitly mention support for older Accountable / Executing documents. No parsing rules changed.

- **F52 — FIXED — Supporting modules.** `cdi/model.py:130`. Responsibility docstring states that every block has two roles. **Action:** Document the single-owner form and its two compatibility storage attributes, alongside the legacy split. No model fields changed.

- **F53 — LEFT — Supporting modules.** `cdi/fields.py:276`; `cdi/parser.py:763`; `doc_standards/role_fix.py:37`; `doc_standards/checks.py:391`. Accountable/Executing aliases, compatibility attributes, parser branching and scoped role-field fixes are still necessary to read and amend older documents. **Action:** Preserve cdi/fields.py and cdi/parser.py byte-for-byte, and retain the legacy-form author warning. Do not rename JSON/SharePoint keys.

- **F54 — LEFT — Supporting modules.** `doc_standards/cdi_reference.json:324`; `doc_standards/cdi_amendments.json:11`. The source reference and amendment intentionally quote the older CDI text and specify its replacement. **Action:** Retain provenance and amendment detection; replacing the source text would falsify what the Procedure currently says.

- **F55 — FIXED — Supporting modules.** `README.md:986`; `README.md:282`. README says there is no SharePoint role register and confuses ERP access tags with control ownership, while Org Roles is implemented. **Action:** Clarify Org Roles versus ERP access tags and the retired Tier-1 register; keep environment/list/API names unchanged.

- **F56 — FIXED — Supporting modules.** `CLAUDE.md:4`. The architectural reference still describes retired Tier-1 role routes and an older role source as current. **Action:** Add a prominent current-role-model note distinguishing Org Roles from ERP access tags and marking the older Tier-1 role sections historical. Preserve unrelated project reference material.

- **F57 — FIXED — Supporting modules.** `scripts/sync_control_library.py:11`. Sync script header refers to the future Role Catalogue. **Action:** Say Org Roles; no script execution or sync behavior changed.

- **F58 — FIXED — Supporting modules.** `scripts/reset_data.py:177`. Reset banner calls the protected current register ROLE REGISTER without identifying Org Roles. **Action:** Identify Org Roles as outside the reset list. The script was not run and reset targets are unchanged.

- **F59 — LEFT — Supporting modules.** `lifecycle/domains.py:64`; `agents/cdi_checker/service.py:211`. Verbatim approval-route source quotes and normal accountable-in-prose obligation detection are not the removed two-owner model. **Action:** Preserve quoted source wording and linguistic detection. Commented-out CDI role-check snippets are inactive historical code, not a role source.

- **F60 — LEFT — Guides (report only).** `docs/ROLE-MODEL-CHANGE.md:26`; `docs/ROLE-MODEL-CHANGE.md:128`; `docs/ROLE-MODEL-CHANGE.md:129`. The current change guide still says until the organogram arrives, claims the old extractor excludes CDI documents without an entry-point guard, and claims a separate Tier-1 role list remains. **Action:** Flag this inconsistency with the task/current code. Do not edit or commit this guide: only ROLE-MODEL-SWEEP.md is permitted under docs/.

- **F61 — LEFT — Guides (report only).** `docs/REMAINING-WORK.md:33`; `docs/REMAINING-WORK.md:52`; `docs/REMAINING-WORK.md:57`. The heading drops the organogram dependency, but the body still waits for a Role Catalogue, executing-role work and an organogram. **Action:** Recommend a guide refresh; retain unchanged under the docs-only-report constraint.

- **F62 — LEFT — Guides (report only).** `docs/GO-LIVE-CHECKLIST.md:11`; `docs/GO-LIVE-CHECKLIST.md:146`. The current readiness row correctly describes Org Roles; a later future section still proposes Role Catalogue/role-assignment expansion. **Action:** Keep the correct readiness statement; flag the superseded proposal for a separate guide update.

- **F63 — LEFT — Guides (report only).** `docs/GRC-ARCHITECTURE-PLAN.md:139`; `docs/GRC-ARCHITECTURE-PLAN.md:474`. The older architecture plan proposes a Role Catalogue, scoped/system roles, an organogram and accountable/executing outputs. **Action:** Treat these as superseded design, not current implementation. Some block examples are valid historical parser fixtures. Guide unchanged.

- **F64 — LEFT — Guides (report only).** `docs/GRC-EXTRACTION-AND-RECORDS-EXPLAINER.md:268`; `docs/GRC-EXTRACTION-AND-RECORDS-EXPLAINER.md:344`. The explainer mixes valid source/custodian examples with superseded job-title authority, field-name roles, dual owners and an organogram request. **Action:** Preserve historical examples; recommend updating its present-tense conclusions. No guide edit or copied register data.

- **F65 — LEFT — Guides (report only).** `docs/DESIGN-DOCUMENT-STANDARDS-AND-ROLES.md:3`. An explicit superseded-design banner correctly warns that the body contains the older organogram/Role Catalogue/two-owner design. **Action:** Retain historical body and its warning; current behavior is the task plus V07/Org Roles, not the superseded sections.

- **F66 — LEFT — Guides (report only).** `docs/ORGOS-COMPLETION-PLAN.md:14`. Completion plan still calls Entra job titles plus groups the authoritative role vocabulary. **Action:** Flag for a separate guide update; ERP access tags and job titles do not constitute the role register.

- **F67 — LEFT — Guides (report only).** `docs/CDI-AUTOFIX-DESIGN.md:36`; `docs/DINT-GAP-ANALYSIS-DRAFT.md:86`; `docs/DOCUMENT-TEMPLATING-DESIGN.md:307`. Older design drafts refer to a retired Role Register/potential role creation or approval-role references. **Action:** Keep these as historical design; actual source-role fixes use Org Roles. No new roles, list names or approval behavior introduced.

- **F68 — LEFT — Guides (report only).** `docs/HOW-ORGOS-WORKS.md:208`; `docs/HOW-ORGOS-WORKS.md:321`; `docs/HOW-ORGOS-WORKS.md:475`. The main guide has correct one-owner/Org Roles sections, but also says V07 is not built and suggests retrying after Role Catalogue changes. **Action:** Flag only the stale status/instructions; retain the correct legacy-form explanation and current role model. Guide unchanged.

- **F69 — LEFT — Historical artifacts.** `census.json:2296`; `backups/pre-purge-2026-10-12/AI_Review_Queue.json:41`; `backups/pre-purge-2026-10-12/Document_Lifecycle.json:255`. Ignored snapshots contain old ProposedOwnerRole, Accountable Department Head and source-document text. They are historical stored data, not product labels or the current role register. **Action:** Do not rewrite, stage or copy their contents. The inventory below lists locations only; any stored-data repair is a separate approved task.

- **F70 — FIXED — Supporting modules.** `agents/extractor/schemas.py:60`. An inactive old schema description still says resolved against Role Register. **Action:** Describe a proposed role for review against Org Roles, without activating or changing the schema.

- **F71 — FIXED — Supporting modules.** `org_roles/router.py:71`; `frontend/src/hooks/useGrc.js:283`; `frontend/src/api/grcApi.js:415`; `frontend/src/components/shared/CdtCoverPanel.jsx:6`; `frontend/src/pages/WorkHub/index.jsx:173`; `ownership/__init__.py:2`. Directory APIs, hook/picker comments and cover/ownership comments describe job titles and groups as the authoritative role vocabulary. **Action:** Clarify Org Roles authority, ERP access versus role membership, and the still-existing legacy fallback. Keep every query, picker source, cover rule and authorization predicate unchanged.

- **F72 — LEFT — Supporting modules.** `agents/cdi_checker/service.py:775`; `agents/cdi_checker/service.py:1285`. Legacy CDI-07 prompts still ask for the closest job title and fall back to directory titles when Org Roles is empty or unavailable. This is separate from V07 and from the newer scoped role-fix flow. **Action:** D3: recommend failing closed for authoritative role validation and presenting RoleBook suggestions for an explicit choice. Corrected comments to describe actual fallback conditions; left prompt, fallback and document-edit behavior unchanged.

- **F73 — DONE (audit defect) — Older review queue.** `agents/extractor/ollama_client.py:_parse_response`; `agents/extractor/service.py:_validate_items`. Audit short-key o is retained as severity, not proposed owner; legacy normalized severity tokens are also recognised and removed from the owner field. Explicit audit owner fields remain intact. Tests cover Major through model normalization, enrichment and mocked queue write, plus a full-key Critical finding with an explicit owner. Regulatory o continues to mean authority as before; its broader role-authority decision remains D3.

- **F74 — DONE — Extraction Review.** `review_queue/acceptance.py:legacy_accept_plan`, `legacy_accept_preview`; `review_queue/router.py`; `frontend/src/pages/ExtractionReview/index.jsx`. Execution, read-only impact and card preview share one accept plan. A typed record with an empty description is correctly previewed with its fallback title. EvidenceUndefined string/bool handling and legacy evidence-owner semantics are preserved. Edit mode and confirmation pass current overrides to the same preview endpoint; no second JavaScript predicate decides whether a record is created.

## What the older extractor actually produces

- **Contract/regulatory extraction targets:** statement, risk, proposed owner, clause, deterministic control/evidence suggestions, confidence/completeness and legacy evidence fields. Most are ItemType=Extraction. Policy extraction and its procedural indexing are now gated by Task A; controlled definitions enter through approval and the approved library. Forms, references and evidence samples are non-extraction targets. Bulk extraction skips Unclassified inputs; the direct legacy pipeline has no Unclassified prompt, rather than an additional output stream.
- **Job descriptions:** ItemType=Orphan, responsibility statement, JD_to_Doc direction, potential-orphan classification/reason, plus the common legacy fields. A JD title is source evidence, not registration in Org Roles.
- **Audits:** ItemType=Extraction plus finding statement/type, severity, gap type and remediation text. Task A keeps short-key o as severity through normalization/enrichment; it no longer populates ProposedOwnerRole with severity or silently changes Major to Minor. Explicit owner fields are preserved. Other audit behavior is retained.
- **Classifier:** Zone 3 near-duplicate control findings and Zone 2 contradictory-requirement/conflict findings. It does not populate a Role Catalogue or validate a role through RoleBook. Control definitions from approved-library sync carry ControlId/Candidate and bypass the legacy create-only accept cascade.

## Chat retrieval trace

Using only mocked Graph/entity results, queried **who owns control SWEEP-01** with two synthetic Control Register rows: SWEEP-01 / Review Lead and OTHER-02 / Operations Lead. The returned result contained both controls, did not carry a control_id field, and used Review Lead as the owner display-name fallback without resolving role members. The corrected context label reads Control owner, but the retrieval and holder limitations remain D7. No live register, staff or vector data was queried or persisted. The characterization test documents current behavior and must change when D7 is implemented.

## Original wording-sweep verification and final self-review

- `source myenv/bin/activate && python -m pytest -q --deselect tests/test_graph_client.py`: **850 passed, 8 deselected**, one existing Starlette/httpx deprecation warning. This adds 18 backend regression/characterization cases to the 832 passing baseline.
- `node --test frontend/tests/reviewWording.test.mjs frontend/tests/roleModelComponents.test.mjs`: **7 passed**. Covers accepted/edit-accepted display, preserving other decision enums, registered/directory suggestion labels, unresolved-owner guidance, ambiguous older-form display, both older responsibility fields, the separate record custodian, and both extraction preview types.
- `cd frontend && npx vite build`: **passed**. Vite retains its existing >500 kB chunk-size advisory.
- Self-reviewed the diff as a compatibility change: normalized Python ASTs retain all non-string runtime structure after removing docstrings and wording literals. This checks that wording fixes did not change branch conditions, calls, return shapes or writes. cdi/fields.py and cdi/parser.py are byte-for-byte unchanged, as are extractor prompts, classifier logic, evidence owner derivation and the chat system policy.
- New tests use synthetic documents, controls, records, roles and people with mocked I/O. Existing contract/JD/audit enrichment and both CDI responsibility forms remain covered. No real register contents were copied into code, tests or this report.
- No SharePoint columns/list names, API paths, environment variable names, payload keys, decision enums, role-matching predicates, authorization filters or acceptance policies were changed. No live SharePoint writes, provisioning reads, import --apply, status rechecks, vector rebuilds or reset scripts were run. The uncertainty is explicit in D1–D7 and LEFT findings.
- Commit scope includes only this report under docs/. Existing guides, census/backup files, source archives, the staff register and the pre-existing cdt_templates_out/ directory are excluded from the commit.

## Task A verification and self-review (24 October 2026)

- D1, D2 and D5 are implemented as decided above. F73's audit defect and F74's evidence-preview mismatch are fixed. Other decisions/findings remain out of scope.
- Regression tests first reproduced audit Major becoming Minor/proposed owner, and the evidence-preview regression was also run against the pre-change component: a typed record with no description incorrectly displayed “No record entry”. Both now pass.
- `tests/test_task_a_review.py` covers single and mixed/all-refused bulk acceptance, invalid registered names/aliases in V07, older-form compatibility, all extraction gates including mocked bulk/SharePoint paths, the four supported legacy document types, audit normalization and queue fields, evidence flags/overrides, and an HTTP preview/accept round trip. No real Graph calls.
- `source myenv/bin/activate && python -m pytest -q --deselect tests/test_graph_client.py`: **897 passed, 8 deselected** (47 new backend cases). Warnings: the existing Starlette/httpx warning and the existing extractor HTTP_422 constant deprecation surfaced by the new route tests.
- `node --test frontend/tests/reviewWording.test.mjs frontend/tests/roleModelComponents.test.mjs`: **16 passed**, including collapsed warnings/disabled acceptance on both screens, bulk eligibility, evidence preview, Assignment navigation and Lifecycle guidance.
- `cd frontend && npx vite build`: **passed**, with the existing >500 kB bundle-size advisory. `git diff --check`: **passed**.
- Reviewed every runtime change against older documents and contract/JD/regulatory/audit behavior. `cdi/fields.py` and `cdi/parser.py` are unchanged. Existing older-form parsing and author migration guidance remain. Legacy single-owner activation, evidence undefined/owner rules, regulatory authority proposals, classifier logic and membership permissions are unchanged; D3/D4/D6/D7 remain pending. Policy gates deliberately prevent the former AI policy-control/procedural-index path and do not remove its stored history.
- Assignment navigation offers the existing document fix without guessing whether a responsibility gap is a role spelling mistake. A source code missing from Lifecycle requires the existing revision flow; there is no new document editor here. No other compatibility uncertainty was found in the diff/tests; live browser/SharePoint behavior was not exercised.
- Only this report changes under docs/. No live SharePoint reads/writes, --apply, migrations or reindexing were run. SharePoint column/list names, API paths and environment variable names remain unchanged; computed preview/refusal response fields and optional impact query fields are additive.

## Whole-tree keyword inventory

Before fixes, searched case-insensitively for accountable, executing, Role Catalogue (including intervening whitespace), organogram, Role Register, ProposedOwnerRole, proposed owner, Custodian Role, and Accountable Department Head. The no-ignore sweep found **542 matching lines in 45 files**, including historical ignored snapshots. The search excluded myenv, node_modules, dist, tests, .git, tool metadata, secrets, bytecode/caches, generated cdt_templates_out and logs. It did not extract document archives or workbooks. Additional directory-title/group-authority copy was reviewed under F71–F72 even where it did not contain the requested keywords.

Every matching line is classified below. Locations are **pre-fix** inventory lines so a replaced/deleted phrase is still auditable against the parent commit; F01–F74 above use the final working-tree lines. Stored snapshot contents are intentionally not reproduced.

- `CLAUDE.md` — lines 65, 477, 498, 572, 701, 746, 827, 835, 1145, 1233, 1431, 1631, 1633. **Disposition:** Older Tier-1/source guidance retained as historical beneath the new authoritative note (F56).

- `README.md` — lines 161, 338, 768. **Disposition:** Retired Tier-1 register history/configuration distinction; retained (F55).

- `README.md` — lines 288, 362, 984. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `agents/cdi_checker/service.py` — lines 100, 116, 211. **Disposition:** Compatibility/source-provenance occurrence; retained and reviewed in the findings above.

- `agents/cdi_checker/service.py` — lines 1033, 1035, 1036. **Disposition:** Inactive, commented-out old-check snippet; retained as historical code (F59).

- `agents/cdi_checker/service.py` — lines 1277. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `agents/classifier/service.py` — lines 180, 391, 392, 545. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `agents/extractor/schemas.py` — lines 60. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `agents/extractor/service.py` — lines 581. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `agents/gap_analyzer/control_gaps.py` — lines 15, 78, 107. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `agents/gap_analyzer/control_gaps.py` — lines 90. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `backups/pre-purge-2026-10-12/AI_Review_Queue.json` — lines 41, 254, 465, 536, 821, 1098, 1170, 1239, 1311, 1380, 1451, 1522, 1593, 1664, 1735, 1807, 1878, 1950, 2019, 2090, 2161, 2233, 2303, 2373, 2443, 2583, 2722, 2933, 3146, 3288. **Disposition:** Historical stored/source data; retained, never staged (F69).

- `backups/pre-purge-2026-10-12/Document_Lifecycle.json` — lines 255, 398, 542, 614, 1260, 1404, 1476, 1620, 1692, 1907, 2050, 2554, 2770, 2913, 3344, 3487, 4783, 4855, 4927, 4999, 5071, 5143, 5515, 5659, 5731, 6021, 6093, 6237, 6309, 6594, 6810, 7170, 7315, 7458, 7961, 8176, 8325, 8544, 8689, 8761, 8833, 8979, 9052, 9125. **Disposition:** Historical stored/source data; retained, never staged (F69).

- `cdi/fields.py` — lines 10, 11, 242, 261, 278, 287, 293, 297, 298, 299, 300, 313, 324, 356, 374, 375, 380, 382, 383, 409. **Disposition:** Older-form parser/check keys or placeholder detection; intentional compatibility (F02, F53).

- `cdi/model.py` — lines 130, 131. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `cdi/model.py` — lines 135, 136, 140, 145. **Disposition:** Older-form parser/check keys or placeholder detection; intentional compatibility (F02, F53).

- `cdi/parser.py` — lines 11, 96, 563, 763, 767, 770, 771, 773, 825, 826. **Disposition:** Older-form parser/check keys or placeholder detection; intentional compatibility (F02, F53).

- `census.json` — lines 2296, 2373, 2424, 3171, 3245, 3296, 3722, 4283, 4292, 4334, 4335, 5223, 5231, 5239, 5262, 5270, 5313, 5337, 5373, 5431, 5456, 5508, 5509, 5525, 5526, 5559, 5560, 6280, 9342, 9818, 10232, 10634, 10923, 11288, 11292, 11296, 11300, 11318, 11440, 11448, 11456, 11464, 11472, 11480, 11486, 11488, 11496, 11944, 11945, 12025, 12026, 12113, 12114, 12187, 12188, 12268, 12269, 12349, 12350, 12423, 12424, 12516, 12517, 12603, 12604, 12607, 12608, 12615, 12616, 12632, 12633, 12665, 12666, 12667, 12698, 12699, 12803, 12804, 12877, 12878, 12965, 12966, 13022, 13023, 13103, 13104, 13191, 13192, 13248, 13249, 13305, 13306, 13379, 13380, 13460, 13461, 13524, 13525, 13581, 13582, 13655, 13656, 13722, 13723, 13793, 13796, 13797, 13870, 13871, 13951, 13952, 14025, 14026, 14082, 14083, 14166, 14167, 14233, 14234, 14300, 14301, 14350, 14351, 14417, 14418, 14491, 14492, 14548, 14549, 14550, 14591, 14626, 14629, 14630, 14683, 14686, 14687, 14688, 14757, 14760, 14761, 14762, 14785, 14786, 14824, 14825, 14826, 14912, 14913, 14914, 14976, 14977, 14978, 15064, 15065, 15066, 15107, 15138, 15139, 15202, 15205, 15206, 15300, 15323, 15714, 15722, 16172, 34163, 34164, 34426, 34427, 34719, 34720, 34978, 34979, 35142, 35143, 35423, 35424, 35730, 35731, 35893, 35894, 36058, 36059, 36222, 36223, 36370, 36371, 36606, 36607, 36783, 36784, 36994. **Disposition:** Historical stored/source data; retained, never staged (F69).

- `control_register/definitions.py` — lines 11, 152, 156. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `control_register/definitions.py` — lines 57, 58, 61, 145, 149. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `control_register/status.py` — lines 4, 5. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `control_register/sync.py` — lines 185, 204. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `doc_standards/cdi_amendments.json` — lines 9, 11, 15, 21. **Disposition:** Procedure source / explicit amendment provenance; retained (F54).

- `doc_standards/cdi_reference.json` — lines 39, 44, 218, 324, 325, 329, 330. **Disposition:** Procedure source / explicit amendment provenance; retained (F54).

- `doc_standards/checks.py` — lines 331, 332, 391. **Disposition:** Older-form parser/check keys or placeholder detection; intentional compatibility (F02, F53).

- `doc_standards/role_fix.py` — lines 11, 37. **Disposition:** Older-form parser/check keys or placeholder detection; intentional compatibility (F02, F53).

- `doc_standards/roles.py` — lines 4. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `doc_standards/roles.py` — lines 28, 29. **Disposition:** Older-form parser/check keys or placeholder detection; intentional compatibility (F02, F53).

- `docs/CDI-AUTOFIX-DESIGN.md` — lines 36. **Disposition:** Superseded design/source examples; retained under docs-only-report constraint (F63–F67).

- `docs/DESIGN-DOCUMENT-STANDARDS-AND-ROLES.md` — lines 3, 8, 20, 30, 46, 76, 77, 78, 102, 120, 121, 128, 129, 131, 134, 137, 139, 140, 141, 142, 143, 153, 216, 217, 218, 220, 221, 229, 240, 241. **Disposition:** Superseded design/source examples; retained under docs-only-report constraint (F63–F67).

- `docs/DINT-GAP-ANALYSIS-DRAFT.md` — lines 86. **Disposition:** Superseded design/source examples; retained under docs-only-report constraint (F63–F67).

- `docs/DOCUMENT-TEMPLATING-DESIGN.md` — lines 307. **Disposition:** Superseded design/source examples; retained under docs-only-report constraint (F63–F67).

- `docs/FOR-BOBBY-ROLE-WORDING.md` — lines 5, 11, 13. **Disposition:** Current replacement wording and deliberately quoted older field names; correct, retained.

- `docs/GO-LIVE-CHECKLIST.md` — lines 11. **Disposition:** Current Org Roles readiness row; correct, retained (F62).

- `docs/GO-LIVE-CHECKLIST.md` — lines 146. **Disposition:** Superseded Role Catalogue proposal; report only (F62).

- `docs/GRC-ARCHITECTURE-PLAN.md` — lines 16, 45, 98, 130, 139, 144, 151, 152, 164, 166, 193, 205, 240, 250, 280, 281, 287, 288, 299, 360, 384, 403, 430, 442, 474. **Disposition:** Superseded design/source examples; retained under docs-only-report constraint (F63–F67).

- `docs/GRC-EXTRACTION-AND-RECORDS-EXPLAINER.md` — lines 12, 22, 32, 63, 84, 104, 122, 123, 194, 195, 222, 251, 254, 256, 257, 259, 268, 287, 289, 295, 306, 309, 311, 313, 325, 326, 344, 346, 359, 372, 374, 379, 397, 398, 414, 416, 425, 435, 438. **Disposition:** Superseded design/source examples; retained under docs-only-report constraint (F63–F67).

- `docs/HOW-ORGOS-WORKS.md` — lines 51, 472, 475. **Disposition:** Current model / explicit older-form explanation; correct, retained (F68).

- `docs/HOW-ORGOS-WORKS.md` — lines 208, 321. **Disposition:** Stale status/Role Catalogue instruction; report only (F68).

- `docs/ORGOS-COMPLETION-PLAN.md` — lines 14. **Disposition:** Stale authoritative vocabulary statement; report only (F66).

- `docs/ORGOS-COMPLETION-PLAN.md` — lines 37. **Disposition:** Retirement of older Tier-1 UI; historical fact, retained (F66).

- `docs/REMAINING-WORK.md` — lines 26, 29, 30, 32, 41. **Disposition:** Historical question/change log or corrected no-organogram heading; retained (F61).

- `docs/REMAINING-WORK.md` — lines 33, 34, 52, 57, 87. **Disposition:** Stale pending work/dependency; report only (F61).

- `docs/ROLE-MODEL-CHANGE.md` — lines 11, 14, 25, 35, 46, 53, 55, 56, 62, 63, 64, 70, 71, 72, 80, 81, 91, 97, 102, 105, 116. **Disposition:** Current amendment, older-form history or change checklist; retained (F60).

- `docs/ROLE-MODEL-CHANGE.md` — lines 26, 128, 129. **Disposition:** Stale organogram / extractor-exclusion / retired Tier-1 list statement; report only (F60).

- `evidence/obligations.py` — lines 85, 119. **Disposition:** Explicit older-form evidence-owner fallback; retained (F31).

- `frontend/src/pages/AIReviewQueue/index.jsx` — lines 585, 702. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `frontend/src/pages/AIReviewQueue/index.jsx` — lines 586. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `frontend/src/pages/ControlRegister/ControlDefinitionView.jsx` — lines 81, 106, 108, 109. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `frontend/src/pages/ExtractionReview/index.jsx` — lines 186, 361, 862. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `frontend/src/pages/ExtractionReview/index.jsx` — lines 264, 940. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `frontend/src/pages/Extractor/index.jsx` — lines 872. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `lifecycle/domains.py` — lines 64, 188. **Disposition:** Verbatim approval-route source or ordinary accountable-in-prose usage; retained (F59).

- `lifecycle/router.py` — lines 1086. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `review_queue/router.py` — lines 160, 293, 551, 1200. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `review_queue/router.py` — lines 412, 1173. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `scripts/bulk_extract.py` — lines 265. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `scripts/provision_sharepoint_columns.py` — lines 157. **Disposition:** Stored compatibility key / older-form output or source role; retained (F01–F39).

- `scripts/reset_data.py` — lines 177. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.

- `scripts/sync_control_library.py` — lines 11. **Disposition:** Stale wording/comment corrected; see the FIXED finding for this file.
