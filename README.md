# OrgOS — Dragnet Solutions Limited
**Internal GRC Orchestration Platform | DRG-AUTO-BRIEF-GRC-01-26**

OrgOS is Dragnet's compliance management platform. It replaces manual spreadsheet-based GRC tracking with a live, AI-assisted system that keeps the control register, evidence trail, policy library, and risk register in sync — and lets any staff member ask questions about policies and procedures in plain English through a built-in AI assistant.

---

## Table of Contents

1. [What It Does](#1-what-it-does)
2. [Architecture](#2-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Project Structure](#4-project-structure)
5. [All Modules Explained](#5-all-modules-explained)
6. [Core Data Flows](#6-core-data-flows)
7. [The AI/LLM System](#7-the-aillm-system)
8. [The NL Search Chatbot](#8-the-nl-search-chatbot)
9. [Authentication & Security](#9-authentication--security)
10. [Setup — Backend](#10-setup--backend)
11. [Setup — Frontend](#11-setup--frontend)
12. [Environment Variables](#12-environment-variables)
13. [Azure App Registration](#13-azure-app-registration)
14. [SharePoint Setup](#14-sharepoint-setup)
15. [Running Tests](#15-running-tests)
16. [Scripts & Utilities](#16-scripts--utilities)
17. [Key Architectural Rules](#17-key-architectural-rules)

---

## 1. What It Does

| Capability | Description |
|---|---|
| **Document Register** | Track all policy/procedure documents — version, owner, status, review dates |
| **Org Roles** | Read-only directory of users and their `org_roles`, read live from Entra ID (assignment happens exclusively in the Dragnet ERP admin panel) |
| **Compliance Calendar** | Track statutory, licensing, and regulatory deadlines per authority |
| **Contract Register** | Monitor vendor contracts, expiry dates, and renewal obligations |
| **AI Extractor** | Upload a PDF or DOCX — the AI extracts structured `{risk, control, evidence}` triplets |
| **AI Review Queue** | Human-in-the-loop staging: accept, reject, or edit extracted controls before they go live |
| **Control Register** | The authoritative list of confirmed, active controls linked to roles and evidence |
| **Evidence Tracker** | Evidence lifecycle: Pending → Submitted → Accepted/Rejected per control |
| **Document Lifecycle** | Draft creation through Review → Sensitisation → Approval stages |
| **Standards Map** | Live ISO 27001 / ISO 9001 / NDPA clause coverage with traffic-light indicators |
| **Gap Analysis** | AI-identified and audit-sourced gaps with full remediation packages |
| **Strategic Risk Register** | ExCo-curated risk register with likelihood × impact scoring |
| **Harmonisation** | Detect and resolve duplicate or variant controls across documents |
| **NL Search Chatbot** | Plain-English Q&A over live GRC data — grounded answers, never hallucinated |

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Dragnet ERP shell                        │
│  Sole authority for login. Sets an erp_auth HttpOnly     │
│  cookie on .dragnet.ng after the user signs in there.    │
└────────────────────────┬────────────────────────────────┘
                         │ redirect / bounce-back (no token in URL)
┌────────────────────────▼────────────────────────────────┐
│            Browser — OrgOS React SPA (standalone)         │
│  No login page, no MSAL. Boots by checking its own        │
│  backend's session endpoint; the erp_auth cookie travels  │
│  automatically on every request (credentials: include).   │
└────────────────────────┬────────────────────────────────┘
                         │ HTTPS + erp_auth cookie
┌────────────────────────▼────────────────────────────────┐
│               FastAPI Backend (Python)                   │
│  • Independently validates the erp_auth JWT (RS256/JWKS) │
│  • Reads org_roles claim — never assigns it               │
│  • Business logic + SharePoint field mapping             │
│  • Calls Microsoft Graph API (client credentials)        │
│  • Calls LLM gateway (GPT-4o-mini) for AI features       │
│  • Calls Ollama locally for document extraction          │
└─────┬──────────────────┬───────────────────────────────-┘
      │                  │                   │
      ▼                  ▼                   ▼
┌──────────┐   ┌──────────────────┐   ┌─────────────────┐
│ Microsoft │   │  gpu.idhub.ng    │   │  Ollama (local) │
│ Graph API │   │  LLM Gateway     │   │  localhost:11434 │
│ SharePoint│   │  /chat → GPT-4o  │   │  llama3         │
│ Lists     │   │  /embed → BGE-M3 │   │  extraction only│
└──────────┘   └──────────────────┘   └─────────────────┘
      │
      ▼
┌──────────────────────────────────────┐
│  SharePoint Online                   │
│  dragnetnigeria.sharepoint.com       │
│  /sites/orgos  (all list data)       │
│  /sites/everybody  (documents)       │
└──────────────────────────────────────┘
```

**There is no relational database.** All application data lives in SharePoint Lists, accessed via the Microsoft Graph API. The backend is stateless — SharePoint is the single source of truth for all persistent state, except identity and roles, which live entirely in Entra ID / the Dragnet ERP (see [§9](#9-authentication--security)).

OrgOS is a **Tier-1 standalone module** of the Dragnet ERP (own `*.dragnet.ng` subdomain, not Module Federation). It owns no login screen, no app registration, and no role-assignment UI of its own — see `docs.local/orgos_notes.md` and `docs.local/ERP_*.md` for the full integration reference.

---

## 3. Technology Stack

### Backend

| Component | Technology | Notes |
|---|---|---|
| Web framework | FastAPI ≥ 0.115 | `lifespan=` pattern, async throughout |
| ASGI server | uvicorn[standard] | `--reload` in dev, `watchfiles` for detection |
| HTTP client | httpx ≥ 0.27 | All Graph API calls — never `requests` or `aiohttp` |
| Data validation | Pydantic v2 ≥ 2.7 | `model_validate()`, `model_dump()`, `@field_validator` |
| Settings | pydantic-settings | `BaseSettings` + `.env` file |
| JWT validation | python-jose[cryptography] | RS256, Entra ID tokens |
| PDF extraction | pypdf | Text extraction from uploaded PDFs |
| DOCX extraction | python-docx | Text extraction + DOCX generation |
| Vector search | ChromaDB | Controls and procedure steps, BGE-M3 embeddings |
| Testing | pytest + pytest-asyncio | `asyncio_mode = auto` |
| HTTP mocking | respx | Mocks all Graph API calls in tests |

### Frontend

| Component | Technology | Notes |
|---|---|---|
| Framework | React 18 | Hooks only, no class components |
| Build tool | Vite 5 | ESM, fast HMR |
| Auth | None (no MSAL) | Session is the ERP's `erp_auth` HttpOnly cookie — OrgOS never talks to Azure AD directly. See [§9](#9-authentication--security). |
| Server state | @tanstack/react-query v5 | All backend data — caching, stale time, invalidation |
| HTTP | axios | `withCredentials: true` — the session cookie travels automatically, no manual token header |
| Routing | react-router-dom v6 | Client-side navigation |
| Icons | lucide-react + Font Awesome | `@fortawesome/react-fontawesome` for the navbar (parity with the ERP shell's icon set); lucide-react elsewhere (chat, dropdown chevrons) |
| Fonts | Plus Jakarta Sans (Google Fonts) | Loaded in `index.html` — matches the Dragnet ERP shell's typography |
| Chat persistence | IndexedDB (idb) | Chat sessions survive page refresh |

---

## 4. Project Structure

```
Orgos/
├── .env                            ← Secrets — NEVER commit (gitignored)
├── .env.example                    ← Template — all keys with placeholder values
├── requirements.txt
├── pytest.ini                      ← asyncio_mode = auto
├── config.py                       ← All settings via pydantic-settings
├── main.py                         ← FastAPI app, CORS, lifespan, all routers
│
├── graph/                          ← Microsoft Graph API layer
│   ├── auth.py                     ← Token acquisition + in-process cache
│   ├── client.py                   ← SharePoint List CRUD, file ops, user resolution
│   └── exceptions.py               ← GraphAPIError hierarchy
│
├── auth/
│   ├── validator.py                 ← JWT decode, JWKS cache, CurrentUser dataclass, org_roles parsing
│   └── router.py                    ← /api/auth/session, /api/auth/revoke — NOT under /api/v1
│                                       (session endpoints only ever read/clear the ERP's
│                                        erp_auth cookie; OrgOS never sets it)
│
├── org_roles/                       ← Read-only org_roles directory (Entra ID via Graph,
│   └── router.py                       not SharePoint) — /api/v1/org-roles
│
├── grc/                            ← Tier 1 GRC registers (Document, Compliance Calendar,
│   │                                   Contract — the Role Register was retired, see below)
│   ├── constants.py                ← SharePoint column name mappings + enum values
│   ├── schemas.py                  ← Pydantic v2 models for the three registers
│   ├── service.py                  ← Business logic, SP ↔ schema mapping
│   └── router.py                   ← /api/v1/grc/*
│
├── agents/
│   ├── llm_client.py               ← Central LLM router (gateway → RunPod → Ollama)
│   ├── extractor/                  ← PDF/DOCX → {risk, control, evidence} triplets
│   ├── classifier/                 ← Post-extraction harmonisation + dedup
│   ├── policy_drafter/             ← AI policy generation + .docx build + SP upload
│   ├── gap_analyzer/               ← Gap analysis vs ISO 27001/9001/NDPA
│   ├── cdi_checker/                ← CDI document quality validation
│   └── nl_search/                  ← NL Search chatbot (full RAG pipeline)
│       ├── intent_classifier.py    ← Routes question → compliance/procedural/both/conversational
│       ├── entity_extractor.py     ← Pulls ISO clause, keywords, status from question
│       ├── compliance_search.py    ← Full-fetch + Python-filter across 6 SP registers
│       ├── procedural_search.py    ← ChromaDB procedures_v1 + SP procedural steps
│       ├── embedder.py             ← BGE-M3 embeddings via GPU gateway /embed
│       ├── vector_store.py         ← ChromaDB (controls_v1, procedures_v1)
│       ├── response_formatter.py   ← Structures raw results for UI (fallback answer)
│       ├── response_generator.py   ← RAG: builds context → LLM → grounded answer
│       ├── memory_service.py       ← Mem0 persistent user memory
│       └── router.py               ← /api/v1/nl-search/*
│
├── review_queue/router.py          ← /api/v1/queue/* (Zone 1/2/3 decisions)
├── lifecycle/router.py             ← /api/v1/lifecycle/*
├── control_register/router.py      ← /api/v1/controls/*
├── evidence_tracker/router.py      ← /api/v1/evidence/*
├── standards_map/router.py         ← /api/v1/standards/*
├── strategic_risks/router.py       ← /api/v1/risks/*
├── gap_analysis/router.py          ← /api/v1/gap-analysis/*
├── sharepoint/router.py            ← /api/v1/sharepoint/* (file browser)
│
├── tests/
│   ├── conftest.py                 ← All fixtures, mock Graph responses, mock user
│   ├── test_graph_client.py
│   └── grc/                        ← CRUD + status calc tests for Tier 1
│
├── scripts/
│   ├── bulk_extract.py             ← Batch extraction with checkpoint/resume
│   └── cdi_triage.py               ← Pre-validate docs against CDI standard
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html                  ← Plus Jakarta Sans Google Fonts link
    ├── public/dragnet-logo.png     ← Navbar brand logo
    ├── .env.local                  ← Frontend secrets (gitignored)
    └── src/
        ├── main.jsx                ← Boot: verifySession() → render, or redirect to the ERP shell
        ├── App.jsx                 ← Shell + routing
        ├── auth/authBridge.js      ← verifySession / redirectToShell / logoutToShell
        ├── context/AuthContext.jsx ← Session identity, populated once at boot
        ├── api/grcApi.js           ← Axios client (withCredentials: true), all API calls
        ├── hooks/
        │   ├── useGrc.js           ← React Query hooks for every register + action
        │   ├── useCurrentUser.js   ← User identity from AuthContext (same shape as before)
        │   └── useCurrentUserRole.js ← isAdmin/isCompliance from the org_roles claim
        ├── services/aiDb.js        ← IndexedDB: chat sessions, message history
        ├── components/
        │   ├── layout/             ← Navbar.jsx (fixed top nav, replaces Sidebar + TopBar), Layout
        │   ├── shared/             ← StatusBadge, PersonPicker, Forms, LoadingState
        │   └── chat/               ← ChatPanel, ChatMessage, SourcesAccordion, ChatButton
        └── pages/
            ├── WorkHub/            ← Dashboard with summary cards and quick actions
            ├── DocumentRegister/
            ├── OrgRoles/           ← Read-only org_roles directory (Compliance/OrgOS Admin only)
            ├── ComplianceCalendar/
            ├── ContractRegister/
            ├── AIReviewQueue/      ← Zone 1/2/3 decision interface
            ├── DocumentLifecycle/
            ├── ControlRegister/
            ├── EvidenceTracker/
            ├── StandardsMap/       ← Traffic light grid per ISO/NDPA clause
            ├── StrategicRisks/
            ├── GapAnalysis/
            ├── Harmonisation/
            ├── Extractor/
            └── AssignmentOwnership/
```

---

## 5. All Modules Explained

### graph/ — Microsoft Graph API Layer

Every call to SharePoint goes through here. Three files:

- **`auth.py`** — Client credentials OAuth2 flow. Acquires a bearer token for the backend → Graph API. Token is cached in-process and refreshed 60 seconds before expiry. On 401 responses, `invalidate_token_cache()` forces a fresh token and retries once.

- **`client.py`** — All SharePoint CRUD:
  - `get_list_items(list_id, list_name, top=500)` — full fetch with `@odata.nextLink` pagination
  - `get_list_item(list_id, list_name, item_id)` — single item
  - `create_list_item(list_id, list_name, fields)` — create; returns item with auto-assigned ID
  - `update_list_item(list_id, list_name, item_id, fields)` — partial update (PATCH)
  - `soft_delete_list_item(list_id, list_name, item_id)` — sets `Status = "Withdrawn"`, never hard-deletes
  - `resolve_user(entra_oid)` — Entra OID → `{display_name, email, org_roles}` via Graph `/users/{oid}` in a single call, cached per process for 5 minutes
  - `list_users_with_org_roles()` — lists every user with an `org_roles` value set, via a Graph advanced query (`ConsistencyLevel: eventual`) on `onPremisesExtensionAttributes.extensionAttribute1` — backs the Org Roles directory page, no SharePoint involved
  - `upload_file_to_sharepoint(file_bytes, filename, folder)` — PUT to SharePoint drive
  - `download_file_from_sharepoint(web_url)` — downloads via `/shares/u!{base64url}`

- **`exceptions.py`** — Custom exception hierarchy: `GraphAuthError` (401), `GraphPermissionError` (403), `GraphNotFoundError` (404), `GraphRateLimitError` (429), `GraphServiceUnavailableError` (503), `SharePointListNotConfiguredError` (list ID = "placeholder").

---

### auth/ — Session Validation

Validates the Dragnet ERP's session — a JWT carried in the `erp_auth` HttpOnly cookie (cookie-first; `Authorization: Bearer` header remains a fallback for tooling/tests). OrgOS never issues, signs, or sets this cookie — only the ERP backend does; OrgOS independently validates it and reads it or clears it locally.

- **`validator.py`** — JWKS keys fetched from Microsoft and cached 2 hours. On `kid` not found, auto-refreshes once (handles key rotation). Validates `iss`, `aud`, `tid` claims. Roles come from the `org_roles` claim — a comma-separated, lowercase string (e.g. `"compliance,coo,exco"`) — not the old Entra App Roles array. Returns `CurrentUser(oid, name, email, tenant_id, roles, exp)`.
  - `get_current_user` — FastAPI `Depends()` used on all protected endpoints; reads the cookie first, header second.
  - `require_compliance_lead` / `require_admin` — role-gate dependencies; check for `"compliance"`/`"orgos-admin"` in `org_roles`. Every router uses these — no inline role-string duplication.
  - `SKIP_AUTH=true` in `.env` bypasses validation entirely (dev only — returns a hardcoded `orgos-admin` user, no cookie or Entra token needed).
- **`router.py`** — `/api/auth/session` (GET validates the cookie and returns `{name, email, roles, oid, expiresOn}`; DELETE clears it locally) and `/api/auth/revoke` (POST, called by the ERP when a user's roles change — shared-secret gated via `REVOKE_SECRET`, blocks that user's next session check once). Mounted **without** the `/api/v1` prefix — these are infra/session routes, not versioned business API. See `docs.local/orgos_notes.md` for the full auth migration writeup.

---

### org_roles/ — Org Roles Directory

`GET /api/v1/org-roles` (Compliance/OrgOS Admin only) — a read-only list of every user with an `org_roles` value set, read live from Entra ID via `graph.client.list_users_with_org_roles()`. No SharePoint list backs this; assignment happens exclusively in the Dragnet ERP admin panel.

---

### grc/ — Tier 1 GRC Registers

Three core registers (the Role Register was retired — see `docs.local/orgos_notes.md`). All follow the same pattern: schemas → service → router.

**Document Register** — Tracks every policy, procedure, SOP, form, and guideline. Document codes follow `DRG-[DEPT]-[TYPE]-[REF]-[YY]`. Status: Active / Under Review / Superseded / Withdrawn.

**Compliance Calendar** — Statutory, licensing, certification, and regulatory obligations with due dates and authorities. Status (Overdue / Due Soon / Upcoming / Completed) is calculated from `due_date` vs today — never stored.

**Contract Register** — Vendor contracts with start/end/review dates, counterparty, and contract type. `Expiring Soon` = end date within 60 days — calculated, not stored.

**Key service patterns:**
- Person fields: stored as `{Field}EntraId` (Entra OID text column) in SharePoint. On read, resolved to `PersonRef{oid, display_name, email}` via `resolve_user()`.
- Partial updates: only non-None fields from the request body are sent to SharePoint.
- Status calculations: pure functions of date fields, recalculated on every read.

---

### agents/extractor/ — Document Extraction Pipeline

Accepts a PDF, DOCX, or TXT file and produces structured GRC data.

**Pipeline:**
1. Extract text from file (pypdf for PDF, python-docx for DOCX)
2. POST to Ollama: `classify_document(text, folder_path)` → one of: Policy, JobDescription, Contract, Regulatory, Audit, Unclassified
3. POST to Ollama: `run_extraction(text, doc_type, doc_code)` → JSON array of items
4. For each item: `_assign_control_type()` (keyword rules override LLM) + `_suggest_evidence_type()`
5. Validate: COMPLETE (all required fields) vs DEFICIENT (missing fields)
6. If `write_to_sharepoint=True`: COMPLETE items written to AI Review Queue (Zone 1)

**Item types by document:**
- **Policy/Contract** → `ExtractionItem`: risk statement, control statement, control type, ISO clause, evidence type and description
- **Job Description** → `OrphanItem`: role title, department, responsibility, orphan classification
- **Regulatory/Statutory** → `RegulatoryItem`: obligation, authority, deadline, recurrence
- **Audit report** → `AuditItem`: finding type, severity, gap type, remediation flag

**Evidence taxonomy** — 16 fixed codes (DRG-QI-REF-EVTX-01-26). No free-text permitted:

| Code | Meaning | Code | Meaning |
|---|---|---|---|
| LOG | System log export | MTG | Meeting/governance record |
| CFG | Configuration evidence | REV | Review record |
| APR | Signed approval record | CHK | Checklist completion |
| FRM | Completed form/record | CNT | Contract/agreement |
| TRN | Training record | INV | Inventory/register extract |
| ACK | Policy acknowledgement | CHG | Change record |
| TST | Test/drill/verification | INC | Incident record |
| CRT | Certificate/external attestation | RPT | Report/assessment |

---

### agents/classifier/ — Harmonisation & Dedup

Runs after extraction. Two jobs (a third, role-variant dedup against the now-retired Role Register, was removed):
1. **Near-duplicate control detection** — compares extracted `ControlStatement` values against each other and the confirmed Control Register, flags pairs above a similarity threshold.
2. **Conflict detection** — identifies controls from different documents that define contradictory requirements for the same obligation.

Writes decisions to Zone 2 (orphan/conflict handling) and Zone 3 (harmonisation queue).

---

### agents/policy_drafter/ — AI Policy Generation

Generates CDI-compliant policy documents and uploads them to SharePoint.

1. Generates a document code (`DRG-[DEPT]-[TYPE]-[REF]-[YY]`)
2. Calls LLM gateway to draft CDI-structured policy text
3. `docx_builder.py` creates a formatted `.docx` using python-docx
4. Uploads to SharePoint `<starting folder>/Drafts/` in the compliance library
5. Creates a Document Lifecycle entry pointing to the file

---

### agents/gap_analyzer/ — Gap Analysis Agent

Reads the Control Register and Evidence Tracker. Builds a coverage map of which ISO 27001/9001/NDPA clauses have controls and accepted evidence. For each uncovered or partially covered clause, writes a Gap Analysis item with:
- Severity: Critical (no control) / Major (no evidence) / Minor (evidence pending)
- Proposed remediation: full JSON package with suggested controls, evidence types, a freely-proposed owner role name (no fixed pick-list — the Role Register that used to seed one was retired), and timeline

---

### agents/cdi_checker/ — CDI Compliance Checker

Validates documents against Dragnet's Controlled Document Interface standard. Checks: document code format, required metadata fields, version numbering, effective/review date logic, mandatory section presence.

---

### review_queue/ — AI Review Queue

Human-in-the-loop staging. Three logical zones with different decision workflows:

**Zone 1 — Extraction (controls from policies/contracts):**
- `POST /api/v1/queue/{id}/accept-control` — Zone 1 cascade (atomic):
  1. Create Control Register item (status = Active)
  2. Create Evidence Tracker item (status = Pending, linked to new control)
  3. Create Audit Log entry (who, when, what)
  4. Update Queue item (ReviewStatus = Accepted)
- `POST /api/v1/queue/{id}/edit-accept` — edit fields, then same cascade
- `POST /api/v1/queue/{id}/reject` — logs to Audit Log with rationale
- `POST /api/v1/queue/{id}/route-to-owner` — assign item to a role owner for input

**Zone 2 — Orphans (from JD processing):**
Create new document, add to existing policy, mark intentional, or route to department head.

**Zone 3 — Harmonisation (duplicate controls from Classifier):**
Merge controls, keep separate, or rename and standardise.

---

### lifecycle/ — Document Lifecycle

Tracks documents from creation trigger through stages to approval. Created by: AI Policy Drafter, Compliance Lead manually, Gap Analysis remediation, CDI Fix, or Scheduled Review. Stages: Review → Sensitisation → Approval.

---

### control_register/ — Confirmed Controls

Authoritative list of active controls. Populated exclusively via the Zone 1 accept cascade. Each control links to a source document, owner role, ISO/NDPA clauses, and evidence items (joined on read).

---

### evidence_tracker/ — Evidence Lifecycle

One evidence item per control. Statuses: Pending → Submitted → Accepted / Rejected. Overdue is calculated (due_date < today AND status = Pending or Submitted).

- Owner submits: `PATCH /api/v1/evidence/{id}/submit` — provides evidence link + notes
- Compliance Lead verifies: `PATCH /api/v1/evidence/{id}/verify` — Accepted or Rejected

---

### standards_map/ — Traffic Lights

Live clause coverage across ISO 27001, ISO 9001, and NDPA. No data stored — recalculated on every request from Control Register + Evidence Tracker.

| Colour | Condition |
|---|---|
| 🟢 Green | All controls have accepted evidence, owners assigned, nothing overdue |
| 🟡 Amber | Evidence due soon (≤7 days), submitted but not verified, or new control with no evidence |
| 🔴 Red | Evidence overdue, no controls for clause, owner unassigned, or evidence rejected |

---

### strategic_risks/ — Risk Register

Manually curated by ExCo. Three entry paths: direct ExCo assessment, accepted gap (gap finding escalated to risk), or incident escalation. Risk score = likelihood (1–3) × impact (1–4). Low: 1–3, Medium: 4–6, High: 7–9, Critical: 10–12.

---

### gap_analysis/ — Gap Findings

Gaps from two sources: AI Gap Analyzer agent, and AuditItem entries from the Review Queue. Each gap has a severity, target date (Critical: 30d / Major: 60d / Minor: 90d), and a full remediation package JSON. Status progression: Open → In progress → Accepted risk / Closed. `POST /api/v1/gap-analysis/{id}/accept-risk` escalates to the Strategic Risk Register.

---

### sharepoint/ — File Browser

Browse the SharePoint Compliance document library (the configured starting folder) and trigger extraction on any file by its drive item ID.

---

## 6. Core Data Flows

### Document → Control Register (Full Pipeline)

```
1. Upload file → POST /api/v1/agents/extract/file
   OR click file in SharePoint browser → POST /api/v1/sharepoint/extract/{item_id}

2. AI Pipeline:
   a. Extract text (pypdf / python-docx)
   b. Ollama classifies document type
   c. Ollama extracts {risk, control, evidence} triplets as JSON
   d. Keyword rules assign control_type and suggest evidence_type
   e. Items marked COMPLETE or DEFICIENT
   f. If write_to_sharepoint=True: COMPLETE items → AI Review Queue (Zone 1)

3. Reviewer opens AI Review Queue → Zone 1

4. "Accept Control" → Zone 1 CASCADE (atomic):
   → Control Register item created (Active)
   → Evidence Tracker item created (Pending, linked to control)
   → Audit Log entry created
   → Queue item updated (Accepted)

5. Evidence owner submits link → status: Submitted
6. Compliance Lead verifies → status: Accepted
7. Standards Map next request → Green for linked ISO clause
```

### Gap Analysis → Risk Escalation

```
1. POST /api/v1/agents/gap-analysis/run (Compliance Lead)
   → Reads Control Register + Evidence Tracker
   → Compares against full standard clause list
   → Writes Gap Analysis items (Critical/Major/Minor + remediation package)

2a. Remediating:
    PATCH /api/v1/gap-analysis/{id}/status → "In progress"
    POST /api/v1/agents/draft-document → AI drafts remediation policy
    → Document Lifecycle entry → Review → Approval → Gap closes

2b. Accepting as risk:
    POST /api/v1/gap-analysis/{id}/accept-risk
    → Strategic Risk Register item created (linked to gap)
    PATCH status → "Accepted risk"
```

---

## 7. The AI/LLM System

OrgOS uses two separate AI systems for different tasks.

### Gateway (GPT-4o-mini via Azure) — All conversational and reasoning tasks

The GPU gateway at `gpu.idhub.ng` sits in front of Azure OpenAI. OrgOS calls its `/chat` endpoint for all reasoning work.

**`llm_chat(messages)`** — used by the NL Search chatbot. Sends a pre-built `[system, history..., user]` messages list. Supports full conversation context.

**`llm_generate(prompt)`** — used by extraction, classification, policy drafting, and gap analysis. Wraps the prompt in a `[system, user]` pair and sends to `/chat`. Both functions call the same gateway `/chat` endpoint — the difference is only in how the input is structured.

**Both route through `agents/llm_client.py`** with this priority:
```
1. CHAT_API_URL set → gateway /chat (GPT-4o-mini)    ← always used in production
2. LLM_PROVIDER=runpod → RunPod direct               ← only if gateway not configured
3. Default → Ollama local                             ← fallback
```

RunPod is never used when `CHAT_API_URL` is set — the gateway handles all routing internally.

### Ollama (local, llama3) — Document extraction only

Only used for the extraction pipeline: classify document type and extract GRC triplets from uploaded documents. Runs locally at `http://localhost:11434`. Not used for the chatbot or any conversational feature.

**Extraction calls use low temperature (0.1)** to minimise hallucination. After the LLM produces extraction results, keyword rules in `_assign_control_type()` and `_suggest_evidence_type()` override the LLM's taxonomy assignments — keyword rules are more consistent for fixed taxonomies.

### BGE-M3 Embeddings

Used by the NL Search chatbot to embed controls and procedural steps into ChromaDB. Called via `gpu.idhub.ng/embed`. Produces 1024-dimensional vectors. ChromaDB collections: `controls_v1` and `procedures_v1`.

---

## 8. The NL Search Chatbot

The floating chat button (bottom-right of every page) provides plain-English Q&A over live GRC data. It uses RAG (Retrieval-Augmented Generation) — retrieves real data from SharePoint and ChromaDB first, then the LLM writes a grounded answer from that data. It cannot invent policies, controls, or procedures.

### How a Question Flows

```
User: "What is the MFA policy?"
             │
             ▼
    Is it a greeting or simple follow-up? (hi / ok / thanks / can you explain...)
    Yes → LLM responds from conversation history only (no search)
    No  ↓
             │
    classify_intent() → "compliance" | "procedural" | "both" | "conversational"
             │
    ─── compliance path ────────────────────────────────────────
             │
    entity_extractor() pulls from the question:
      { iso_clause: "A.5.17", keywords: ["MFA"], status_filter: null }
             │
    compliance_search.py
    1. Fetch full Control Register from SharePoint (no OData filter — Python filter)
    2. Fetch full Evidence Tracker → join evidence to each control
    3. Fetch Gap Analysis, Obligations, Risks, Documents as relevant
    4. Python-filter by ISO clause, keywords, status
    5. ChromaDB fallback (controls_v1, distance ≤ 0.42) if SP returns nothing
    6. Resolve control owners via Graph API
             │
    response_generator.py
    Builds context block:
      [CONTROL: DRG-ISMS-POL-ACP-01-26]
      Rule: Privileged accounts must use MFA for all remote access...
      ISO clause: A.5.17 | Type: Preventive | Owner: IT Security Lead
      Evidence status: 🔴 No evidence on file
             │
    Adds last 3 conversation turns (history trimmed to 600 chars per assistant turn)
    Adds Mem0 persistent memory facts (cross-session context)
    → LLM gateway /chat (GPT-4o-mini) → max_tokens=500 → grounded answer
             │
    NLSearchResponse { answer, mode, sources, compliance_data }
             │
    ChatMessage renders: mode badge, markdown, sources accordion (evidence links)
    Saved to IndexedDB → survives page refresh
```

### Conversation Continuity

The last 3 user/assistant turn pairs are sent with every request. This allows:
- "What is the MFA policy?" → answer about MFA controls
- "can you explain that?" → LLM uses the prior answer in history, elaborates (no new search)
- "hi" → warm greeting, no SharePoint query at all

Mem0 persistent memory stores facts across sessions (e.g. "user previously asked about A.5.17 gap"). On return visits, the LLM can reference prior conversations naturally.

### Search Strategy

SharePoint lists are small (<500 items). All filtering is done in Python after a full fetch — no OData `$filter` is used, because most SharePoint list columns are unindexed and OData filters on them return HTTP 400. ChromaDB is used as a semantic fallback when SharePoint returns no matches.

**Never-empty guarantee:** If Python filtering produces zero results, the original full list is returned. The LLM always receives data, never an empty context from a filter overreach.

### Intent Routing

| Intent | Triggered by | Action |
|---|---|---|
| `conversational` | Greetings, follow-ups, vague questions | LLM uses history only — no search |
| `compliance` | Questions about policies, controls, ISO clauses, gaps, risks | `compliance_search.py` |
| `procedural` | "How do I...", step-by-step process questions | `procedural_search.py` + ChromaDB |
| `both` | Questions spanning policies AND procedures | Both pipelines in parallel |

### Seeding the Index (Dev/Demo)

```bash
# Seed ChromaDB with test data (requires Compliance Lead or Admin token)
curl -X POST http://localhost:8000/api/v1/nl-search/index/seed \
  -H "Authorization: Bearer YOUR_TOKEN"
# Inserts 7 controls + 6 procedural steps covering MFA, access, leave, incidents, etc.
```

### Full Index Rebuild (Production)

```bash
curl -X POST http://localhost:8000/api/v1/nl-search/index/rebuild \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm": true}'
# Reads all active controls + procedural steps from SharePoint, embeds everything
```

Incremental indexing happens automatically — when a Zone 1 control is accepted, the cascade immediately indexes it into ChromaDB. A full rebuild is only needed after the initial SharePoint list population.

---

## 9. Authentication & Security

OrgOS is a **Tier-1 standalone module** of the Dragnet ERP. It has no login
page, no MSAL, and no app registration of its own — the ERP is the sole
authority for authentication and role assignment across every Dragnet
module. Full write-up: `docs.local/orgos_notes.md`.

### Session flow (ERP shell → OrgOS)

1. User is not authenticated → OrgOS's frontend (`main.jsx`) calls `GET /api/auth/session` on its own backend; that fails, so it redirects to the ERP shell (`VITE_ERP_URL`) with `?redirect=<current-url>`.
2. The ERP shell authenticates the user (its own concern entirely) and sets an `erp_auth` HttpOnly cookie on `.dragnet.ng`, then redirects back — no token ever appears in the URL.
3. Back on OrgOS, `GET /api/auth/session` now succeeds — the frontend renders with `{name, email, roles, oid}` from that response.
4. Every subsequent API call sends `credentials: "include"` (axios `withCredentials: true`) — the cookie travels automatically. There is no `Authorization` header logic anywhere in the frontend.
5. OrgOS's own backend (`auth/validator.py`) independently validates the JWT inside that cookie: fetches Microsoft JWKS (cached 2h), decodes RS256, validates `iss`/`aud`/`tid`. Cookie is checked first; an `Authorization: Bearer` header remains a fallback for tooling/tests/direct API clients.
6. Returns `CurrentUser(oid, name, email, tenant_id, roles, exp)` — used in every protected route via `Depends(get_current_user)`.

**OrgOS's backend never constructs, signs, or sets the `erp_auth` cookie** — only the ERP backend does. OrgOS only ever reads it (`GET /api/auth/session`) or clears it locally (`DELETE /api/auth/session`, and defensively on validation failure).

### Sign out

`logoutToShell()` (`frontend/src/auth/authBridge.js`) — clears the session locally (`DELETE /api/auth/session`) then redirects to `${VITE_ERP_URL}/logout`, ending the session across every other Dragnet module too.

### Session revocation

`POST /api/auth/revoke` — called by the ERP when a user's `org_roles` change. Body `{email, secret}`, `secret` must match `REVOKE_SECRET`. Adds the user to an in-memory blocklist that blocks their *next* session check once (2h auto-expiry) — the cookie itself isn't invalidated, only the following check catches it.

### Backend → Graph API (Client Credentials) — unchanged

1. Backend acquires its own token using client credentials grant (`client_id` + `client_secret` — now the **shared Dragnet ERP app registration's** values, see §13).
2. Cached in-process, refreshed 60s before expiry.
3. On 401: token cache invalidated + one retry.
4. Completely separate from the user's session — this flow never touches the `erp_auth` cookie.

### org_roles (replaces the old Entra App Roles)

Roles come from the `org_roles` JWT claim — a comma-separated, lowercase string (e.g. `"compliance,coo,marketing"`) — assigned exclusively via the Dragnet ERP admin panel. OrgOS only acts on two of them; everything else is display-only (see the Org Roles directory, §5).

| org_role | Access |
|---|---|
| `orgos-admin` | Full access including agent triggers, verification, all admin operations |
| `compliance` | Agent triggers (extraction, gap analysis, classification) + evidence verification |
| (any other value) | No special access in OrgOS — visible in the Org Roles directory only |
| (none of the above) | Read/write registers, submit evidence, use chatbot |

**OrgOS never assigns `org_roles`.** There is no write path anywhere in the codebase for it — role assignment is exclusively an ERP admin panel action.

### Development Bypass

`SKIP_AUTH=true` in `.env` (with `ENVIRONMENT=development`) bypasses JWT validation on **both** `get_current_user()` and `GET /api/auth/session` — the backend returns a fixed `CurrentUser(oid="dev-bypass-oid", roles=["orgos-admin"])` / session response for every request. This means the entire app (backend *and* frontend) can boot and be fully clickable with no real Entra token, ERP instance, or cookie at all. **Never set in production.**

---

## 10. Setup — Backend

### Prerequisites

```bash
# Python 3.11+ required
python3 --version

# Ollama — only needed for the extraction pipeline
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3
ollama serve                   # runs on http://localhost:11434
```

### Install and Run

```bash
# 1. Create virtual environment
python3 -m venv myenv
source myenv/bin/activate      # Windows: myenv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Environment file
cp .env.example .env
# Edit .env — fill in TENANT_ID, CLIENT_ID, CLIENT_SECRET (the SHARED Dragnet
# ERP app registration — get these from the ERP team, not a new Azure app
# registration), SHAREPOINT_SITE_ID, and REVOKE_SECRET (also from the ERP team)
# Set CHAT_API_URL, EMBED_API_URL, INFERENCE_API_KEY for the LLM gateway
# Leave List IDs as "placeholder" until SharePoint lists are provisioned
# For pure local dev with no real ERP: set SKIP_AUTH=true — see §9

# 4. Run (development)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# API docs:  http://localhost:8000/docs
# ReDoc:     http://localhost:8000/redoc
# Health:    http://localhost:8000/health
# Graph:     http://localhost:8000/api/v1/health/graph
```

---

## 11. Setup — Frontend

### Prerequisites

```bash
node --version    # Node 18+ required
```

### Install and Run

```bash
cd frontend

npm install

cp .env.local.example .env.local
# Edit .env.local — fill in VITE_ERP_URL (the Dragnet ERP shell's URL,
# from the ERP team). No Azure/MSAL values needed — OrgOS never calls
# Entra ID directly from the frontend.

npm run dev       # development: http://localhost:3000 (see frontend/vite.config.js)

npm run build     # production build → frontend/dist/
```

---

## 12. Environment Variables

### Backend `.env`

```bash
# ── Microsoft Entra ID — the SHARED Dragnet ERP app registration ──
# OrgOS has no login of its own; get these three from the ERP team,
# not a dedicated OrgOS app registration.
TENANT_ID=                              # Azure AD directory (tenant) ID
CLIENT_ID=                              # Shared ERP app registration client ID
CLIENT_SECRET=                          # Shared ERP app registration client secret

# Shared secret the ERP calls POST /api/auth/revoke with when a user's
# org_roles change. Get from the ERP team. Empty = revocation disabled.
REVOKE_SECRET=

# ── SharePoint ───────────────────────────────────────────────────
SHAREPOINT_SITE_ID=                     # Site ID from Graph API (see section 14)
SHAREPOINT_SITE_URL=https://dragnetnigeria.sharepoint.com/sites/orgos
COMPLIANCE_SITE_URL=https://dragnetnigeria.sharepoint.com/sites/everybody
COMPLIANCE_LIBRARY_NAME=ORGOS LIBRARY
COMPLIANCE_STARTING_FOLDER=Policies, Procedures, Manuals, Guidelines, Frameworks, Handbook, SOP

# ── SharePoint List IDs (fill after creating lists in SharePoint) ─
# No ROLE_REGISTER_LIST_ID — the Role Register was retired entirely,
# see docs.local/orgos_notes.md. Do not re-add it.
DOCUMENT_REGISTER_LIST_ID=placeholder
COMPLIANCE_CALENDAR_LIST_ID=placeholder
CONTRACT_REGISTER_LIST_ID=placeholder
AI_REVIEW_QUEUE_LIST_ID=placeholder
DOCUMENT_LIFECYCLE_LIST_ID=placeholder
CONTROL_REGISTER_LIST_ID=placeholder
EVIDENCE_TRACKER_LIST_ID=placeholder
AUDIT_LOG_LIST_ID=placeholder
STRATEGIC_RISK_REGISTER_LIST_ID=placeholder
GAP_ANALYSIS_LIST_ID=placeholder
PROCEDURAL_STEPS_LIST_ID=placeholder

# ── LLM Gateway (gpu.idhub.ng) ───────────────────────────────────
CHAT_API_URL=https://gpu.idhub.ng/chat  # → GPT-4o-mini (all reasoning tasks)
EMBED_API_URL=https://gpu.idhub.ng/embed # → BGE-M3 embeddings (ChromaDB)
INFERENCE_API_KEY=                       # Bearer token — same key for both endpoints

# ── Ollama (extraction pipeline only) ────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120

# ── ChromaDB (NL Search vector store) ────────────────────────────
CHROMA_PERSIST_DIR=./chroma_db

# ── Application ──────────────────────────────────────────────────
ENVIRONMENT=development
ALLOWED_ORIGINS=http://localhost:3000   # comma-separated in production — must include
                                         # the OrgOS frontend's real origin for the
                                         # erp_auth cookie's CORS to work
APP_PORT=8000
LOG_LEVEL=DEBUG
SKIP_AUTH=false                         # true only for local dev with no real ERP — see §9

# ── Graph Search (NL Search optional enhancement) ────────────────
GRAPH_SEARCH_REGION=EUR                 # NAM | EUR | APC — match your tenant region
```

### Frontend `.env.local`

```bash
VITE_API_BASE_URL=http://localhost:8000

# Dragnet ERP shell URL — where unauthenticated visitors are redirected to
# sign in, and where sign-out sends them back to. Get the real value from
# the ERP team for staging/production.
VITE_ERP_URL=http://localhost:5173
```

No `VITE_AZURE_*` variables — OrgOS's frontend never calls Entra ID or MSAL directly.

---

## 13. Azure App Registration

**There is no OrgOS-specific app registration to create.** `TENANT_ID` / `CLIENT_ID` / `CLIENT_SECRET` above are the **shared Dragnet ERP app registration's** values — request them from the ERP team. What to confirm with them:

1. The three values themselves (`TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`).
2. `REVOKE_SECRET` for `POST /api/auth/revoke`.
3. That the shared app registration retains the Graph API application permissions OrgOS needs:
   - `Sites.ReadWrite.All` (SharePoint list/file access)
   - `User.Read.All` (person resolution + the Org Roles directory)
4. OrgOS registered in the ERP admin panel as a Tier-1 module (`*.dragnet.ng` subdomain) — required for the redirect flow's origin checks to pass in production.
5. The real `VITE_ERP_URL` for staging/production.

Role assignment (`org_roles`, e.g. `orgos-admin`/`compliance`) happens exclusively in the ERP admin panel — there is nothing to configure on OrgOS's side for it. See [§9](#9-authentication--security) and `docs.local/orgos_notes.md`.

---

## 14. SharePoint Setup

### Getting the Site ID

```bash
# After backend is running with valid Entra credentials:
curl "https://graph.microsoft.com/v1.0/sites/dragnetnigeria.sharepoint.com:/sites/orgos" \
  -H "Authorization: Bearer $(python3 -c \
    'import asyncio; from graph.auth import get_graph_access_token; \
     print(asyncio.run(get_graph_access_token()))')"
# Copy the "id" field → SHAREPOINT_SITE_ID in .env
```

Or use [Graph Explorer](https://developer.microsoft.com/graph/graph-explorer): `GET /v1.0/sites/dragnetnigeria.sharepoint.com:/sites/orgos`

### Provisioning SharePoint Lists

Each list must be created manually in the OrgOS SharePoint site with the correct column names (PascalCase). After creation, copy each list's GUID into the corresponding `*_LIST_ID` variable in `.env`.

Column naming convention: all columns use PascalCase. Person ownership fields store the Entra OID as a text column named `{Field}EntraId` (e.g. `OwnerEntraId`). This is the only column OrgOS writes to for person references.

Reference `grc/constants.py` for the exact column names expected by each register.

### Getting a List ID

```bash
curl "https://graph.microsoft.com/v1.0/sites/{SITE_ID}/lists" \
  -H "Authorization: Bearer YOUR_TOKEN"
# Find your list by name → copy its "id" → paste into .env
```

---

## 15. Running Tests

Tests use pytest with async support. All Graph API calls are mocked with `respx` — no real SharePoint calls in the test suite.

```bash
# All tests
pytest -v

# Specific register
pytest tests/grc/test_document_register.py -v
pytest tests/grc/test_compliance_calendar.py -v
pytest tests/grc/test_contract_register.py -v

# Graph client (token caching, error handling)
pytest tests/test_graph_client.py -v

# With coverage
pytest --cov=grc --cov=graph --cov-report=term-missing

# Single test
pytest tests/test_graph_client.py::test_token_cache_hit -v
```

**Test coverage:** Graph API token caching and error types, the three remaining Tier 1 registers (CRUD, status calculation, person resolution, schema validation). Agent modules, review queue, lifecycle, and Tier 2+ modules have no automated tests yet.

---

## 16. Scripts & Utilities

### `scripts/bulk_extract.py` — Batch Extraction

Traverses the entire configured starting folder in the compliance library, extracts all PDF/DOCX/TXT files, writes COMPLETE results to the AI Review Queue. Supports checkpoint/resume — safe to interrupt.

```bash
python scripts/bulk_extract.py --dry-run              # Preview files, no extraction
python scripts/bulk_extract.py --folder "Policies"    # Single subfolder only
python scripts/bulk_extract.py                        # All folders
python scripts/bulk_extract.py --reset                # Clear checkpoint, start fresh
```

### `scripts/cdi_triage.py` — CDI Pre-Validation

Runs CDI compliance checks on documents before they enter the extraction pipeline. Validates document codes, required metadata, and mandatory sections.

---

## 17. Key Architectural Rules

These rules apply to every module and must never be broken.

**No relational database.** All data is in SharePoint Lists. No SQLite, no Postgres, no Redis. Cross-list aggregation happens in Python after fetching.

**No hard deletes.** Every `DELETE` endpoint calls `soft_delete_list_item()`, which sets `Status = "Withdrawn"`. Audit trail is always preserved. No exceptions.

**Async everywhere.** All I/O is `async/await`. Use `httpx.AsyncClient`. Never `requests`, never `aiohttp`, never synchronous file reads in hot paths.

**Settings from `config.py` only.** All modules do `from config import settings`. Never `os.environ.get(...)` directly. `get_settings()` is `@lru_cache` — `.env` is read once per process.

**Pydantic v2 API only.** Use `model_validate()` not `parse_obj()`. Use `model_dump()` not `.dict()`. Use `@field_validator` not `@validator`. Use `model_config = SettingsConfigDict(...)` not inner class `Config`.

**Status is calculated, never stored.** Obligation Overdue/Due Soon, Contract Expiring Soon, Evidence Overdue, and all Standards Map traffic lights are pure functions of date fields, recalculated on every read. No background jobs or stored status for these.

**No OData `$filter` on SharePoint lists.** Most SharePoint list columns are not indexed. OData filters on them return HTTP 400. All filtering is done in Python after a full fetch (`top=500`).

**URLs never pass through the LLM.** Evidence links and SharePoint file URLs are returned in the `sources[]` array as structured data. They are never included in the LLM context — the LLM truncates or misformats long URLs. The frontend renders links from `sources`, not from the LLM response text.

**Document codes follow the format `DRG-[DEPT]-[TYPE]-[REF]-[YY]`.** Role JD references follow `DRG-JD-[DEPT]-[CODE]-[NN]`. Evidence type codes are the 16 fixed codes from DRG-QI-REF-EVTX-01-26. No free-text alternatives.

**All Graph API calls go through `graph/client.py`.** Never call `httpx` directly in routers or services for Graph operations. The client handles token acquisition, retry on 401, and exception mapping.

**OrgOS never handles login, and never assigns `org_roles`.** The Dragnet ERP is the sole authority for both. OrgOS's backend only ever *reads* or *clears* the `erp_auth` cookie — never constructs or signs it. If a task seems to call for a login screen, an app registration, or a role-assignment UI inside OrgOS, that's a sign the task is misunderstood — those belong to the ERP, not here.

**No SharePoint-backed Role Register.** It was retired intentionally (see `docs.local/orgos_notes.md`) — do not re-introduce `ROLE_REGISTER_LIST_ID` or a Role Register list/page. Anything that needs to know "who has what role" reads `org_roles` live from Entra ID via `graph.client.resolve_user()` / `list_users_with_org_roles()`, never from SharePoint.
