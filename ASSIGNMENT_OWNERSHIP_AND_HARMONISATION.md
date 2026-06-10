# Assignment & Ownership and Harmonisation

This document explains how the Assignment & Ownership and Harmonisation areas work in OrgOS, why they exist, what data they use, what decisions reviewers make, and what the workflow should guarantee.

These two areas sit after extraction. Extraction identifies controls, risks, owners, evidence, and document references. Assignment & Ownership and Harmonisation then clean up the organisational meaning of those findings so the compliance chain is complete, consistent, and auditable.

## 1. Big Picture

OrgOS is not only collecting controls. It is building a live compliance chain:

Document -> control -> owner role -> role holder -> evidence -> verification -> standard/gap status.

Assignment & Ownership and Harmonisation protect that chain from two common failure modes:

1. A responsibility exists, but nobody can prove where it is governed or who owns it.
2. The same role or control is described differently across documents, creating duplicates, ambiguity, or conflicting ownership.

Assignment & Ownership focuses on accountability gaps.

Harmonisation focuses on language consistency and duplicate reduction.

Together, they make sure accepted controls are not just stored, but are usable, owned, and traceable.

## 2. What Creates These Items

Assignment & Ownership and Harmonisation items are not manually created from their screens. They are created by backend extraction/classification flows and written into the AI Review Queue.

There are two main creation paths:

1. Extraction creates `Extraction` and `Orphan` queue items.
2. The Classifier creates `Harmonisation` queue items after comparing extracted data against registers.

### 2.1 The Bulk Extraction Script

The main bulk script is:

`scripts/bulk_extract.py`

It scans the configured Compliance SharePoint document library, walks through folders under `settings.compliance_starting_folder`, downloads supported files, classifies the document type, runs extraction, validates the extracted items, then writes them to the AI Review Queue.

The script connects to SharePoint through Microsoft Graph, resolves the compliance drive, walks folders, and processes each remaining file with checkpoint/resume support.

The high-level flow is:

1. Connect to the Compliance SharePoint site and document library.
2. Find the configured starting folder.
3. Walk all child folders and files.
4. Classify each file by folder path, document code, and filename.
5. Skip non-extraction document types.
6. Download the file bytes.
7. Extract text.
8. Run the extraction model.
9. Validate and enrich extracted items.
10. Write queue items to the AI Review Queue.

The same extraction writing logic also exists in:

`agents/extractor/service.py`

That service is used by normal extraction endpoints, while `scripts/bulk_extract.py` is the batch/SharePoint folder processing path.

### 2.2 Which Document Types The Script Understands

Document type classification is defined in:

`agents/extractor/ollama_client.py`

Supported document types include:

| DocumentType | Meaning | Extraction behavior |
| --- | --- | --- |
| `Policy` | Policies, procedures, SOPs | Creates normal Zone 1 `Extraction` items |
| `JobDescription` | Job descriptions/JDs | Creates Zone 2 `Orphan` items |
| `Contract` | Contracts, SLAs, agreements | Creates normal Zone 1 `Extraction` items |
| `Regulatory` | Regulatory/statutory documents | Creates extraction items with obligation fields where present |
| `Audit` | Audit reports, findings, risk assessments | Creates audit/finding-style queue fields |
| `EvidenceSample` | Evidence sample files | Skipped by bulk extraction |
| `Form` | Forms/templates | Skipped by bulk extraction |
| `Reference` | Reference documents | Skipped by bulk extraction |
| `Unclassified` | Unknown document type | Skipped by bulk extraction |

The folder path can determine type first. For example:

| Folder text | DocumentType |
| --- | --- |
| `policies & sops` or `policies and sops` | `Policy` |
| `contracts & agreements` or `contracts and agreements` | `Contract` |
| `job descriptions` | `JobDescription` |
| `regulatory & statutory` or `regulatory and statutory` | `Regulatory` |
| `evidence samples` | `EvidenceSample` |
| `audit & risks` or `audit and risks` | `Audit` |

