# OrgOS Role-Based Access Control (RBAC) — Full Implementation Plan
**Dragnet Solutions Limited | DRG-AUTO-BRIEF-GRC-01-26**
**Document version:** 1.0 | **Status:** Planning

---

## Table of Contents

1. [Overview & Principles](#1-overview--principles)
2. [The Three Roles](#2-the-three-roles)
3. [Role Assignment Architecture](#3-role-assignment-architecture)
4. [Frontend Role Resolution Pattern](#4-frontend-role-resolution-pattern)
5. [Backend Enforcement Layers](#5-backend-enforcement-layers)
6. [Navigation & Sidebar by Role](#6-navigation--sidebar-by-role)
7. [Screen-by-Screen Breakdown](#7-screen-by-screen-breakdown)
   - 7.1 [Login Screen](#71-login-screen)
   - 7.2 [Work Hub (Dashboard)](#72-work-hub-dashboard)
   - 7.3 [Document Register](#73-document-register)
   - 7.4 [Role Register](#74-role-register)
   - 7.5 [Compliance Calendar](#75-compliance-calendar)
   - 7.6 [Contract Register](#76-contract-register)
   - 7.7 [Document Lifecycle](#77-document-lifecycle)
   - 7.8 [Extraction Review](#78-extraction-review)
   - 7.9 [Assignment & Ownership](#79-assignment--ownership)
   - 7.10 [Harmonisation](#710-harmonisation)
   - 7.11 [Control Register](#711-control-register)
   - 7.12 [Evidence Tracker](#712-evidence-tracker)
   - 7.13 [Strategic Risks](#713-strategic-risks)
   - 7.14 [Standards Map](#714-standards-map)
   - 7.15 [Gap Analysis](#715-gap-analysis)
   - 7.16 [AI Review Queue](#716-ai-review-queue)
8. [Permission Matrix Summary](#8-permission-matrix-summary)
9. [Implementation Steps — Frontend](#9-implementation-steps--frontend)
10. [Implementation Steps — Backend](#10-implementation-steps--backend)
11. [Role Denial UX Patterns](#11-role-denial-ux-patterns)
12. [Testing Checklist](#12-testing-checklist)

---

## 1. Overview & Principles

OrgOS serves three distinct audiences with fundamentally different relationships to the GRC system:

- **Standard employees** are primarily *data providers* — they own evidence, read the standards landscape, and submit artefacts.
- **Compliance Officers** are *orchestrators* — they review AI outputs, make decisions, trigger agents, and manage the compliance lifecycle.
- **OrgOS Admins / Compliance Admins** are *system stewards* — they control the registers, manage user access, trigger high-impact system operations, and hold final authority over all data in the platform.

### Guiding Principles

1. **Defence in depth.** Every permission is enforced in *two places*: the backend (via FastAPI `Depends()`) and the frontend (via hidden/disabled UI). The backend is the source of truth; the frontend is convenience.

2. **Show, don't hide — with exceptions.** Most screens are visible to all roles in read-only form. We avoid invisible navigation items unless the feature has zero value to the lesser role. Hiding things feels patronising and prevents users from understanding what the system does. The exceptions (screens entirely hidden from Standard Users) are documented explicitly below.

3. **No silent failure.** If a user without the right role tries to perform a restricted action, they receive a clear, contextual explanation: *"This action requires the Compliance Lead role. Contact your OrgOS Admin to request access."*

4. **Principle of least privilege on agents.** AI agent triggers (Extraction, Gap Analyzer, Policy Drafter, CDI Checker, Harmonisation Classifier) are exclusively Compliance-and-above actions. They consume significant system resources and produce records that feed into audit evidence. Standard Users never see trigger buttons.

5. **Owner-level elevation for Standard Users.** A Standard User *does* have one elevated permission on any record they personally own: they can submit evidence for controls linked to their role, and they can complete compliance obligations assigned to them. This is the core task the system was designed to facilitate.

---

## 2. The Three Roles

### Role 1 — Standard User
**Entra ID app role:** None (or `OrgOS.User` if you choose to add an explicit role, but the absence of the other two roles is sufficient)

**Who holds this role:** Every Dragnet employee who interacts with the GRC system. This includes department heads, HR staff, ISMS leads of individual departments, finance staff, and anyone who generates or submits compliance evidence as part of their job.

**Core responsibility in OrgOS:**
- Submit evidence for controls linked to their role
- View the compliance posture of the organisation
- Complete compliance obligations they personally own
- Upload documents for review in the lifecycle workflow

**What they can never do:**
- Trigger AI agents
- Accept or reject items in the AI Review Queue
- Make harmonisation or orphan resolution decisions
- Escalate obligations to Gap Analysis
- Terminate contracts
- Create strategic risks
- Change the lifecycle status of a contract
- Run gap analysis
- Approve documents in the lifecycle

---

### Role 2 — Compliance Officer
**Entra ID app role:** `Compliance.Lead`

**Who holds this role:** The Compliance team at Dragnet. This includes the Head of Compliance, Compliance Analysts, and the ISMS Manager. Typically 3–6 people.

**Core responsibility in OrgOS:**
- Everything a Standard User can do
- Make all AI Review Queue decisions (Accept, Edit, Reject, Route)
- Trigger extraction, gap analysis, harmonisation, CDI check, policy drafting
- Complete and escalate compliance obligations
- Manage all four Tier 1 registers (Document, Role, Compliance Calendar, Contract)
- Verify evidence submitted by Standard Users
- Approve documents in the lifecycle workflow
- Update gap analysis status
- Escalate gaps to Strategic Risk

**What they cannot do (Admin only):**
- Hard-delete any SharePoint record (no one can — we soft-delete)
- Assign Entra ID application roles to users
- Access the OrgOS Admin panel (if created in future)
- Terminate contracts (this is an Admin-only lifecycle transition — see section 7.6)
- Create strategic risks directly (only via gap escalation or Admin)

---

### Role 3 — OrgOS Admin / Compliance Admin
**Entra ID app role:** `OrgOS.Admin`

**Who holds this role:** The OrgOS System Administrator, the Head of Compliance (double-hatted), and any executive-level user who needs full system authority. Typically 1–2 people.

**Core responsibility in OrgOS:**
- Everything a Compliance Officer can do
- Full CRUD authority across all registers
- High-impact lifecycle actions (terminate contracts, supersede documents, reset lifecycle stages)
- Assign role holders in the Role Register
- Create and edit entries in the Strategic Risk Register (ExCo-equivalent authority)
- Trigger all AI agents without additional confirmation steps
- View all system items regardless of ownership or department
- Override calculated statuses (e.g., manually mark a contract as Active after it expired)
- Access admin-only UI sections (Admin panel, user role viewer)

---

## 3. Role Assignment Architecture

### How Roles Are Stored and Assigned

Roles are defined as **Entra ID application roles** in the Azure App Registration for OrgOS. This is already the existing pattern — the backend validates JWTs and reads the `roles` claim. The frontend reads the same claim from the MSAL account object.

**In the Azure App Registration:**
```
App roles:
  - OrgOS.Admin      → displayName: "OrgOS Administrator"
                       description: "Full system authority, agent triggers, ExCo risk register"
                       allowedMemberTypes: Users/Groups

  - Compliance.Lead  → displayName: "Compliance Officer"
                       description: "AI queue decisions, evidence verification, agent triggers"
                       allowedMemberTypes: Users/Groups
```

**Assigning roles to users (done in Azure Portal):**
- Azure Portal → Enterprise Applications → OrgOS → Users and groups → Assign
- An Admin assigns `Compliance.Lead` to each Compliance team member
- An Admin assigns `OrgOS.Admin` to the OrgOS System Admin and Head of Compliance
- All other employees receive no role assignment — they are Standard Users by default

**Propagation:**
- When a user signs in, MSAL acquires an access token with `roles: ["Compliance.Lead"]` or `roles: ["OrgOS.Admin"]` in the claims
- The backend JWT validator reads this from the `roles` claim
- The frontend reads this from `accounts[0].idTokenClaims.roles`

### Role Hierarchy

```
Standard User
     ↓  (is a subset of)
Compliance Officer   [Compliance.Lead]
     ↓  (is a subset of)
OrgOS Admin         [OrgOS.Admin]
```

An `OrgOS.Admin` implicitly has all `Compliance.Lead` permissions. This is already implemented in the backend: `require_compliance_lead` checks for either role.

### The `useCurrentUserRole` Hook (to be created)

The single source of truth for role detection in the frontend. All role-gated UI reads from this hook.

```javascript
// hooks/useCurrentUserRole.js

import { useMsal } from "@azure/msal-react";

export function useCurrentUserRole() {
  const { accounts } = useMsal();
  const claims = accounts[0]?.idTokenClaims || {};
  const roles  = Array.isArray(claims.roles) ? claims.roles : [];

  const isAdmin      = roles.includes("OrgOS.Admin");
  const isCompliance = roles.includes("Compliance.Lead") || isAdmin;
  const isStandard   = !isAdmin && !isCompliance;

  // The user's Entra OID — used to check ownership
  const oid  = accounts[0]?.localAccountId || accounts[0]?.homeAccountId || "";
  const name = accounts[0]?.name || "";
  const email = accounts[0]?.username || "";

  return {
    oid,
    name,
    email,
    roles,
    isAdmin,
    isCompliance,   // true for Compliance.Lead AND OrgOS.Admin
    isStandard,     // true when no special role assigned
    roleLabel: isAdmin ? "Admin" : isCompliance ? "Compliance" : "Standard User",
  };
}
```

### Ownership Check Pattern

For actions where Standard Users have elevated permission on their own records (e.g., completing their own obligation, submitting their own evidence):

```javascript
const { oid, isCompliance } = useCurrentUserRole();
const canComplete = isCompliance || (obligation.owner?.oid === oid);
```

This pattern is used throughout the section below wherever "owners can act on their own records" applies.

---

## 4. Frontend Role Resolution Pattern

### How Role-Gated Components Are Written

Every screen uses a consistent pattern. Role checks are done at the component level — the page reads `useCurrentUserRole()` once at the top, and all conditional renders derive from that.

```javascript
// Example pattern — every page that has role-gated UI
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";

export default function ExamplePage() {
  const { isAdmin, isCompliance, isStandard, oid } = useCurrentUserRole();

  return (
    <>
      {/* Read-only content — always visible */}
      <ItemList items={items} />

      {/* Compliance-and-above action */}
      {isCompliance && (
        <button onClick={handleEscalate}>Escalate to Gap Analysis</button>
      )}

      {/* Admin-only action */}
      {isAdmin && (
        <button onClick={handleTerminate}>Terminate contract</button>
      )}

      {/* Standard user sees this callout instead of action buttons */}
      {isStandard && (
        <div className="read-only-notice">
          You have read-only access to this register.
          Contact the Compliance team to request changes.
        </div>
      )}
    </>
  );
}
```

### Disabled vs Hidden Buttons

- **Hidden:** When the action is categorically unavailable (e.g., Standard Users never see "Accept control" in the queue). Showing a disabled button would just create confusion.
- **Disabled with tooltip:** When the user has partial access (e.g., a Compliance Officer can see the "Terminate" button but it is disabled because Terminate requires Admin). The disabled state explains why: *"Requires OrgOS Admin role"*.

### Read-Only Notice Banner

Every page that shows a Standard User a read-only view displays a consistent banner at the top:

```
┌─────────────────────────────────────────────────────────────┐
│  📋  You have read-only access to this register.            │
│  To request changes, contact the Compliance team.           │
└─────────────────────────────────────────────────────────────┘
```

This banner is a shared component: `<ReadOnlyBanner />`.

---

## 5. Backend Enforcement Layers

### Existing Enforcement (Already Built)

| Endpoint pattern | Enforcer |
|---|---|
| All endpoints | `Depends(get_current_user)` — requires valid Entra ID JWT |
| Agent trigger endpoints | `Depends(require_compliance_lead)` — requires `Compliance.Lead` or `OrgOS.Admin` |
| Role assign endpoint | Currently unchecked — needs Admin guard added |

### New Backend Guards to Add

The following additional guards need to be implemented as part of this RBAC rollout:

| Action | Required role | Implementation |
|---|---|---|
| `POST /grc/documents` (create) | Compliance.Lead | Add `Depends(require_compliance_lead)` |
| `PATCH /grc/documents/{id}` (update) | Compliance.Lead | Add `Depends(require_compliance_lead)` |
| `DELETE /grc/documents/{id}` (soft delete) | Compliance.Lead | Add `Depends(require_compliance_lead)` |
| `POST /grc/roles` (create) | OrgOS.Admin | Add `Depends(require_admin)` |
| `PATCH /grc/roles/{id}` (update) | OrgOS.Admin | Add `Depends(require_admin)` |
| `PATCH /grc/roles/{id}/assign` | OrgOS.Admin | Add `Depends(require_admin)` |
| `POST /grc/compliance` (create obligation) | Compliance.Lead | Add `Depends(require_compliance_lead)` |
| `PATCH /grc/compliance/{id}` | Compliance.Lead | Add `Depends(require_compliance_lead)` |
| `PATCH /grc/compliance/{id}/complete` | Owner OR Compliance.Lead | Ownership check in service layer |
| `POST /grc/compliance/{id}/escalate` | Compliance.Lead | Already guarded in router |
| `DELETE /grc/compliance/{id}` | Compliance.Lead | Already guarded in router |
| `POST /grc/contracts` (create) | Compliance.Lead | Add `Depends(require_compliance_lead)` |
| `PATCH /grc/contracts/{id}` | Compliance.Lead | Add `Depends(require_compliance_lead)` |
| `PATCH /grc/contracts/{id}/lifecycle` | OrgOS.Admin | Change guard to `require_admin` for Terminate/Supersede; Compliance.Lead for Under Review |
| `DELETE /grc/contracts/{id}` | Compliance.Lead | Already guarded |
| `PATCH /evidence/{id}/submit` | Owner OR Compliance.Lead | Ownership check in service layer |
| `PATCH /evidence/{id}/verify` | Compliance.Lead | Already guarded |
| `POST /risks` | OrgOS.Admin | Add `Depends(require_admin)` |
| `PATCH /risks/{id}` | OrgOS.Admin | Add `Depends(require_admin)` |
| `PATCH /gap-analysis/{id}/status` | Compliance.Lead | Add `Depends(require_compliance_lead)` |
| `POST /gap-analysis/{id}/accept-risk` | Compliance.Lead | Add `Depends(require_compliance_lead)` |

### New Backend Dependency to Create

```python
# auth/validator.py — add below require_compliance_lead

async def require_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Enforces OrgOS.Admin role. Used on high-impact endpoints."""
    if "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the OrgOS Admin role.",
        )
    return user
```

### Ownership Check in Service Layer

For endpoints where Standard Users can act on their own records:

```python
# In service functions that need ownership checks:

async def complete_obligation(item_id, user_oid, user_name, body, roles):
    item = await get_list_item(...)
    owner_oid = item.get("fields", {}).get("OwnerEntraId", "")
    
    is_compliance = "Compliance.Lead" in roles or "OrgOS.Admin" in roles
    is_owner = owner_oid == user_oid
    
    if not is_compliance and not is_owner:
        raise HTTPException(
            status_code=403,
            detail="You can only complete obligations assigned to you."
        )
    # ... rest of completion logic
```

---

## 6. Navigation & Sidebar by Role

The sidebar is the primary navigation. Role-gating here controls what users know the system can do.

### Sidebar Visibility by Role

| Nav item | Standard User | Compliance | Admin |
|---|---|---|---|
| Work Hub | ✅ Visible | ✅ Visible | ✅ Visible |
| Document Register | ✅ Read-only | ✅ Full access | ✅ Full access |
| Role Register | ✅ Read-only | ✅ Read-only | ✅ Full access |
| Compliance Calendar | ✅ Own items highlighted | ✅ Full access | ✅ Full access |
| Contract Register | ✅ Read-only | ✅ Full access | ✅ Full access |
| Document Lifecycle | ✅ Read-only | ✅ Full access | ✅ Full access |
| Extraction Review | ❌ Hidden | ✅ Full access | ✅ Full access |
| Assignment & Ownership | ❌ Hidden | ✅ Full access | ✅ Full access |
| Harmonisation | ❌ Hidden | ✅ Full access | ✅ Full access |
| Control Register | ✅ Read-only | ✅ Full access | ✅ Full access |
| Evidence Tracker | ✅ Own evidence only | ✅ Full access | ✅ Full access |
| Strategic Risks | ✅ Read-only | ✅ Read-only | ✅ Full access |
| Standards Map | ✅ Full view | ✅ Full view + trigger | ✅ Full access |
| Gap Analysis | ✅ Read-only | ✅ Full access | ✅ Full access |

**Why Extraction Review, Assignment & Ownership, and Harmonisation are hidden from Standard Users:** These three pages are entirely Compliance-internal workflow screens. They show AI model outputs, orphaned JD mappings, and control deduplication logic that have no actionable meaning to a Standard User and would cause confusion. Showing them creates risk of accidental misclicks on consequential decisions.

### Sidebar UI for Standard Users

Standard Users see a role badge under their name in the TopBar: **"Standard User"** displayed in a grey chip. The three hidden nav items simply do not render. No placeholder, no lock icon — the items do not exist in their sidebar. This is cleaner than showing disabled items.

### Sidebar UI for Compliance

Compliance Officers see a **"Compliance"** blue chip under their name. All nav items are visible. The AI Workflow tier (Extraction, Assignment, Harmonisation) is prominently styled to draw attention to pending queue items.

### Sidebar UI for Admins

Admins see an **"Admin"** purple chip with a subtle shield icon. All nav items visible. A future Admin Settings entry can be added to the bottom of the sidebar. Admin-only actions appear throughout the app distinguished by a small shield icon.

---

## 7. Screen-by-Screen Breakdown

---

### 7.1 Login Screen

**All roles see the same login screen.**

The Microsoft 365 login button opens the MSAL popup. After login, the user's role is determined from the JWT claims. No role selection happens here — it is automatic.

**What changes after login:**
- The TopBar immediately shows the user's name, email, and role chip
- Navigation items render based on the detected role
- Work Hub content personalises based on role

**Error state:** If a user who has been removed from Entra ID tries to sign in, MSAL shows a standard Microsoft error. OrgOS adds no custom logic here.

---

### 7.2 Work Hub (Dashboard)

The Work Hub is the first screen after login. It shows urgency streams — items that need attention right now.

---

#### Standard User — Work Hub

The Standard User's Work Hub is **personalised to them**. It shows only items where they are the owner or assignee. It is not an organisational dashboard — it is their personal action queue.

**What they see:**

**Section 1 — My overdue evidence**
- A list of evidence items where:
  - `owner_role` matches a role assigned to this user in the Role Register
  - `status = Overdue` (due_date has passed and still Pending/Submitted)
- Each card shows: Control statement (truncated), due date (in red), evidence type, Submit button
- Clicking "Submit" takes them directly to the Evidence Tracker with that item pre-selected
- If no overdue evidence: "You have no overdue evidence items. You're on track."

**Section 2 — My upcoming evidence (due within 7 days)**
- Same filter but `status = Pending` and `due_date <= today + 7`
- Amber-coloured cards
- If none: hidden entirely (no empty state shown)

**Section 3 — My obligations**
- Compliance Calendar obligations where `owner.oid = currentUser.oid`
- Filtered to Overdue and Due Soon
- Each card shows: obligation name, due date, recurrence, Complete button
- Complete button opens the completion modal directly from Work Hub
- If none: hidden

**Section 4 — Documents awaiting my review (if any lifecycle items assigned to them)**
- If the user is listed as a reviewer on a Document Lifecycle item
- Shows document name, stage, due date
- Click → takes to Document Lifecycle for that document

**What they do NOT see:**
- Total pending AI Review Queue count (this is internal Compliance data)
- Total unassigned roles across the organisation
- System health cards
- Pending gap analysis count
- Any items not related to them

**Banner:** A green "Your compliance posture" banner at the bottom shows the Standards Map traffic lights as a summary (read-only, no action).

---

#### Compliance Officer — Work Hub

The Compliance Work Hub is an **organisational action dashboard**. Everything that needs a Compliance decision appears here.

**What they see:**

**Section 1 — AI Review Queue (pending decisions)**
- Count badge: "X items pending decision" split by zone (Extraction / Orphan / Harmonisation)
- A preview of the 3 oldest pending items
- "Go to Review Queue" button
- If all empty: "All queue items resolved." green state

**Section 2 — Overdue obligations (all, not just their own)**
- Count of all overdue obligations across the organisation
- Top 5 shown as cards sorted by obligation type (Statutory first)
- Each card has: Escalate to Gap Analysis button, Complete button
- "View all overdue" link → Compliance Calendar with Overdue tab active

**Section 3 — Overdue evidence (all)**
- Count of all Overdue evidence items in the Evidence Tracker
- Top 5 shown: which control they relate to, who the owner is, how many days overdue
- Click → Evidence Tracker with that item

**Section 4 — Lifecycle documents in review**
- All Document Lifecycle items currently in the Review or Sensitisation stage
- Days since entered current stage
- Progress stage button

**Section 5 — Unassigned roles**
- Count of roles with no current_holder
- Top 5 listed with department and JD reference
- "Go to Role Register" link

**Section 6 — Open gaps by severity**
- Count of Critical and Major open gap analysis items
- Mini traffic light summary: Red = Critical, Amber = Major
- "Go to Gap Analysis" link

---

#### Admin — Work Hub

The Admin Work Hub contains everything the Compliance Work Hub has, plus:

**Additional section — System health**
- Graph API connectivity status (green dot = connected, red = graph issue)
- Ollama health (green dot = model available, amber = model unavailable)
- Count of SharePoint list IDs that are still set to "placeholder" (i.e., not yet provisioned)

**Additional section — All strategic risks by score**
- Top 5 risks sorted by risk_score descending
- Risk score heat map (1–3 green, 4–6 amber, 7–9 red, 10–12 dark red)
- Click → Strategic Risk Register

**Additional data exposed:** The Admin can see the total count of all items in every register directly on the Work Hub, not just the urgent ones.

---

### 7.3 Document Register

The Document Register holds all policy, procedure, SOP, form, and guidelines documents.

---

#### Standard User — Document Register

**What they see:**
- Full list of all documents in the register (no filtering by department or status)
- Status badges (Active, Under Review, Superseded, Withdrawn)
- Search bar (search by name, code, owner)
- Filter by department, type, status (read-only filters)
- Click any document → detail view showing all fields

**What they see in detail view:**
- Document code, title, type, department, owner name, current version, effective date, next review date, applicable standards, status
- Linked controls count (how many controls reference this document)
- A read-only notice banner: "You have read-only access. Contact Compliance to request changes."

**What they do NOT see:**
- "+ Create document" button
- Edit button in detail view
- Withdraw (delete) button
- Status change dropdown

**The standard user's relationship to the Document Register is reference.** They look up which documents govern their responsibilities, not manage them.

---

#### Compliance Officer — Document Register

**What they see:**
- Everything the Standard User sees
- **"+ Add document" button** in the top right
- **Edit button** in the detail view (opens edit form)
- **Withdraw button** in the detail view (soft delete, with confirmation)
- No read-only notice banner

**Create document form:**
- Document code (with format validation: DRG-[DEPT]-[TYPE]-[REF]-[YY])
- Title
- Type (Policy / Procedure / SOP / Form / Guidelines)
- Department
- Current version
- Effective date
- Next review date
- Applicable standards (checkboxes)
- Owner (PersonPicker — resolved via Entra ID email lookup)

**Edit document form:**
- All the same fields, pre-populated
- Status field is visible and editable (Active / Under Review / Superseded)
- Cannot set Withdrawn from the edit form — must use the Withdraw button

---

#### Admin — Document Register

**What they see:**
- Everything the Compliance Officer sees
- **"Bulk import"** option (future feature — import from CSV)
- In the detail view, they see the raw SharePoint item ID for debugging
- **Status override** — can set any status including re-activating a Superseded document

---

### 7.4 Role Register

The Role Register maps organisational roles (from Entra ID, SeamlessHR, BitWiseFlow) to control ownership.

---

#### Standard User — Role Register

**What they see:**
- Full role list (all departments, all statuses)
- Their own role is highlighted with a subtle "You" chip
- Columns: Role title, department, JD reference, current holder name, assignment status
- Search by role title or department
- Click any role → detail view showing all fields including source system and variant terms

**What they do NOT see:**
- Assign button (assigning roles is Admin-only)
- Create role button
- Edit role button
- Delete button

**Purpose for Standard User:** They look up who is responsible for what, and confirm what role they are assigned to in the system.

---

#### Compliance Officer — Role Register

**What they see:**
- Everything the Standard User sees
- No extra write permissions on the Role Register
- Compliance Officers can READ but not write the Role Register — roles come from authoritative systems (Entra ID, HR)
- They see the "Source system" field prominently

**Why Compliance Officers cannot write the Role Register:** Role assignments are authoritative data from Entra ID and SeamlessHR. Allowing Compliance to manually edit roles would create drift from the authoritative source. The only legitimate write is role assignment after a handover, which is an Admin function.

**What they DO see that Standard Users don't:**
- Unassigned roles count in a banner: "4 roles are unassigned. Go to Work Hub → Unassigned roles."
- The sync status badge showing when data was last pulled from source systems

---

#### Admin — Role Register

**What they see:**
- Everything the Compliance Officer sees
- **"+ Add role"** button (manual role creation for roles not sourced from integrated systems)
- **Edit button** in detail view
- **Assign holder** button — opens PersonPicker to assign a current_holder
- **Unassign** button — removes the current holder (sets assignment_status = Unassigned)
- **"Sync from source"** button — triggers `scripts/sync_roles.py` equivalent via API

**Why Admin is required for assignment:** Assigning a role in OrgOS connects a person to control ownership and evidence responsibilities. This is a consequential action — the assigned person will start receiving evidence submission tasks. The Admin should confirm this is intentional.

---

### 7.5 Compliance Calendar

The Compliance Calendar tracks all statutory, licensing, certification, and regulatory obligations.

---

#### Standard User — Compliance Calendar

**What they see:**
- All obligations in the register (full list)
- Status-coloured cards (Overdue = red, Due Soon = amber, Upcoming = green, Completed = grey)
- Filter tabs: All / Overdue / Due Soon / Upcoming / Completed
- Filter by type (Statutory, Licensing, Certification, Regulatory)
- Search bar

**Their own obligations highlighted:** Any obligation where `owner.oid === currentUser.oid` has a subtle "Your obligation" indicator — a lighter background tint and a star/flag icon on the card.

**On their own obligations they can:**
- See the Complete button (appears only on obligations they own)
- Complete the obligation (the completion modal explains recurrence rollover)

**On obligations they do NOT own:**
- The Complete button is absent
- The Escalate button is absent
- Clicking the card shows the detail view in read-only mode

**What they do NOT see:**
- "+ Add obligation" button
- Edit button on any obligation
- Escalate to Gap Analysis button (on any obligation, including their own)
- Withdraw button

**Why Standard Users can complete their own obligations:** This is the primary action designed for them. A PAYE officer completing the monthly PAYE obligation, for example, should not need to ask a Compliance Officer to mark it done. The owner is the accountable person.

**Why Standard Users cannot escalate:** Escalation creates a Gap Analysis record and triggers a formal compliance response chain. This is a Compliance-level decision about whether non-compliance rises to the level of a findable gap.

---

#### Compliance Officer — Compliance Calendar

**What they see:**
- Full list with all cards
- All the Standard User view, plus:
- **"+ Add obligation"** button top right
- **Edit button** on all obligation detail views (opens edit form)
- **Complete button** on all obligations (not just their own)
- **Escalate to Gap Analysis button** on all Overdue obligations
- **Withdraw button** with confirmation on all obligations

**Escalate to Gap Analysis (Compliance only):**
- Opens a modal confirming the gap ID will be created
- Optional escalation notes field
- Shows severity that will be assigned (Critical for Statutory/Regulatory, Major for others)
- Idempotency: if already escalated, shows the existing gap ID rather than creating a duplicate
- On success: a toast appears: "Gap Analysis item [GAP-OBL-26-001] created"

---

#### Admin — Compliance Calendar

**What they see:**
- Everything the Compliance Officer sees
- No functional difference in day-to-day use
- Admin also sees linked_contract_id badge on obligations created via the Contract Register cascade, with a link to the originating contract record
- Admin can view/edit the full audit history of any obligation (completion history, escalation history)

---

### 7.6 Contract Register

The Contract Register tracks all vendor, client, partner, employment, and NDA contracts.

---

#### Standard User — Contract Register

**What they see:**
- Full contract list, all status tabs (Active, Expiring Soon, Expired, Under Review, Terminated, Superseded)
- Status-coloured cards with type icons
- Renewal notice overdue badge (visible to all — informs stakeholders)
- Auto-renewal chip on relevant contracts
- Filter by type and status
- Search bar

**Detail view (read-only):**
- All contract fields: reference, title, counterparty, type, owner, dates, renewal notice, notice period, auto-renewal, lifecycle status, applicable standards
- SharePoint file URL (if present) — clickable link to open the contract document in SharePoint
- Source document code (if present)
- Notes

**What they do NOT see:**
- "+ Add contract" button
- Edit button
- Lifecycle action buttons (Terminate, Supersede, Under Review)
- Add calendar obligation button
- Withdraw button

**Read-only notice banner** shown at top of page.

---

#### Compliance Officer — Contract Register

**What they see:**
- Everything the Standard User sees
- **"+ Add contract"** button
- **Edit button** in detail view (opens full edit form with all fields)
- **"+ Add calendar obligation"** button in detail view — opens modal to create a linked Compliance Calendar item
- **"→ Under Review"** lifecycle button — can move Active contracts to Under Review for legal review
- **Withdraw button** with confirmation
- **No Terminate or Supersede buttons** (those are Admin-only)

**Why Compliance cannot Terminate or Supersede:**
- Terminating a contract is a legal/commercial decision, not a compliance one. It requires executive sign-off.
- Superseding marks a contract as replaced by a new one — this needs confirmation of the replacement contract's existence.
- Both actions are irreversible from a practical standpoint and affect the organisation's legal posture.
- OrgOS Admin represents the appropriate authority level for these actions.

**Edit contract form (Compliance can access):**
- All fields except lifecycle_status (that's Admin-controlled via the lifecycle buttons)
- Compliance can update dates, counterparty name, owner, standards mapping, SharePoint URL, notes

---

#### Admin — Contract Register

**What they see:**
- Everything the Compliance Officer sees
- **"Terminate"** lifecycle button (dark red, opens confirmation modal with warning text)
- **"Supersede"** lifecycle button (purple, opens confirmation modal)
- In the lifecycle confirmation modal: a mandatory notes field explaining the reason for termination/supersession

**Terminate contract flow:**
1. Admin clicks "Terminate"
2. Modal opens: "Move [Contract Name] to Terminated? This is a significant lifecycle decision. Once terminated, the contract will no longer appear in active views."
3. Admin must type a termination reason in a text field
4. Admin clicks "Confirm termination"
5. Backend sets `LifecycleStatus = "Terminated"` and logs to Audit Log with reason
6. Contract card moves to Terminated tab, red border

---

### 7.7 Document Lifecycle

The Document Lifecycle tracks every document from creation trigger through Review → Sensitisation → Approval.

---

#### Standard User — Document Lifecycle

**What they see:**
- Full list of lifecycle entries
- Stage indicators (Review, Sensitisation, Approval) — visual stage bar
- AI Generated badge on auto-drafted documents
- Linked gap ID badge if created from Gap Analysis remediation
- Filter by stage and trigger type

**Actions they can take:**
- **Download** the current draft document (if a SharePoint URL is attached)
- If they are listed as a reviewer or sensitisation participant on a specific entry, they see an "Upload my reviewed version" button for that entry only (upload their annotated copy)

**What they cannot do:**
- Create a new lifecycle entry manually
- Progress the stage (Review → Sensitisation, Sensitisation → Approval)
- Trigger AI policy drafting
- Approve documents

---

#### Compliance Officer — Document Lifecycle

**What they see:**
- Full list
- **"+ Create lifecycle entry"** button
- **"Draft with AI"** button — triggers policy drafter agent with form (title, type, department, notes, standards mapping, trigger reason)
- **Stage progression buttons** on each lifecycle card:
  - "Progress to Sensitisation" (from Review)
  - "Progress to Approval" (from Sensitisation)
  - "Mark Approved" (from Approval) — this finalises the document
- **Upload document** button on each entry
- **Download** button
- When marking Approved: a mandatory "Approved by" field (PersonPicker)

**Draft with AI flow:**
1. Compliance clicks "Draft with AI"
2. Form opens: title, document type, department, applicable standards (checkboxes), trigger reason, linked gap ID (optional), notes for the LLM
3. Submit → calls `/api/v1/agents/draft-document`
4. Loading state: "Drafting policy with AI... this takes 30–90 seconds"
5. On success: shows generated section list, full text preview, and a link to the uploaded .docx in SharePoint
6. A Document Lifecycle entry is automatically created with Stage = Review, AIGenerated = true

---

#### Admin — Document Lifecycle

**What they see:**
- Everything Compliance sees
- A "Reset stage" button on any entry that allows moving backwards (e.g., Sensitisation → Review if a problem is found)
- Admin notes field when resetting stage (mandatory)
- The full AI-generated vs. manual-drafted breakdown in stats at the top

---

### 7.8 Extraction Review

This screen is hidden from Standard Users in the sidebar. It houses the AI document extractor (upload a file, run extraction, preview results) and is the entry point to the AI Review Queue.

---

#### Standard User — Extraction Review

**Not visible.** This page does not appear in their sidebar. If they somehow navigate to the URL directly (shouldn't happen in a SPA), they see:

```
You don't have access to the Extraction Review.
This feature is available to Compliance Officers and OrgOS Admins.
If you believe you need access, contact your OrgOS Admin.
```

---

#### Compliance Officer — Extraction Review

**Full access.**

**What they see:**

**Section 1 — File upload**
- Drag-and-drop zone: "Upload a PDF, DOCX, or TXT file to extract GRC controls"
- Document code field (required): "e.g. DRG-ISMS-POL-ACP-01-26"
- "Write to SharePoint" toggle: if ON, COMPLETE items are written to the AI Review Queue for human decision; if OFF, results are preview-only
- Max file size: 10MB (enforced client-side and server-side)

**Section 2 — SharePoint browser**
- Browse the GRC MASTERY SharePoint library tree
- Click a file → triggers extraction from SharePoint directly (no upload needed)
- "Extract this document" button

**Section 3 — Extraction results (after extraction completes)**
- Summary bar: total extracted / complete / deficient / document type detected
- Tabs: Complete (green) / Deficient (amber) / All
- Each item card shows: risk statement, control statement, control type badge, ISO clause, proposed owner role, evidence type, evidence description
- Deficient items show the deficiency reason in red
- "Write to Review Queue" button — sends COMPLETE items to AI Review Queue list

---

#### Admin — Extraction Review

- Everything Compliance sees
- **Batch extraction trigger** (runs `bulk_extract.py` equivalent via API over all GRC MASTERY documents)
- Progress indicator showing checkpoint/resume status
- Estimated time remaining

---

### 7.9 Assignment & Ownership

This screen is hidden from Standard Users. It resolves Zone 2 (Orphan) items from the AI Review Queue — items from Job Description processing with unclear ownership.

---

#### Standard User — Assignment & Ownership

**Not visible.** Same access-denied screen as Extraction Review.

---

#### Compliance Officer — Assignment & Ownership

**What they see:**
- List of all Orphan queue items (Zone 2)
- Each item shows: responsibility statement, role title, department, orphan direction (JD_to_Doc or Doc_to_JD), orphan classification (POTENTIAL_ORPHAN or ROLE_REFERENCE), and the reason

**Decision buttons per item:**
- **Create document** — opens mini-form to create a new Document Register entry and document lifecycle entry for this gap
- **Add to policy** — links this responsibility to an existing policy document (opens document picker)
- **Intentional** — marks as accepted orphan, no action needed (requires a rationale note)
- **Route to department** — assigns the item to a department head for input (opens PersonPicker)

**Rationale field:** Every decision requires a short rationale (minimum 10 characters). This is logged to the Audit Log.

---

#### Admin — Assignment & Ownership

- Everything Compliance sees
- Can override any previously made decision on orphan items
- Can view the Audit Log entries for past decisions directly from the card

---

### 7.10 Harmonisation

This screen is hidden from Standard Users. It resolves Zone 3 (Harmonisation) items — duplicate or variant controls identified by the Classifier agent.

---

#### Standard User — Harmonisation

**Not visible.** Same access-denied screen.

---

#### Compliance Officer — Harmonisation

**What they see:**
- List of control variant pairs from Zone 3
- Each pair shown in a side-by-side comparison card:
  - Left column: Control A (source document, control statement, control type, proposed owner role, ISO clause)
  - Right column: Control B (same fields)
  - Similarity score badge (e.g., "87% match")
  - The specific differences highlighted inline

**Decision buttons per pair:**
- **Merge** — consolidates into one canonical control (opens merge form where Compliance picks which version of each field to keep, or writes a unified version)
- **Keep separate** — both controls are accepted as intentional variants with rationale
- **Rename and standardise** — aligns terminology without merging content (Compliance edits the control statement for one or both to make them clearly distinct)

**Trigger agent button:**
- "Run harmonisation classifier" — triggers the Classifier agent over all Zone 1 items, populating Zone 3 with new pairs
- Requires Compliance.Lead (already guarded by `require_compliance_lead`)
- Disabled with tooltip if the AI Review Queue has no Zone 1 items

---

#### Admin — Harmonisation

- Everything Compliance sees
- Can revert any harmonisation decision
- Can manually route specific queue items to Zone 3 for human review

---

### 7.11 Control Register

The Control Register holds all confirmed, active controls that have passed human review.

---

#### Standard User — Control Register

**What they see:**
- Full list of all active controls
- Filter by ISO clause, control type (Preventive / Detective / Corrective / Directive), source document
- Each card shows: control statement, control type badge, ISO clause, source document code, owner role, evidence status summary
- Click a control → detail view

**Detail view:**
- Control statement, control type, source document, ISO clause, owner role, risk implication, status
- **Evidence items linked to this control** — a sub-list showing each evidence item's type, description, status, and due date
- For evidence items where `owner_role` matches a role they hold: a **Submit evidence** button is shown in-line

**What they do NOT see:**
- No "Add control" button (controls are created via the Zone 1 cascade only — no manual creation for Standard Users)
- No status change dropdown
- No edit button

---

#### Compliance Officer — Control Register

**What they see:**
- Everything Standard User sees
- **Status update dropdown** on the detail view: can change a control from Active to Under Review or Withdrawn
- Can view the Zone 1 cascade history: which queue item created this control, who accepted it
- Can create a manual evidence item linked to a control

---

#### Admin — Control Register

- Everything Compliance sees
- **"Add control manually"** button (emergency bypass of the queue cascade)
- Can hard-link controls to ISO/NDPA clauses that weren't captured in extraction
- Can reassign the owner role of any control

---

### 7.12 Evidence Tracker

Evidence items are linked to controls and track the collection lifecycle: Pending → Submitted → Accepted/Rejected.

---

#### Standard User — Evidence Tracker

**What they see:**
The Evidence Tracker is the primary active-work screen for Standard Users. It is personalised.

**Their default view:**
- Automatically filtered to evidence items linked to controls where `owner_role` matches their assigned role(s)
- A "My evidence" tab is the default
- An "All evidence" tab is also available (read-only view of all items, useful to understand overall compliance posture)

**Status breakdown at the top:**
- Overdue (red), Pending (amber), Submitted (blue), Accepted (green), Rejected (red)

**Each evidence card shows:**
- Evidence description
- Evidence type badge (LOG, CFG, APR, FRM, etc.)
- Source system
- Evidence format
- Due date
- Control it relates to (linked, opens control detail on click)
- Validation criteria (what the Compliance Officer will check)
- Status badge

**Actions on their own evidence:**
- **Submit** button (visible on Pending and Rejected items they own):
  - Opens submission modal
  - Fields: Evidence link (URL or file path), Submission notes
  - On submit: status → Submitted
- For Rejected items: submit again with a note addressing the rejection

**Actions on others' evidence:**
- Read-only. No submit button.

**What they do NOT see:**
- Verify button (that's Compliance-only)
- Create evidence button
- Any filter options that would expose other users' personal data unnecessarily (they can see ALL evidence in the "All" tab but cannot act on it)

---

#### Compliance Officer — Evidence Tracker

**What they see:**
- Everything Standard User sees
- Default view is "All evidence" not "My evidence" (Compliance manages the whole register)
- **Verify button** on Submitted items — opens verification modal:
  - Decision: Accepted / Rejected
  - Reviewer notes (required)
  - On Accepted: evidence item status → Accepted; linked control's evidence coverage improves; Standards Map traffic light may turn green
  - On Rejected: status → Rejected; submitter sees the rejection with reviewer notes; they can resubmit
- **Create evidence** button — manually create an evidence item linked to a specific control
- Filter by: all statuses, control ID, evidence type, owner role, date range

---

#### Admin — Evidence Tracker

- Everything Compliance sees
- Can **reassign evidence ownership** (change owner_role on an evidence item)
- Can **extend due dates** on evidence items
- Can see the full audit trail of submissions and verifications for each evidence item

---

### 7.13 Strategic Risks

The Strategic Risk Register is curated by ExCo (Executive Committee) and tracks high-level organisational risks.

---

#### Standard User — Strategic Risks

**What they see:**
- Full read-only view of the Strategic Risk Register
- Risk cards sorted by risk_score descending (highest risk first)
- Heat map colouring: 1–3 green, 4–6 amber, 7–9 red, 10–12 dark red
- Each card: risk description, category, likelihood × impact = score, status, treatment, linked gap ID (if escalated from Gap Analysis)
- Filter by category, status

**What they do NOT see:**
- "+ Add risk" button
- Edit or delete buttons
- Accept risk / Reject risk buttons
- Score adjustment

**Purpose for Standard Users:** Awareness. Senior employees and department heads use this to understand the organisational risk context for their area.

---

#### Compliance Officer — Strategic Risks

**What they see:**
- Same read-only view as Standard Users
- Compliance Officers cannot create or edit strategic risks directly — that is an ExCo/Admin function
- They CAN escalate from Gap Analysis (the `POST /gap-analysis/{id}/accept-risk` endpoint creates a Risk item — this is their indirect write path)
- A "Linked from Gap Analysis" badge on risks created via escalation, which they can click through to the original gap

**What they do NOT see:**
- "+ Add risk" button (that's Admin-only)
- Direct edit of risk score, status, or treatment

---

#### Admin — Strategic Risks

**What they see:**
- Full CRUD
- **"+ Add risk"** button opens a risk creation form:
  - Description (risk statement)
  - Category (Partnership / Regulatory / Reputational / Operational / Financial / Technology)
  - Likelihood (1–3 slider)
  - Impact (1–4 slider)
  - Score calculated live: `likelihood × impact`
  - Treatment plan (textarea)
  - Status (Open / Under treatment / Accepted / Transferred / Avoided / Closed)
  - Related gap ID (optional link)
- **Edit button** in detail view — can update all fields including score, status, treatment
- **Status transition buttons** with validation:
  - Open → [Under treatment, Accepted, Transferred, Avoided]
  - Under treatment → [Accepted, Transferred, Avoided, Closed]
  - Accepted / Transferred / Avoided → [Closed]
  - Closed → (no transitions — terminal state)
- **Risk score history** — if score changed over time (via edits), shows the historical trend

---

### 7.14 Standards Map

The Standards Map provides a live, traffic-light view of ISO 27001, ISO 9001, and NDPA clause coverage.

---

#### Standard User — Standards Map

**What they see:**
- Full grid of clauses with traffic light icons (green / amber / red)
- Colour definitions shown in legend:
  - Green: controls in place, evidence accepted, owner assigned
  - Amber: evidence submitted not verified, or evidence due soon (≤7 days)
  - Red: no controls, overdue evidence, rejected evidence, or unassigned owner
- Filter by standard (ISO 27001 / ISO 9001 / NDPA)
- Click a clause → drill-down showing the full chain:
  - Clause title and description
  - All controls mapped to this clause
  - For each control: control statement, owner role, evidence items and their status
- This is a full read — Standard Users see the complete chain, not a summary. They need this to understand what evidence they're responsible for.

**What they do NOT see:**
- "Run Gap Analysis" trigger button

---

#### Compliance Officer — Standards Map

**What they see:**
- Everything Standard User sees
- **"Run gap analysis"** button in the top section:
  - Triggers the Gap Analyzer agent: `POST /api/v1/agents/gap-analysis/run`
  - Loading state: "Analysing coverage... this may take 2–5 minutes"
  - On complete: toast with count of new gaps identified
  - Redirects to Gap Analysis page
- A coverage percentage summary per standard (e.g., "ISO 27001: 63% covered")

---

#### Admin — Standards Map

- Everything Compliance sees
- Can manually add clause mappings (link a control to an additional ISO clause not captured in extraction)

---

### 7.15 Gap Analysis

Gap Analysis tracks compliance gaps from two sources: the AI Gap Analyzer agent and AuditItems from the extraction pipeline.

---

#### Standard User — Gap Analysis

**What they see:**
- Full list of all gap findings, sorted Critical → Major → Minor
- Filter by severity, standard, status
- Status badges: Open / In progress / Accepted risk / Closed
- Each gap card: gap ID, standard, clause, finding description, severity, target date, assigned to (if set), current status

**Detail view:**
- Full gap fields: GapId, standard, clause, severity, finding, impact, target date, status
- **Proposed remediation package** — the accordion that can expand to show:
  - Recommended document to create or update
  - Suggested controls
  - Evidence types to collect
  - Roles to assign
  - Target date
  - Verification criteria
  - Standards mapping

**What they do NOT see:**
- Status change buttons (Open → In progress → Closed)
- "Accept as risk" button
- "Run Gap Analysis" trigger
- "Create gap" button

---

#### Compliance Officer — Gap Analysis

**What they see:**
- Full list with all cards
- **"Run Gap Analysis"** button:
  - Triggers `POST /api/v1/agents/gap-analysis/run`
  - Loading spinner with estimated duration
  - On complete: new gaps appear in the list automatically (React Query invalidation)
- **Status update buttons** on each gap:
  - "Start remediation" → status = In progress
  - "Close gap" → status = Closed (requires confirmation and notes)
- **"Accept as risk"** button on Open and In progress gaps:
  - Opens modal: "This will create a Strategic Risk Register entry linked to this gap. The gap status will be set to Accepted risk."
  - Escalation notes field
  - On confirm: calls `POST /gap-analysis/{id}/accept-risk`
  - Toast: "Strategic Risk item RSK-26-001 created"
- **"Draft remediation policy"** button:
  - Pre-fills the Document Lifecycle AI Draft form with the gap's remediation context
  - User reviews and submits → creates lifecycle entry and AI-drafted policy
- Filter by: all filters Standard User sees

---

#### Admin — Gap Analysis

- Everything Compliance sees
- **"+ Create gap manually"** button — for audit-sourced gaps not captured by the AI agent
- Can edit the severity and finding of any gap
- Can delete (withdraw) gaps that were created in error
- Can override the target date

---

### 7.16 AI Review Queue

The AI Review Queue is the central human-in-the-loop decision screen. Standard Users do not see this.

---

#### Standard User — AI Review Queue

**Not visible.** The Queue page is hidden from Standard User navigation entirely. If an item has been routed to them specifically (via the "Route to owner" decision), they receive a Work Hub notification but do not get queue access — they receive a targeted action request instead.

---

#### Compliance Officer — AI Review Queue

**What they see:**

**Three tabs:**

**Tab 1 — Extraction (Zone 1)**
- Controls extracted from policy/contract documents awaiting decision
- Each card shows: risk statement, control statement, control type badge, ISO clause, proposed owner role, evidence type, evidence description, confidence score, source document code, extraction category
- Deficiency reason shown on deficient items (in amber/red)
- Actions per card:
  - **Accept control** → triggers Zone 1 cascade: creates Control Register item + Evidence Tracker item + Audit Log entry
  - **Edit & accept** → opens inline edit form, then cascades on save
  - **Reject** → opens rationale field (required), logs to Audit Log
  - **Route to owner** → opens PersonPicker to assign to a role owner for their input

**Tab 2 — Orphan (Zone 2)**
- Items from JD processing with unclear ownership
- Each card shows: responsibility statement, role title, department, orphan direction, classification, reason
- Actions: Create document / Add to existing policy / Intentional / Route to department

**Tab 3 — Harmonisation (Zone 3)**
- Duplicate/variant control pairs from the Classifier agent
- Side-by-side view
- Actions: Merge / Keep separate / Rename and standardise

**Rationale gate:** Every destructive or consequential action (Reject, Intentional, Merge, Keep separate) requires a rationale note before the button activates.

**Optimistic updates:** Accepted/rejected items move out of the list immediately on click (optimistic update with React Query), without waiting for the server round-trip. On server error, the item reappears with an error banner.

---

#### Admin — AI Review Queue

- Everything Compliance sees
- Can revert any accepted control (marks the Control Register item as Withdrawn and removes it from the Evidence Tracker — requires mandatory Admin notes)
- Can reassign queue items between zones manually
- Sees the Audit Log entries for past decisions inline on each card

---

## 8. Permission Matrix Summary

| Action | Standard User | Compliance | Admin |
|---|---|---|---|
| **Document Register** | | | |
| View documents | ✅ | ✅ | ✅ |
| Create document | ❌ | ✅ | ✅ |
| Edit document | ❌ | ✅ | ✅ |
| Withdraw document | ❌ | ✅ | ✅ |
| **Role Register** | | | |
| View roles | ✅ | ✅ | ✅ |
| Create role | ❌ | ❌ | ✅ |
| Edit role | ❌ | ❌ | ✅ |
| Assign role holder | ❌ | ❌ | ✅ |
| **Compliance Calendar** | | | |
| View obligations | ✅ | ✅ | ✅ |
| Create obligation | ❌ | ✅ | ✅ |
| Edit obligation | ❌ | ✅ | ✅ |
| Complete own obligation | ✅ (own only) | ✅ | ✅ |
| Complete any obligation | ❌ | ✅ | ✅ |
| Escalate to Gap Analysis | ❌ | ✅ | ✅ |
| Withdraw obligation | ❌ | ✅ | ✅ |
| **Contract Register** | | | |
| View contracts | ✅ | ✅ | ✅ |
| Create contract | ❌ | ✅ | ✅ |
| Edit contract | ❌ | ✅ | ✅ |
| Set Under Review | ❌ | ✅ | ✅ |
| Terminate contract | ❌ | ❌ | ✅ |
| Supersede contract | ❌ | ❌ | ✅ |
| Add calendar obligation | ❌ | ✅ | ✅ |
| **Document Lifecycle** | | | |
| View lifecycle | ✅ (read-only) | ✅ | ✅ |
| Create lifecycle entry | ❌ | ✅ | ✅ |
| Progress stages | ❌ | ✅ | ✅ |
| Upload document | ✅ (assigned items) | ✅ | ✅ |
| Approve document | ❌ | ✅ | ✅ |
| Draft policy with AI | ❌ | ✅ | ✅ |
| Reset stage | ❌ | ❌ | ✅ |
| **Extraction & Queue** | | | |
| View extractor | ❌ | ✅ | ✅ |
| Trigger extraction | ❌ | ✅ | ✅ |
| View AI Review Queue | ❌ | ✅ | ✅ |
| Accept/reject queue item | ❌ | ✅ | ✅ |
| Revert accepted control | ❌ | ❌ | ✅ |
| View Assignment/Orphan | ❌ | ✅ | ✅ |
| Make orphan decisions | ❌ | ✅ | ✅ |
| View Harmonisation | ❌ | ✅ | ✅ |
| Make harmonisation decisions | ❌ | ✅ | ✅ |
| Run harmonisation classifier | ❌ | ✅ | ✅ |
| **Control Register** | | | |
| View controls | ✅ | ✅ | ✅ |
| Update control status | ❌ | ✅ | ✅ |
| Create control manually | ❌ | ❌ | ✅ |
| **Evidence Tracker** | | | |
| View all evidence | ✅ | ✅ | ✅ |
| Submit own evidence | ✅ | ✅ | ✅ |
| Verify evidence | ❌ | ✅ | ✅ |
| Create evidence item | ❌ | ✅ | ✅ |
| Reassign evidence | ❌ | ❌ | ✅ |
| **Strategic Risks** | | | |
| View risks | ✅ | ✅ | ✅ |
| Create risk | ❌ | ❌ (via gap escalation only) | ✅ |
| Edit risk | ❌ | ❌ | ✅ |
| Change risk status | ❌ | ❌ | ✅ |
| **Standards Map** | | | |
| View map | ✅ | ✅ | ✅ |
| Drill down to clause chain | ✅ | ✅ | ✅ |
| Run gap analysis | ❌ | ✅ | ✅ |
| **Gap Analysis** | | | |
| View gaps | ✅ | ✅ | ✅ |
| View remediation package | ✅ | ✅ | ✅ |
| Update gap status | ❌ | ✅ | ✅ |
| Escalate to risk | ❌ | ✅ | ✅ |
| Run gap analysis agent | ❌ | ✅ | ✅ |
| Create gap manually | ❌ | ❌ | ✅ |

---

## 9. Implementation Steps — Frontend

The frontend changes are structured in phases. Each phase is independently deployable.

### Phase 1 — Create the role hook and context

**File:** `frontend/src/hooks/useCurrentUserRole.js`
- Create the hook as specified in Section 3
- Returns: `{ oid, name, email, roles, isAdmin, isCompliance, isStandard, roleLabel }`
- This hook is the ONLY source of role information in the frontend
- Replace the existing `useUserRoles` in `AIReviewQueue/index.jsx` with this

**File:** `frontend/src/components/shared/ReadOnlyBanner.jsx`
- Create the shared read-only notice component
- Props: `message` (defaults to "You have read-only access. Contact Compliance to request changes.")

**File:** `frontend/src/components/shared/RoleBadge.jsx`
- Small chip component showing the role label
- Used in the TopBar

### Phase 2 — Update TopBar

**File:** `frontend/src/components/layout/TopBar.jsx`
- Import `useCurrentUserRole`
- Show `RoleBadge` next to the user's name
- Standard User: grey chip "Standard User"
- Compliance: blue chip "Compliance"
- Admin: purple chip "Admin" with shield icon

### Phase 3 — Update Sidebar

**File:** `frontend/src/components/layout/Sidebar.jsx`
- Import `useCurrentUserRole`
- Add `requiredRole` property to the NAV items that need gating:
  ```javascript
  { id: "extraction",   label: "Extraction review",     tier: 2, requiredRole: "compliance" },
  { id: "assignment",   label: "Assignment & ownership", tier: 2, requiredRole: "compliance" },
  { id: "harmonisation",label: "Harmonisation",          tier: 2, requiredRole: "compliance" },
  ```
- Filter NAV items before rendering: skip items where `requiredRole = "compliance"` if `!isCompliance`
- Skip items where `requiredRole = "admin"` if `!isAdmin`

### Phase 4 — Update each page

Apply the pattern to every page in this order (most impactful first):

1. **Work Hub** — three different dashboard layouts
2. **Evidence Tracker** — Standard User filtered view + Submit, Compliance adds Verify
3. **Document Register** — hide create/edit/delete for Standard User
4. **Compliance Calendar** — hide create/escalate for Standard User, show Complete only for owner
5. **Contract Register** — hide create/edit for Standard User, hide lifecycle buttons for Compliance
6. **Document Lifecycle** — hide AI draft and stage progression for Standard User
7. **Control Register** — hide status change for Standard User
8. **Gap Analysis** — hide status update and escalate for Standard User
9. **Strategic Risks** — hide all write actions for Standard User and Compliance
10. **Standards Map** — hide Run Gap Analysis trigger for Standard User
11. **AI Review Queue** — full role gate (Compliance-only) with access-denied state
12. **Harmonisation** — full role gate (Compliance-only)
13. **Assignment & Ownership** — full role gate (Compliance-only)

### Phase 5 — Update App.jsx

**File:** `frontend/src/App.jsx`
- Import `useCurrentUserRole`
- Remove the hardcoded `const IS_COMP = true`
- Route rendering should check roles before rendering gated pages:
  ```javascript
  case "extraction":
    return isCompliance ? <ExtractionReview /> : <AccessDenied />;
  case "assignment":
    return isCompliance ? <AssignmentOwnership /> : <AccessDenied />;
  case "harmonisation":
    return isCompliance ? <Harmonisation /> : <AccessDenied />;
  ```

**File:** `frontend/src/pages/shared/AccessDenied.jsx` (create)
- Shown when a user navigates directly to a restricted page
- Message: "You don't have access to [page name]. This feature is available to [required role] and above. Contact your OrgOS Admin to request access."

---

## 10. Implementation Steps — Backend

### Phase 1 — Create the `require_admin` dependency

**File:** `auth/validator.py`
```python
async def require_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if "OrgOS.Admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the OrgOS Admin role. Contact your system administrator.",
        )
    return user
```

### Phase 2 — Add guards to existing endpoints

**File:** `grc/router.py`
- `create_document`, `update_document`, `delete_document` → `Depends(require_compliance_lead)`
- `create_role`, `update_role`, `assign_role` → `Depends(require_admin)`
- `create_obligation`, `update_obligation`, `delete_obligation` → `Depends(require_compliance_lead)`
- `create_contract`, `update_contract`, `delete_contract` → `Depends(require_compliance_lead)`
- `update_contract_lifecycle` (Terminate/Supersede) → `Depends(require_admin)`, Under Review → `Depends(require_compliance_lead)` (split into two endpoints or check in handler)

**File:** `strategic_risks/router.py`
- `create_risk`, `update_risk` → `Depends(require_admin)`

**File:** `gap_analysis/router.py`
- `update_gap_status`, `accept_risk` → `Depends(require_compliance_lead)`
- `create_gap` (manual) → `Depends(require_admin)`

### Phase 3 — Ownership checks in service layer

**File:** `grc/service.py`
Update `complete_obligation` signature to receive `roles` parameter from the current user:
```python
async def complete_obligation(item_id, user_oid, user_name, body, roles: list[str]):
    item = await get_list_item(...)
    owner_oid = item["fields"].get("OwnerEntraId", "")
    is_compliance = "Compliance.Lead" in roles or "OrgOS.Admin" in roles
    is_owner = owner_oid == user_oid
    if not is_compliance and not is_owner:
        raise HTTPException(403, "You can only complete obligations assigned to you.")
```

**File:** `evidence_tracker/router.py` / `service.py`
Add ownership check to `submit_evidence`:
```python
# Only the evidence owner or a Compliance Lead can submit
evidence_owner_oid = item["fields"].get("OwnerEntraId", "")
is_compliance = "Compliance.Lead" in user.roles or "OrgOS.Admin" in user.roles
if not is_compliance and evidence_owner_oid != user.oid:
    raise HTTPException(403, "You can only submit evidence for items assigned to your role.")
```

### Phase 4 — Pass user roles to router handlers

Update all affected router handlers to pass `user.roles` through to service functions that need ownership checks:

```python
@router.patch("/compliance/{item_id}/complete")
async def complete_obligation(
    item_id: str,
    body: CompleteObligation,
    user: CurrentUser = Depends(get_current_user),  # any authenticated user
):
    return await service.complete_obligation(
        item_id,
        user_oid=user.oid,
        user_name=user.name,
        body=body,
        roles=user.roles,  # pass roles for ownership check in service
    )
```

---

## 11. Role Denial UX Patterns

When a user without sufficient permissions encounters a restricted area, OrgOS uses consistent, contextual patterns rather than generic error pages.

### Pattern A — Hidden element (most common)

The button, form, or section simply does not exist in the DOM. No placeholder, no greyed-out element. Used when the feature has zero value to the lesser role.

**When to use:** Agent trigger buttons, create/edit buttons in registers, AI Review Queue decision buttons.

### Pattern B — Disabled button with tooltip

The button is visible but disabled. On hover, a tooltip explains: *"Requires Compliance Lead role"* or *"Requires OrgOS Admin role"*. Used when the user needs to understand the feature exists (so they can request access), but cannot use it yet.

**When to use:** Lifecycle action buttons where Compliance can see Terminate but cannot use it. Standard User seeing the Standards Map trigger button.

```jsx
<button
  disabled={!isAdmin}
  title={!isAdmin ? "Requires OrgOS Admin role" : undefined}
  style={{ opacity: isAdmin ? 1 : 0.4, cursor: isAdmin ? "pointer" : "not-allowed" }}
  onClick={handleTerminate}
>
  Terminate contract
</button>
```

### Pattern C — Read-only notice banner

A non-blocking informational banner at the top of the page. The page content is fully visible. Used on all Tier 1 register pages when accessed by a Standard User.

```
┌─────────────────────────────────────────────────────────────────┐
│  📋  You have read-only access to this register.               │
│  To request changes, contact the Compliance team.              │
└─────────────────────────────────────────────────────────────────┘
```

### Pattern D — Access denied page

A full-page replacement for screens that are entirely gated. Used for Extraction Review, Assignment & Ownership, and Harmonisation when a Standard User navigates there.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  🔒  Access restricted                                          │
│                                                                  │
│  The Extraction Review is available to Compliance Officers      │
│  and OrgOS Admins.                                              │
│                                                                  │
│  Your current role: Standard User                               │
│                                                                  │
│  If you need access to this feature, contact your               │
│  OrgOS Admin (admin@dragnet-solutions.com).                     │
│                                                                  │
│  [← Go to Work Hub]                                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Pattern E — API 403 error toast

When a backend API call returns 403 (which should not happen normally because the UI hides restricted actions), the Axios response interceptor shows a toast:

```
⚠  Access denied: [detail message from backend]
    This action requires the Compliance Lead role.
```

The toast auto-dismisses after 6 seconds and is displayed in the top-right corner. This is the safety net for cases where the UI fails to hide something it should have hidden.

---

## 12. Testing Checklist

Before declaring RBAC implementation complete, verify the following scenarios manually and in automated tests.

### Standard User Scenarios

- [ ] Login as a user with no Entra app role assigned
- [ ] Work Hub shows only their own obligations and evidence items
- [ ] Document Register: no create/edit/delete buttons visible
- [ ] Document Register: can read all documents and click into detail view
- [ ] Role Register: can view all roles, see "You" chip on their own role
- [ ] Compliance Calendar: can see all obligations, can complete their own
- [ ] Compliance Calendar: Complete button absent on obligations not owned by them
- [ ] Compliance Calendar: Escalate button absent on all items
- [ ] Contract Register: read-only, no create/edit/lifecycle buttons
- [ ] Evidence Tracker: sees only their own evidence in "My evidence" tab
- [ ] Evidence Tracker: Submit button present on their own Pending items
- [ ] Evidence Tracker: Submit button absent on others' items
- [ ] Evidence Tracker: Verify button absent on all items
- [ ] Strategic Risks: read-only, no create/edit/delete buttons
- [ ] Standards Map: no "Run Gap Analysis" button
- [ ] Gap Analysis: no status update or escalate buttons, remediation package readable
- [ ] Extraction Review URL: access-denied page shown, not the extractor
- [ ] AI Review Queue URL: access-denied page shown
- [ ] Harmonisation URL: access-denied page shown
- [ ] Direct API call to create document: 403 returned
- [ ] Direct API call to escalate obligation: 403 returned
- [ ] Direct API call to verify evidence: 403 returned
- [ ] Direct API call to accept queue item: 403 returned

### Compliance Officer Scenarios

- [ ] Login as a user with `Compliance.Lead` role in Entra
- [ ] Work Hub shows organisational urgency streams (all obligations, all evidence, all queue items)
- [ ] Document Register: create/edit/delete buttons visible and functional
- [ ] Compliance Calendar: can create, edit, complete any obligation, escalate overdue
- [ ] Contract Register: can create, edit, add obligation, set Under Review
- [ ] Contract Register: Terminate and Supersede buttons absent (or disabled with tooltip)
- [ ] Document Lifecycle: stage progression, AI draft trigger functional
- [ ] Extraction Review: page accessible, upload and extract functional
- [ ] AI Review Queue: accessible, decisions functional (Accept/Edit/Reject/Route)
- [ ] Assignment & Ownership: accessible, orphan decisions functional
- [ ] Harmonisation: accessible, variant decisions functional
- [ ] Evidence Tracker: Verify button visible on Submitted items
- [ ] Gap Analysis: status update, escalate to risk, AI run trigger functional
- [ ] Strategic Risks: read-only, no create/edit buttons
- [ ] Direct API call to create risk: 403 returned
- [ ] Direct API call to terminate contract: 403 returned
- [ ] Direct API call to assign role holder: 403 returned

### Admin Scenarios

- [ ] Login as a user with `OrgOS.Admin` role in Entra
- [ ] Work Hub shows all urgency streams plus system health panel
- [ ] Role Register: create/edit/assign/unassign functional
- [ ] Contract Register: Terminate and Supersede lifecycle buttons functional
- [ ] Strategic Risks: full CRUD functional, score updates work, status transitions validated
- [ ] Document Lifecycle: Reset stage button functional
- [ ] Gap Analysis: create gap manually functional
- [ ] All Compliance scenarios also work (Admin is a superset)

### Edge Cases

- [ ] User signs out and back in with a different account — role updates correctly
- [ ] User with `OrgOS.Admin` role tries to move a risk from Closed to Open — gets 422 invalid transition error
- [ ] User is the owner of an obligation AND a Standard User — Complete button is shown
- [ ] User is NOT the owner and IS a Standard User — Complete button absent
- [ ] Backend returns 403 on a normally-hidden action — error toast shown without crashing the page
- [ ] `SKIP_AUTH=true` in dev — returns mock `OrgOS.Admin` user, all features visible (this is correct dev behaviour)

---

*End of RBAC Plan — Dragnet Solutions Limited | OrgOS Platform*
*Prepared for implementation review. Changes to this plan should be versioned and reviewed by the OrgOS Admin.*