If the folder path does not classify the file, the document code is checked.

Examples:

| Code pattern | DocumentType |
| --- | --- |
| `-POL-PRO-`, `-POL-`, `-PRO-` | `Policy` |
| `DRG-JD-`, `-JD-` | `JobDescription` |
| `-SLA-` | `Contract` |
| `-FM-` | `Form` |
| `-REF-` | `Reference` |

If neither folder nor code is enough, the filename is checked for words like `job description`, `contract`, `agreement`, `policy`, `procedure`, `sop`, `audit`, `finding`, or `risk assessment`.

### 2.3 What Creates Assignment & Ownership Items

Assignment & Ownership items are created directly from Job Description extraction.

When a document is classified as:

`DocumentType.JD`

the extraction validation code forces:

`extraction_category = Orphan`

That means JD responsibilities are written to the AI Review Queue as:

`ItemType = Orphan`

The relevant code is in:

- `agents/extractor/service.py`
- `scripts/bulk_extract.py`

For JD documents, each extracted responsibility is mapped like this:

| Queue field | Source |
| --- | --- |
| `ItemType` | `Orphan` |
| `DocumentType` | `JobDescription` |
| `ResponsibilityStatement` | Extracted JD responsibility/control-like statement |
| `OrphanDirection` | Defaults to `JD_to_Doc` |
| `OrphanClassification` | Defaults to `POTENTIAL_ORPHAN` |
| `OrphanReason` | Extracted risk/reason, or fallback text |
| `SourceDocumentCode` | Document code derived from filename |
| `SourceDocumentUrl` | SharePoint web URL when available |
| `ReviewStatus` | `Pending Review` |

So the immediate source for Assignment & Ownership is mainly:

Job Description documents in the SharePoint folder tree.

The reason is that JDs list responsibilities. OrgOS treats each JD responsibility as a possible accountability that must be checked against governing policies/procedures.

Current behavior:

The extractor creates mostly `JD_to_Doc` orphan items. That means the system is currently strongest at detecting:

JD says someone is responsible for something, but the governing policy/procedure may not exist or may not have been linked yet.

Intended behavior:

The full Zone 2 design should also create `Doc_to_JD` items where a policy/control assigns a role but the role's JD does not contain that responsibility. That requires comparing accepted/extracted policy controls against JD responsibility data.

### 2.4 What Creates Harmonisation Items

Harmonisation items are created by the Classifier agent, not directly by document extraction.

The classifier endpoint is:

`POST /api/v1/agents/classify`

The frontend button is in:

`frontend/src/pages/Harmonisation/index.jsx`

The backend router is:

`agents/classifier/router.py`

The classifier implementation is:

`agents/classifier/service.py`

The classifier reads:

- AI Review Queue extraction items.
- Role Register entries.
- Confirmed Control Register entries.

Then it writes new AI Review Queue items with:

`ItemType = Harmonisation`

### 2.5 Classifier Job 1: Role Variant Detection

Role variant detection compares extracted owner role terms against the Role Register.

It reads `ProposedOwnerRole` from queue items where:

`ItemType = Extraction`

It then compares those role terms with Role Register titles.

If the role term does not exactly match a role title, it creates a Harmonisation item.

This can happen from several document types because owner roles can be extracted from:

- Policies
- Procedures
- Contracts
- Regulatory documents
- Audit/risk documents where controls/findings mention owners

Example:

Policy extraction finds:

`ProposedOwnerRole = InfoSec Lead`

Role Register contains:

`Information Security Lead`

The classifier creates:

`ItemType = Harmonisation`

with variant terms:

`InfoSec Lead, Information Security Lead`

The reviewer then decides whether to merge, keep separate, partially merge, or rename/standardise.

### 2.6 Classifier Job 2: Near-Duplicate Control Detection

Near-duplicate detection compares control statements from:

- AI Review Queue extraction items.
- Confirmed Control Register items.

It normalises the text and uses similarity scoring.

Current threshold:

`0.80`

If two controls from different source documents are similar enough, the classifier creates a Harmonisation item.

This can be created from:

- Policies and procedures that repeat the same control.
- Contracts that contain controls already covered by policy.
- Regulatory extraction that overlaps with internal controls.
- Audit/risk documents that reference control requirements similar to existing controls.

The Harmonisation item stores:

| Queue field | Source |
| --- | --- |
| `ItemType` | `Harmonisation` |
| `ControlStatement` | First duplicate control statement |
| `VariantTerms` | Text containing both compared controls |
| `VariantFrequency` | Similarity score summary |
| `SourceDocumentCode` | Source document pair |
| `ConfidenceScore` | Similarity score |
| `ReviewStatus` | `Pending Review` |

### 2.7 Classifier Job 3: Conflict Detection

The classifier file header describes a third job:

Conflict detection.

Purpose:

Identify controls from different documents that define contradictory requirements for the same obligation.

Current implementation note:

The current classifier code describes this as part of the design, but the active implementation shown in `agents/classifier/service.py` currently writes role variant and near-duplicate Harmonisation items. Conflict item writing is not yet fully implemented in the active code path.

Intended behavior:

Conflict detection should create Assignment & Ownership or conflict review items when two documents disagree on ownership, frequency, requirement wording, or required evidence.

Example:

One policy says access reviews are quarterly. Another procedure says access reviews are annual.

That should become a conflict item requiring reviewer decision.

### 2.8 Summary: Which Documents Create Which Items

| Source document type | Creates Zone 1 Extraction? | Creates Zone 2 Assignment & Ownership? | Creates Zone 3 Harmonisation? |
| --- | --- | --- | --- |
| Policy/procedure/SOP | Yes | Indirectly, if later compared to JDs or conflicts | Yes, via classifier role/duplicate comparison |
| Job description | No normal control acceptance path; mapped to Orphan | Yes, directly as `Orphan` | Indirectly, if role terms are later compared |
| Contract/SLA/agreement | Yes | Indirectly, if assigned role/accountability does not align | Yes, via classifier duplicate/role comparison |
| Regulatory/statutory | Yes, with obligation fields where present | Indirectly, if obligations imply unclear ownership | Yes, via classifier duplicate/role comparison |
| Audit/risk document | Yes, as finding-style extracted items | Indirectly, if findings expose ownership gaps | Yes, if controls overlap with existing controls |
| Evidence sample | No, skipped | No | No |
| Form/template | No, skipped | No | No |
| Reference document | No, skipped | No | No |
| Unclassified | No, skipped | No | No |

### 2.9 Operational Meaning

In simple terms:

Assignment & Ownership is born mainly from JDs.

Harmonisation is born from comparison.

JDs create responsibility gaps because they say what people do.

Policies, procedures, contracts, regulatory documents, and audit documents create controls and owner terms. The Classifier then compares those terms and controls against registers and other extracted items to find duplicates, variants, and inconsistencies.

## 3. Assignment & Ownership

Assignment & Ownership is Zone 2 of the review process. It handles queue items where the extracted responsibility/control does not line up cleanly between job descriptions, policies, procedures, and the Role Register.

The page lives at:

`frontend/src/pages/AssignmentOwnership/index.jsx`

The backend decision route is:

`PATCH /api/v1/queue/items/{item_id}/zone2-decide`

The backend implementation is in:

`review_queue/router.py`

### 3.1 Purpose

Assignment & Ownership answers this question:

Who is accountable for this responsibility, and where is that accountability formally governed?

A control is weak if the owner role is unclear. A job description is weak if it gives a person a responsibility that no policy or procedure governs. A policy is weak if it assigns a control to a role whose JD does not acknowledge that duty.

Zone 2 exists to catch those gaps before they become accepted operating records.

### 3.2 Item Types

The frontend currently loads AI Review Queue items where:

`ItemType = Orphan`

The UI recognises two main orphan directions.

#### JD to Document

Field:

`OrphanDirection = JD_to_Doc`

Meaning:

A job description contains a responsibility, but no governing policy/procedure/control document appears to define how that responsibility should operate.

Example:

A JD says the Information Security Lead must perform quarterly access reviews, but there is no access review policy or procedure explaining the requirement, evidence, frequency, or acceptance criteria.

Risk:

The person has a responsibility, but the organisation has no formal control framework around it.

#### Document to JD

Field:

`OrphanDirection = Doc_to_JD` or any non-`JD_to_Doc` value in the current UI.

Meaning:

A policy/procedure/control references a role, but that role's JD does not contain the responsibility.

Example:

A policy says the HR Manager must maintain training evidence, but the HR Manager JD does not mention training evidence ownership.

Risk:

The control exists, but the assigned role may not know it owns the obligation.

### 3.3 What The Screen Shows

Each card shows:

- Direction badge: `JD -> No policy` or `Policy -> Not in JD`.
- The responsibility or control statement.
- The orphan reason.
- Source document code and source clause.
- Review status if the item has already been decided.

When expanded, the card explains the gap in plain language.

For JD-to-document items, the screen explains that no control governs the activity, no evidence is collected, and the responsibility is not tracked in the compliance chain.

For document-to-JD items, the screen explains that the control exists, but the role's JD does not acknowledge the accountability.

### 3.4 Decision Options

The available decision buttons depend on the orphan direction.

#### JD to Document Decisions

`Create new document`

Use when the responsibility is valid, but there is no governing policy/procedure. This creates a Document Lifecycle item so a new document can be drafted, reviewed, sensitised, and approved.

`Add to existing policy`

Use when the responsibility is valid and should be added to an existing policy/procedure. The reviewer can enter a document code so the audit trail records which document needs revision.

`Intentional`

Use when the responsibility deliberately does not need a governing policy. This should be rare and must be justified clearly in the rationale.

`Remove from JD`

Use when the JD contains a responsibility that should not be there. The item is treated as rejected from the compliance chain and should trigger a JD correction process outside the current direct cascade.

`Mark False Positive`

Use when the AI incorrectly identified a gap.

`Request Second Review`

Use when another reviewer should assess the item before final decision.

#### Document to JD Decisions

The UI includes these intended decision types:

- `Add to existing JD`
- `Reassign control`
- `Create new role`
- `Remove from policy`
- `Mark False Positive`
- `Request Second Review`

Important current implementation note:

The backend Zone 2 route currently accepts only:

- `Create new document`
- `Add to existing policy`
- `Intentional`
- `Remove from JD`
- `Mark False Positive`
- `Request Second Review`

So the frontend contains the intended document-to-JD decisions, but the backend currently needs to be extended before those decisions can be processed successfully. Until then, those decisions may return validation errors unless the backend is updated.

### 3.5 Required Rationale

Every Zone 2 decision requires a rationale.

The frontend requires at least 10 characters before enabling decisions.

The backend requires a non-empty rationale of at least 5 characters.

The rationale is important because it becomes the audit explanation for why the item was accepted, rejected, marked false positive, or escalated.

### 3.6 Backend Cascade

When a reviewer submits a Zone 2 decision, the backend:

1. Validates the decision value.
2. Validates the rationale.
3. Fetches the AI Review Queue item from SharePoint.
4. Runs the Zone 2 cascade.
5. Updates the queue item with decision metadata.
6. Writes an audit log entry.
7. Returns the updated item and cascade summary.

Decision status mapping:

| Decision | ReviewStatus |
| --- | --- |
| Create new document | Accepted |
| Add to existing policy | Accepted |
| Intentional | Accepted |
| Remove from JD | Rejected |
| Mark False Positive | False Positive |
| Request Second Review | Pending Second Review |

### 3.7 Create New Document Cascade

When the decision is `Create new document`, the backend creates a Document Lifecycle entry.

The lifecycle item is created with:

- `Title`: `Gap Remediation: <statement>`
- `Stage`: `Review`
- `Trigger`: `Gap Remediation`
- `AIGenerated`: `False`
- `Revised`: `False`
- `OwnerEntraId`: current reviewer
- `Notes`: source document, responsibility/control statement, and reviewer rationale

This means the gap becomes a formal document remediation task.

The workflow then continues in Document Lifecycle:

Review -> Sensitisation -> Approval.

### 3.8 Add To Existing Policy Cascade

When the decision is `Add to existing policy`, the backend records the chosen document code in the cascade result if the reviewer supplied one.

Current behavior:

It does not yet directly update the target policy or create a lifecycle revision entry for that existing document. It records the action and audit trail.

Recommended behavior:

This should create or update a Document Lifecycle item for the named document with trigger `Gap Remediation`, preserving the linked queue item and rationale. That would make the revision trackable instead of relying on manual follow-up.

### 3.9 Intentional Decision

`Intentional` means the reviewer accepts that no further control or document action is needed.

This should only be used where the organisation deliberately chooses not to formalise the responsibility in a governing document.

Good rationale should explain:

- Why no policy/procedure is required.
- Who accepted that position.
- What risk, if any, remains.
- Whether this should be revisited later.

### 3.10 Remove From JD

`Remove from JD` means the responsibility should not be in the job description.

Current behavior:

The queue item is marked `Rejected`.

Recommended behavior:

This should create a Document Lifecycle item for JD revision, because removing a responsibility from a JD is a document change and should go through review and approval.

### 3.11 False Positive

`Mark False Positive` means the AI detected a gap that is not real.

The item becomes `False Positive`.

The rationale should explain what the AI missed, such as:

- The responsibility is already covered by another clause.
- The role is already mapped using a recognised variant.
- The control is not actually assigning responsibility.

### 3.12 Second Review

`Request Second Review` means the item should be reviewed by another compliance reviewer.

The item becomes `Pending Second Review`.

Recommended behavior:

Second review should eventually support assigning a named reviewer, tracking reviewer comments, and preventing the same person from approving their own escalation.

### 3.13 What Assignment & Ownership Should Guarantee

A completed Zone 2 workflow should guarantee:

- Every accepted responsibility has a governing document or a documented reason why no document is required.
- Every accepted control has an accountable role.
- Every accountable role should exist in the Role Register.
- Every role that owns a control should have the responsibility reflected in its JD.
- Every remediation decision should create a trackable lifecycle item when a document change is required.
- Every decision should have an audit trail.
- False positives should be recorded so the same issue can be tuned out later.

## 4. Harmonisation

Harmonisation is Zone 3 of the review process. It handles inconsistent naming, role variants, and near-duplicate controls.

The page lives at:

`frontend/src/pages/Harmonisation/index.jsx`

The backend decision route is:

`PATCH /api/v1/queue/items/{item_id}/zone3-decide`

The classifier that creates Harmonisation items is in:

`agents/classifier/service.py`

### 4.1 Purpose

Harmonisation answers this question:

Are these names or controls actually the same thing, and what should the canonical version be?

Without harmonisation, OrgOS can end up with:

- Multiple names for the same role.
- Duplicate controls from different documents.
- Controls assigned to role names that do not exist in the Role Register.
- Evidence requirements split across duplicate controls.
- Standards coverage appearing stronger or weaker than it really is.

Harmonisation keeps the compliance model clean.

### 4.2 How Harmonisation Items Are Created

The Harmonisation screen loads AI Review Queue items where:

`ItemType = Harmonisation`

Those items are created by the Classifier agent.

The frontend has a `Run classifier` button that calls:

`POST /api/v1/agents/classify`

The classifier performs two active jobs in the current implementation:

1. Role variant detection.
2. Near-duplicate control detection.

The code comments also describe conflict detection as a planned job, but the current classifier implementation writes role variant and duplicate control items.

### 4.3 Role Variant Detection

Role variant detection compares extracted `ProposedOwnerRole` values against the Role Register.

If an extracted role does not exactly match a Role Register title, the classifier checks whether it is similar to an existing role.

Example:

- Extracted term: `IT Security Officer`
- Role Register title: `Information Security Officer`

If similarity is close enough, the classifier creates a Harmonisation queue item asking the reviewer whether these are variants of the same role.

If the role term is completely unrecognised, it still creates a Harmonisation item so the reviewer can decide whether it should become a new role or map to an existing one.

The queue item stores:

- `Title`
- `ItemType = Harmonisation`
- `CanonicalName`
- `VariantTerms`
- `VariantFrequency`
- `ReviewStatus = Pending Review`
- `ConfidenceScore`
- `SourceDocumentCode`

### 4.4 Near-Duplicate Control Detection

Near-duplicate detection compares extracted controls against:

- Other extracted controls in the queue.
- Confirmed controls in the Control Register.

The classifier normalises text by removing common modal/determiner words and then compares similarity.

Current similarity threshold:

`0.80`

If two controls from different source documents are similar enough, the classifier creates a Harmonisation item.

Example:

Control A:

`The Information Security Lead shall review user access quarterly.`

Control B:

`User access must be reviewed every quarter by the IS Lead.`

These may be the same control and should not necessarily become two independent control records.

### 4.5 What The Harmonisation Screen Shows

Each Harmonisation card shows:

- Item type badge: `Role variant` or `Control duplicate`.
- Frequency/similarity information.
- The title or control statement.
- Variant terms as small tags.
- Source document code.
- Review status if already decided.

When expanded, the screen explains the pattern:

For role variants:

The terms may all refer to the same role. The reviewer should confirm the canonical name so future extractions can map variants correctly.

For control duplicates:

The controls may be near-duplicates from different documents. The reviewer should decide whether to merge them, partially merge them, standardise wording, or keep them separate.

### 4.6 Harmonisation Decisions

The backend accepts four decisions.

`Merge`

Use when all terms or controls represent the same underlying thing.

For role variants, this means the canonical role should be confirmed and all variant terms should map to it.

For duplicate controls, this means the controls should be consolidated into one master control.

`Partial merge`

Use when some variants are the same, but not all.

Example:

`InfoSec Lead` and `Information Security Lead` are the same, but `IT Manager` is not.

`Keep separate`

Use when the items are genuinely different.

This prevents an over-aggressive classifier from merging roles or controls that should remain distinct.

`Rename and standardise`

Use when the term should be renamed consistently, even if the underlying records are not merged.

Example:

Standardise all references from `Departmental Head` to `Department Head`.

### 4.7 Canonical Name

The Harmonisation form includes a canonical name input.

The canonical name is the preferred name going forward.

For roles, this should match the Role Register title.

For controls, this should be the master wording or the agreed label for the consolidated control.

The frontend describes it as:

`the one true name going forward`

This is useful language for reviewers, but operationally it means:

- The canonical term should be stored.
- Variant terms should be retained.
- Future extraction should resolve known variants to the canonical value.

### 4.8 Required Rationale

Every Harmonisation decision requires a rationale.

The frontend requires at least 10 characters before enabling decisions.

The backend requires a non-empty rationale of at least 5 characters.

Good rationale should explain:

- Why the items are the same or different.
- Why the chosen canonical name is correct.
- Whether any remaining variants require follow-up.
- Whether documents or registers need revision.

### 4.9 Backend Cascade

When a reviewer submits a Zone 3 decision, the backend:

1. Validates the decision.
2. Validates the rationale.
3. Fetches the queue item.
4. Builds a cascade summary.
5. Writes an audit log entry.
6. Updates the queue item with review status, decision, rationale, reviewer, cascade result, and canonical name if supplied.
7. Returns the updated item.

Decision status mapping:

| Decision | ReviewStatus |
| --- | --- |
| Merge | Accepted |
| Partial merge | Accepted |
| Keep separate | Accepted |
| Rename and standardise | Accepted |

### 4.10 Current Cascade Behavior

Current backend behavior is conservative.

For `Merge` and `Rename and standardise` with a canonical name, the backend records:

- Canonical name confirmed.
- Role Register update required.

For `Partial merge`, it records:

- Partial merge confirmed.
- Remaining variants require manual review.

For `Keep separate`, it records:

- No merge required.

The backend also writes an audit log entry.

Important current implementation note:

The backend does not yet automatically update the Role Register, Control Register, or source documents. It records the decision and audit trail, and it updates the queue item.

### 4.11 What Harmonisation Should Eventually Enforce

A completed Harmonisation workflow should eventually enforce:

- Canonical role names are written to the Role Register.
- Variant terms are stored in the Role Register `VariantTerms` field.
- Future extractions use variant mappings before creating orphan items.
- Confirmed duplicate controls are linked or merged so evidence is not fragmented.
- Control Register owners are updated to canonical role names.
- Source documents requiring wording changes create Document Lifecycle revision items.
- Keep-separate decisions suppress repeated false duplicate findings.
- Every merge/rename decision is auditable.

## 5. Relationship Between Assignment & Ownership And Harmonisation

These two workflows are related but not the same.

Assignment & Ownership asks:

Does this responsibility/control have the right owner and governing document?

Harmonisation asks:

Are these names or controls actually the same thing?

They often interact.

Example:

An extraction finds owner role `InfoSec Lead`, but the Role Register has `Information Security Lead`.

Without harmonisation, this can look like an ownership problem because the role does not exactly match.

With harmonisation, `InfoSec Lead` can be mapped as a variant of `Information Security Lead`, preventing a false orphan.

Another example:

Two documents contain similar access review controls.

Without harmonisation, both may become separate controls with separate evidence requirements.

With harmonisation, they can be merged or standardised so there is one coherent control, one owner, and one evidence requirement.

## 6. Data Model Summary

Both workflows use the AI Review Queue as their working list.

Important common fields:

| Field | Meaning |
| --- | --- |
| `id` | SharePoint queue item ID |
| `Title` | Human-readable item title |
| `ItemType` | `Orphan` or `Harmonisation` |
| `SourceDocumentCode` | Source document where the issue was found |
| `SourceClause` | Source clause or section if available |
| `ReviewStatus` | Current review state |
| `Decision` | Reviewer decision |
| `DecisionRationale` | Reviewer rationale |
| `ReviewedByEntraId` | Reviewer identity |
| `CascadeResult` | Summary of downstream action |
| `ConfidenceScore` | AI/classifier confidence or similarity score |

Assignment & Ownership fields:

| Field | Meaning |
| --- | --- |
| `ResponsibilityStatement` | JD responsibility or extracted responsibility |
| `ControlStatement` | Control statement when source is policy/control |
| `OrphanDirection` | Direction of mismatch |
| `OrphanClassification` | Classifier label for orphan type |
| `OrphanReason` | Explanation of the gap |
| `linked_doc_code` | Request body value for existing document update |

Harmonisation fields:

| Field | Meaning |
| --- | --- |
| `CanonicalName` | Proposed or confirmed canonical term |
| `VariantTerms` | Terms that may refer to the same role/control |
| `VariantFrequency` | Frequency or similarity summary |
| `ControlStatement` | Used for duplicate control items |

## 7. Roles And Permissions

The frontend checks Microsoft Entra roles from the current account.

Users can make decisions if they have:

- `Compliance.Lead`
- `OrgOS.Admin`

Users without those roles can view items but cannot decide them.

This is important because Zone 2 and Zone 3 decisions affect the structure of the compliance system. They should not be ordinary data edits.

## 8. Statuses

Common statuses include:

`Pending Review`

The item needs a reviewer decision.

`Accepted`

The reviewer accepted the item and selected a resolution path.

`Rejected`

The reviewer rejected the proposed issue or chose a rejection-type decision.

`False Positive`

The AI/classifier was wrong.

`Pending Second Review`

The item needs another reviewer.

The current frontend filters mainly between pending and all items on both pages.

## 9. Audit Expectations

Every decision should answer:

- Who reviewed it?
- What did they decide?
- Why did they decide it?
- When was it decided?
- What downstream action was created?

The backend writes Audit Log entries for Zone 2 and Zone 3 decisions.

This matters because assignment and harmonisation decisions can change accountability. They are governance decisions, not cosmetic edits.

## 10. Current Gaps To Close

These are the main implementation gaps visible from the current code.

### 10.1 Zone 2 Frontend And Backend Decision Mismatch

The Assignment & Ownership frontend includes intended document-to-JD decisions such as:

- `Add to existing JD`
- `Reassign control`
- `Create new role`
- `Remove from policy`

The backend currently does not accept those values.

Recommended fix:

Extend `ZONE2_DECISIONS`, status mapping, and cascade behavior to support those decisions.

### 10.2 Add To Existing Policy Should Create Lifecycle Work

Current behavior records the target document code only in cascade text.

Recommended fix:

Create a Document Lifecycle revision item for the existing document.

### 10.3 Remove From JD Should Create JD Revision Work

Current behavior marks the item rejected.

Recommended fix:

Create a Document Lifecycle item for JD amendment.

### 10.4 Harmonisation Should Update Registers

Current behavior records that Role Register updates are required, but does not perform them.

Recommended fix:

When a role merge/rename is accepted:

- Update or create the canonical role in Role Register.
- Append variant terms.
- Update related Control Register owner role values.
- Prevent future classifier runs from reopening the same variant.

### 10.5 Duplicate Controls Need A Register Strategy

Current Harmonisation decisions do not merge Control Register records.

Recommended fix:

Define whether merged controls should:

- Keep one master control and retire duplicates.
- Link duplicates to a master control.
- Preserve source-specific clauses while sharing one evidence requirement.

### 10.6 Classifier Conflict Detection Is Described But Not Fully Active

The classifier header describes conflict detection, but the current implementation writes role variants and near-duplicate controls only.

Recommended fix:

Add a conflict detection job that creates Zone 2 conflict items, then add UI/backend decision support for conflict resolution.

## 11. Ideal End-To-End Flow

The ideal flow is:

1. Documents and JDs are extracted.
2. Extracted controls enter Zone 1 for human review.
3. The Classifier compares extracted roles and controls against existing registers.
4. Assignment & Ownership receives orphan/accountability gaps.
5. Harmonisation receives role variants and duplicate controls.
6. Compliance reviewers decide each item with rationale.
7. Accepted decisions create concrete downstream work:
   - new document lifecycle task,
   - existing document revision,
   - JD update,
   - Role Register update,
   - Control Register merge/update,
   - audit log record.
8. The registers become cleaner after every review cycle.
9. Future extraction produces fewer false gaps because the system learns canonical names and accepted mappings.

## 12. Practical Reviewer Guidance

When reviewing Assignment & Ownership:

- Do not accept an orphan just because the wording sounds reasonable.
- Ask whether there is a real governing document.
- Ask whether the named owner role exists.
- Ask whether the JD truly includes the accountability.
- Prefer creating lifecycle work when a document must change.
- Use false positive only when the system is objectively wrong.

When reviewing Harmonisation:

- Do not merge roles just because names are similar.
- Confirm whether the same person/role would actually own the same accountability.
- Check whether duplicate controls have the same scope, frequency, evidence, and standard mapping.
- Use keep separate when two controls look similar but operate differently.
- Use canonical names that match the Role Register.
- Keep variant terms for traceability.

## 13. Summary

Assignment & Ownership makes sure responsibility is formally governed and owned.

Harmonisation makes sure names and controls are consistent enough for OrgOS to reason about them.

Both workflows are essential to a reliable GRC system. Without Assignment & Ownership, controls can exist without true accountability. Without Harmonisation, the system can create duplicate roles, duplicate controls, and misleading gaps.

The current implementation already provides the review screens, decision routes, audit logging, classifier-generated Harmonisation items, and Document Lifecycle cascade for new document creation. The next improvement layer is to make every accepted decision update the affected register or create the correct lifecycle task automatically.
