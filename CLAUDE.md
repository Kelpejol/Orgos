# CLAUDE.md — OrgOS: Complete Project Reference
**Dragnet Solutions Limited | GRC Orchestration Module | DRG-AUTO-BRIEF-GRC-01-26**

---

## Table of Contents

1. [What Is OrgOS](#1-what-is-orgos)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Repository Layout](#4-repository-layout)
5. [Backend: Module-by-Module Reference](#5-backend-module-by-module-reference)
   - 5.1 [config.py — Settings & Environment](#51-configpy--settings--environment)
   - 5.2 [main.py — FastAPI Entry Point](#52-mainpy--fastapi-entry-point)
   - 5.3 [graph/ — Microsoft Graph API Layer](#53-graph--microsoft-graph-api-layer)
   - 5.4 [auth/ — Token Validation](#54-auth--token-validation)
   - 5.5 [grc/ — Tier 1 GRC Registers](#55-grc--tier-1-grc-registers)
   - 5.6 [agents/extractor/ — Document Extraction](#56-agentsextractor--document-extraction)
   - 5.7 [agents/classifier/ — Harmonisation & Dedup](#57-agentsclassifier--harmonisation--dedup)
   - 5.8 [agents/policy_drafter/ — AI Policy Generation](#58-agentspolicy_drafter--ai-policy-generation)
   - 5.9 [agents/gap_analyzer/ — Gap Analysis Agent](#59-agentsgap_analyzer--gap-analysis-agent)
   - 5.10 [agents/cdi_checker/ — CDI Compliance Checker](#510-agentscdi_checker--cdi-compliance-checker)
   - 5.11 [review_queue/ — AI Review Queue](#511-review_queue--ai-review-queue)
   - 5.12 [lifecycle/ — Document Lifecycle](#512-lifecycle--document-lifecycle)
   - 5.13 [control_register/ — Confirmed Controls](#513-control_register--confirmed-controls)
   - 5.14 [evidence_tracker/ — Evidence Collection](#514-evidence_tracker--evidence-collection)
   - 5.15 [standards_map/ — Standards Traffic Lights](#515-standards_map--standards-traffic-lights)
   - 5.16 [strategic_risks/ — Strategic Risk Register](#516-strategic_risks--strategic-risk-register)
   - 5.17 [gap_analysis/ — Gap Findings](#517-gap_analysis--gap-findings)
   - 5.18 [sharepoint/ — File Browser & Extraction](#518-sharepoint--file-browser--extraction)
6. [Frontend: Module-by-Module Reference](#6-frontend-module-by-module-reference)
   - 6.1 [Entry Point & MSAL Setup](#61-entry-point--msal-setup)
   - 6.2 [Auth Configuration](#62-auth-configuration)
   - 6.3 [API Client (grcApi.js)](#63-api-client-grcapijs)
   - 6.4 [React Query Hooks](#64-react-query-hooks)
   - 6.5 [Layout Components](#65-layout-components)
   - 6.6 [Shared Components](#66-shared-components)
   - 6.7 [Pages](#67-pages)
7. [Data Models & SharePoint Lists](#7-data-models--sharepoint-lists)
8. [Core Data Flows](#8-core-data-flows)
9. [API Endpoint Reference](#9-api-endpoint-reference)
10. [AI & LLM Integration](#10-ai--llm-integration)
11. [Authentication & Security](#11-authentication--security)
12. [Configuration & Environment Variables](#12-configuration--environment-variables)
13. [Testing](#13-testing)
14. [Scripts & Utilities](#14-scripts--utilities)
15. [Development Setup](#15-development-setup)
16. [Key Architectural Decisions & Invariants](#16-key-architectural-decisions--invariants)
17. [Known Patterns & Conventions](#17-known-patterns--conventions)
18. [Current State & What's Built](#18-current-state--whats-built)

---

## 1. What Is OrgOS

OrgOS is Dragnet Solutions Limited's internal **GRC (Governance, Risk, and Compliance) Orchestration Platform**. It is a full-stack web application that automates and centralises Dragnet's compliance management lifecycle — from document ingestion through AI-powered control extraction, human review, evidence tracking, and standards gap analysis.

**Core mission:** Replace manual spreadsheet-based GRC tracking with a live, AI-assisted system that keeps Dragnet's control register, evidence trail, policy library, and risk register in sync with ISO 9001, ISO 27001, and NDPA requirements.

**Key capabilities:**

| Capability | What it does |
|---|---|
| Document Register | Track all policy/procedure documents with version, owner, status |
| Role Register | Maintain role-to-control ownership across departments |
| Compliance Calendar | Track statutory, licensing, regulatory deadlines per authority |
| Contract Register | Monitor vendor contracts, expiry, renewal obligations |
| AI Extractor | Feed a PDF/DOCX, receive structured {risk, control, evidence} triplets |
| AI Review Queue | Human-in-the-loop staging area: accept, reject, or edit extracted controls |
| Control Register | Confirmed, active controls linked to roles and evidence requirements |
| Evidence Tracker | Evidence item lifecycle: Pending → Submitted → Accepted/Rejected |
| Document Lifecycle | Draft creation, review stages, sensitisation, approval |
| Standards Map | Live ISO 27001/9001/NDPA clause coverage with traffic lights |
| Gap Analysis | AI-identified and audit-sourced gaps with remediation packages |
| Strategic Risk Register | ExCo-curated risk register with likelihood × impact scoring |
| Harmonisation | Detect duplicate or variant controls across documents |
| Policy Drafter | AI-generated policy documents conforming to CDI standards |

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (React SPA)                       │
│  MSAL auth → acquires Entra ID token → attaches to every request │
└───────────────────────────┬────────────────────────────────────--┘
                            │ HTTPS / Bearer token
┌───────────────────────────▼─────────────────────────────────────┐
│                    FastAPI Backend (Python)                       │
│  • Validates Entra ID JWT (RS256)                                │
│  • Business logic + data mapping                                 │
│  • Calls Microsoft Graph API (client credentials)                │
│  • Calls Ollama (local, no auth, LLM inference)                  │
└────────┬─────────────────────────────────┬───────────────────────┘
         │                                 │
         ▼                                 ▼
┌────────────────────┐          ┌──────────────────────┐
│  Microsoft Graph   │          │  Ollama (local LLM)  │
│  API (v1.0)        │          │  http://localhost:    │
│  SharePoint Lists  │          │  11434               │
│  Users / Files     │          │  llama3 / mistral    │
└────────────────────┘          └──────────────────────┘
         │
         ▼
┌────────────────────┐
│  SharePoint Online │
│  dragnetnigeria    │
│  .sharepoint.com   │
│  /sites/orgos      │
│  /sites/compliance │
└────────────────────┘
```

**There is no relational database.** All application data lives in SharePoint Lists, accessed via the Microsoft Graph API. The backend is stateless; SharePoint is the single source of truth for all persistent state.

---

## 3. Technology Stack

### Backend

| Component | Library / Version | Notes |
|---|---|---|
| Web framework | FastAPI ≥ 0.115.0 | lifespan= pattern, async throughout |
| ASGI server | uvicorn[standard] ≥ 0.30.0 | watchfiles for reload, httptools for perf |
| HTTP client | httpx ≥ 0.27.0 | ALL Graph API calls — never requests or aiohttp |
| Data validation | Pydantic v2 ≥ 2.7.0 | model_validate(), model_dump(), @field_validator |
| Settings | pydantic-settings ≥ 2.3.0 | BaseSettings + .env file |
| Env vars | python-dotenv ≥ 1.0.0 | Underlying .env loader |
| JWT validation | python-jose[cryptography] ≥ 3.3.0 | RS256, Entra ID tokens |
| Crypto | cryptography ≥ 42.0.0 | RSA key ops for python-jose |
| PDF extraction | pypdf ≥ 4.0.0 | Text extraction from uploaded PDFs |
| DOCX extraction | python-docx ≥ 1.1.0 | Text + DOCX generation |
| File uploads | python-multipart ≥ 0.0.9 | FastAPI multipart/form-data |
| Testing | pytest ≥ 8.0.0 + pytest-asyncio ≥ 0.23.0 | asyncio_mode = auto |
| HTTP mocking | respx ≥ 0.20.0 + pytest-httpx ≥ 0.30.0 | Mock all Graph API calls in tests |
| Python version | CPython 3.14 (based on __pycache__ bytecode) | |

### Frontend

| Component | Library / Version | Notes |
|---|---|---|
| Framework | React 18.3.1 | Hooks throughout, no class components |
| Build tool | Vite 5.2.0 | ESM modules, fast HMR |
| Auth | @azure/msal-browser 3.10.0 + @azure/msal-react 2.0.15 | MSAL v3 API |
| Server state | @tanstack/react-query 5.28.0 | All backend data through React Query |
| HTTP | axios 1.6.8 | With MSAL interceptor for token attachment |
| Routing | react-router-dom 6.22.3 | Client-side navigation |
| Icons | lucide-react 0.383.0 | SVG icon library |
| Module type | ESM (type: "module") | |

---

## 4. Repository Layout

```
/Users/kelpejol/dragnet/Orgos/
│
├── .env                            ← Secrets — NEVER commit (gitignored)
├── .env.example                    ← Template — all keys with placeholder values
├── .gitignore
├── README.md                       ← Quick-start guide (setup, run, test)
├── CLAUDE.md                       ← This file — deep architectural reference
├── requirements.txt                ← Python dependencies
├── pytest.ini                      ← asyncio_mode = auto
├── config.py                       ← All settings via pydantic-settings
├── main.py                         ← FastAPI app, CORS, lifespan, all routers
│
├── graph/                          ← Microsoft Graph API layer
│   ├── __init__.py
│   ├── auth.py                     ← Token acquisition + in-process cache
│   ├── client.py                   ← SharePoint List CRUD, file ops, user resolution
│   └── exceptions.py               ← GraphAPIError hierarchy
│
├── auth/                           ← Incoming Entra ID token validation
│   ├── __init__.py
│   └── validator.py                ← JWT decode, JWKS cache, CurrentUser dataclass
│
├── grc/                            ← Tier 1: four GRC registers
│   ├── __init__.py
│   ├── constants.py                ← List IDs, SP column names, valid enum values
│   ├── schemas.py                  ← Pydantic v2 models for all four registers
│   ├── service.py                  ← Business logic, SP ↔ schema mapping
│   └── router.py                   ← /api/v1/grc/* routes
│
├── agents/                         ← AI agent modules
│   ├── __init__.py
│   ├── extractor/                  ← Document → {risk, control, evidence} triplets
│   │   ├── __init__.py
│   │   ├── schemas.py              ← ExtractionItem, OrphanItem, RegulatoryItem, AuditItem
│   │   ├── ollama_client.py        ← Local LLM calls (classify + extract)
│   │   ├── service.py              ← Pipeline: text → validate → write
│   │   └── router.py               ← /api/v1/agents/extract/*
│   ├── classifier/                 ← Post-extraction harmonisation + dedup
│   │   ├── __init__.py
│   │   ├── service.py
│   │   └── router.py               ← /api/v1/agents/classify
│   ├── policy_drafter/             ← AI policy generation + .docx build
│   │   ├── __init__.py
│   │   ├── docx_builder.py         ← python-docx Word document generator
│   │   └── router.py               ← /api/v1/agents/draft-document
│   ├── gap_analyzer/               ← Gap analysis vs standards
│   │   ├── __init__.py
│   │   └── router.py               ← /api/v1/agents/gap-analysis/run
│   └── cdi_checker/                ← CDI (Controlled Document Interface) validator
│       ├── __init__.py
│       ├── service.py
│       └── router.py               ← /api/v1/agents/cdi-check
│
├── review_queue/                   ← AI Review Queue (Zone 1/2/3 decisions)
│   ├── __init__.py
│   └── router.py                   ← /api/v1/queue/*
│
├── lifecycle/                      ← Document Lifecycle management
│   ├── __init__.py
│   └── router.py                   ← /api/v1/lifecycle/*
│
├── control_register/               ← Confirmed controls post-review
│   ├── __init__.py
│   └── router.py                   ← /api/v1/controls/*
│
├── evidence_tracker/               ← Evidence item lifecycle
│   ├── __init__.py
│   └── router.py                   ← /api/v1/evidence/*
│
├── standards_map/                  ← Live clause coverage traffic lights
│   ├── __init__.py
│   └── router.py                   ← /api/v1/standards/*
│
├── strategic_risks/                ← Strategic Risk Register
│   ├── __init__.py
│   └── router.py                   ← /api/v1/risks/*
│
├── gap_analysis/                   ← Gap findings + remediation
│   ├── __init__.py
│   └── router.py                   ← /api/v1/gap-analysis/*
│
├── sharepoint/                     ← SharePoint file browser + extraction trigger
│   ├── __init__.py
│   └── router.py                   ← /api/v1/sharepoint/*
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 ← All fixtures, mock Graph responses, mock user
│   ├── test_graph_client.py        ← Token, caching, error handling
│   └── grc/
│       ├── __init__.py
│       ├── test_document_register.py
│       ├── test_role_register.py
│       ├── test_compliance_calendar.py
│       └── test_contract_register.py
│
├── scripts/
│   ├── bulk_extract.py             ← Batch extraction with checkpoint/resume
│   ├── sync_roles.py               ← Sync roles from Entra ID / HR systems
│   └── cdi_triage.py               ← Pre-validate docs against CDI standards
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    ├── .env.local                  ← Frontend secrets (gitignored)
    ├── .env.local.example
    └── src/
        ├── main.jsx                ← MSAL + React Query setup, app bootstrap
        ├── App.jsx                 ← Main shell + page routing
        ├── authConfig.js           ← MSAL config, scope definitions
        ├── api/
        │   └── grcApi.js           ← Axios client with MSAL interceptor, all API calls
        ├── hooks/
        │   ├── useGrc.js           ← React Query hooks (per register + action)
        │   └── useCurrentUser.js   ← Parse user profile from MSAL token
        ├── components/
        │   ├── layout/
        │   │   ├── Sidebar.jsx     ← Navigation menu with collapse state
        │   │   ├── TopBar.jsx      ← User profile, sign-out button
        │   │   └── Layout.jsx      ← Page wrapper (sidebar + topbar + content)
        │   └── shared/
        │       ├── StatusBadge.jsx ← Colour-coded status chips
        │       ├── LoadingState.jsx← Spinner + skeleton loader
        │       ├── PersonPicker.jsx← Entra ID user search / select
        │       └── Forms.jsx       ← Field, Btn, Link primitives
        └── pages/
            ├── WorkHub/index.jsx
            ├── DocumentRegister/
            │   ├── index.jsx
            │   └── DocumentForm.jsx
            ├── RoleRegister/
            │   ├── index.jsx
            │   └── RoleForm.jsx
            ├── ComplianceCalendar/
            │   ├── index.jsx
            │   └── CalendarForm.jsx
            ├── ContractRegister/
            │   ├── index.jsx
            │   └── ContractForm.jsx
            ├── AIReviewQueue/index.jsx
            ├── DocumentLifecycle/
            ├── ControlRegister/index.jsx
            ├── EvidenceTracker/
            ├── StandardsMap/index.jsx
            ├── StrategicRisks/
            ├── GapAnalysis/index.jsx
            ├── Harmonisation/index.jsx
            ├── Extractor/index.jsx
            └── AssignmentOwnership/index.jsx
```

---

## 5. Backend: Module-by-Module Reference

### 5.1 config.py — Settings & Environment

Single source of truth for all runtime configuration. **All other modules import `settings` from here — never `os.environ` directly.**

**Class:** `Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")`

**Field categories:**

| Category | Fields |
|---|---|
| Entra ID | tenant_id, client_id, client_secret |
| SharePoint | sharepoint_site_id, sharepoint_site_url, compliance_site_url, compliance_library_name, compliance_starting_folder |
| List IDs (Tier 1) | document_register_list_id, role_register_list_id, compliance_calendar_list_id, contract_register_list_id |
| List IDs (Tier 2+) | ai_review_queue_list_id, document_lifecycle_list_id, control_register_list_id, evidence_tracker_list_id, audit_log_list_id, strategic_risk_register_list_id, gap_analysis_list_id |
| Application | environment, allowed_origins, app_port, log_level, skip_auth |
| Ollama | ollama_base_url, ollama_model, ollama_timeout |

All List IDs default to `"placeholder"` — the application starts cleanly with placeholder values; `settings.is_list_configured(list_id)` returns `False` for them and raises a `SharePointListNotConfiguredError` when accessed.

**Computed properties:**
- `allowed_origins_list` → splits comma-separated ALLOWED_ORIGINS string into list
- `is_development` → `environment.lower() == "development"`
- `graph_token_url` → `https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token`
- `graph_base_url` → `https://graph.microsoft.com/v1.0`
- `jwks_uri` → JWKS endpoint for RS256 key retrieval
- `token_issuer` → Expected `iss` claim in JWT
- `sharepoint_lists_base` → Base URL for all List operations
- `is_list_configured(list_id: str) → bool` → True if not "placeholder" or ""

**Caching:** `get_settings()` is decorated with `@lru_cache()` — `.env` is read once per process. In tests, call `get_settings.cache_clear()` before patching.

**Logging:** `configure_logging()` sets root logger level from `settings.log_level`. Called once in [main.py](main.py) before everything else.

---

### 5.2 main.py — FastAPI Entry Point

Creates the FastAPI `app` instance, registers CORS middleware, mounts all 14 routers, and defines health endpoints.

**Lifespan pattern (FastAPI 0.115+):**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup:
    await graph_client.startup()   # Opens httpx.AsyncClient
    await _get_jwks()              # Pre-fetches Microsoft public keys (fails soft)
    yield
    # Shutdown:
    await graph_client.shutdown()  # Closes httpx client
```

**CORS configuration:**
- `allow_origins`: from `settings.allowed_origins_list`
- `allow_methods`: `["GET", "POST", "PATCH", "DELETE", "OPTIONS"]`
- `allow_headers`: `["Authorization", "Content-Type", "Accept"]`
- `allow_credentials`: `True`

**Routers mounted (in order):**
`grc_router`, `extractor_router`, `sharepoint_router`, `queue_router`, `lifecycle_router`, `control_router`, `evidence_router`, `standards_router`, `risks_router`, `gap_router`, `classifier_router`, `cdi_router`, `policy_drafter_router`, `gap_analyzer_router`

**Health endpoints (no auth):**
- `GET /health` → `{"status": "ok", "environment": ..., "version": "1.0.0"}`
- `GET /api/v1/health/graph` → Graph connectivity check; returns 503 if Graph unreachable

**API docs:**
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

---

### 5.3 graph/ — Microsoft Graph API Layer

The entire interface between OrgOS and Microsoft's cloud services. Three files:

#### graph/auth.py — Token acquisition & caching

Implements the **client credentials OAuth2 flow** (backend → Graph API, no user involved).

- **`async get_graph_access_token() → str`**
  - Checks in-process cache first (module-level `_token_cache` dict)
  - If token expires within 60 seconds, fetches a new one
  - POSTs to `settings.graph_token_url` with `client_credentials` grant
  - Caches: `_token_cache = {"access_token": "...", "expires_at": float}`
  - Returns bearer token string

- **`invalidate_token_cache()`** — Force-clears cache; called on 401 responses to retry with a fresh token

- **`get_auth_header() → dict`** — Sync wrapper that calls the async token function; returns `{"Authorization": "Bearer <token>"}`

#### graph/client.py — SharePoint List CRUD & file operations

All SharePoint operations go through functions here. Uses `httpx.AsyncClient` opened at startup.

**List operations:**

| Function | HTTP | Description |
|---|---|---|
| `get_list_items(list_id, list_name, odata_filter, select_fields, top)` | GET | Paginated read with `@odata.nextLink` support |
| `get_list_item(list_id, list_name, item_id)` | GET | Single item by ID |
| `create_list_item(list_id, list_name, fields)` | POST | Create; returns created item dict with auto-assigned ID |
| `update_list_item(list_id, list_name, item_id, fields)` | PATCH | Partial update; returns updated fields |
| `soft_delete_list_item(list_id, list_name, item_id)` | PATCH | Sets `Status = "Withdrawn"` — never hard-deletes |

**User resolution:**

- `async resolve_user(entra_oid) → dict` — Resolves an Entra OID to `{display_name, email}` via `GET /users/{oid}`. Results cached per process. Handles special `"dev-bypass-oid"` for local dev without real Entra users.

**SharePoint file operations:**

- `async upload_file_to_sharepoint(file_bytes, filename, folder) → str` — PUT to SharePoint drive; returns `webUrl`
- `async download_file_from_sharepoint(web_url) → tuple[bytes, str]` — Downloads via `/shares/u!{base64url}` encoding pattern

**Health:**

- `async check_graph_connectivity() → dict` — Validates token acquisition + reaches SharePoint site; used by `GET /api/v1/health/graph`

#### graph/exceptions.py — Custom exception hierarchy

```
GraphAPIError (base)
├── GraphAuthError          (401 — token invalid/expired)
├── GraphPermissionError    (403 — scope insufficient)
├── GraphNotFoundError      (404 — item not found)
├── GraphRateLimitError     (429 — retry_after attribute)
├── GraphServiceUnavailableError  (503 — Graph down)
└── SharePointListNotConfiguredError  (503 — List ID = "placeholder")
```

**`raise_for_graph_status(status_code, body, context)`** — Factory function that maps HTTP status codes to the right exception type with a human-readable message. Used after every Graph API response.

In `grc/router.py`, the helper `_handle_graph_error(exc, operation)` converts these exceptions to FastAPI `HTTPException` with appropriate status codes.

---

### 5.4 auth/ — Token Validation

Validates **incoming** bearer tokens from the React frontend (Entra ID JWTs signed with RS256).

#### auth/validator.py

**`@dataclass CurrentUser`:** `{oid: str, name: str, email: str, tenant_id: str, roles: list[str]}`

**JWKS caching:**
- `async _get_jwks() → list[dict]` — Fetches Microsoft's public keys from `settings.jwks_uri`. Cached module-level with 2-hour TTL. Pre-fetched at startup.
- `async _find_signing_key(token, jwks) → str` — Finds the key matching the token's `kid` header. If not found, auto-refreshes JWKS once (handles key rotation).

**`async validate_entra_id_token(token: str) → CurrentUser`:**
1. Decodes JWT header to get `kid`
2. Looks up signing key from JWKS
3. Decodes + verifies with RS256 signature
4. Validates `iss` (must match `settings.token_issuer`), `aud` (must match `settings.client_id`), `tid` (must match `settings.tenant_id`)
5. Returns `CurrentUser` populated from claims
6. Raises `HTTPException(401)` on any validation failure

**FastAPI dependencies:**
- `async get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) → CurrentUser` — The standard FastAPI `Depends()` for all protected endpoints. When `settings.skip_auth = True`, returns a hardcoded `dev-bypass-oid` user without validation (development only).
- `require_compliance_lead(user: CurrentUser = Depends(get_current_user)) → CurrentUser` — Additional dependency that enforces `"Compliance.Lead"` or `"OrgOS.Admin"` in `user.roles`. Used on all agent trigger endpoints.

---

### 5.5 grc/ — Tier 1 GRC Registers

The four core registers: **Document Register**, **Role Register**, **Compliance Calendar**, **Contract Register**.

#### grc/schemas.py — Pydantic v2 Data Models

**Person references (shared):**
```python
class PersonRef(BaseModel):
    oid: str
    display_name: str
    email: str
```
`PersonRef` is immutable (never stored in SharePoint — resolved at query time from OID).

**Document Register:**
- `DocumentType`: Policy | Procedure | SOP | Form | Guidelines
- `DocumentStatus`: Active | Under Review | Superseded | Withdrawn
- `DocumentBase`: `document_code` (pattern: `DRG-[DEPT]-[TYPE]-[REF]-[YY]`), `title`, `type`, `department`, `current_version`, `effective_date`, `next_review_date`, `applicable_standards` (comma-separated: ISO 9001/ISO 27001/NDPA/Internal), `status`
- `DocumentCreate(DocumentBase)`: adds `owner_id` (Entra OID)
- `DocumentUpdate`: all fields Optional
- `DocumentRead(DocumentBase)`: adds `id` (SP item ID), `owner: PersonRef`, `linked_controls_count: int`, `created`, `modified`

**Role Register:**
- `RoleSourceSystem`: Entra ID | SeamlessHR | BitWiseFlow | Manual
- `AssignmentStatus`: Assigned | Unassigned
- `RoleBase`: `role_title`, `department`, `jd_reference` (pattern: `DRG-JD-[DEPT]-[CODE]-[NN]`), `assignment_status`, `source_system`, `variant_terms`
- `RoleCreate(RoleBase)`: adds `current_holder_id` (Entra OID or None)
- `RoleAssign`: only `current_holder_id` (for the PATCH /assign endpoint)
- `RoleUpdate`: all Optional
- `RoleRead(RoleBase)`: adds `id`, `current_holder: Optional[PersonRef]`, `created`, `modified`

**Compliance Calendar (Obligations):**
- `ObligationType`: Statutory | Licensing | Certification | Regulatory
- `ObligationRecurrence`: Monthly | Quarterly | Annual | Once
- `ObligationStatus`: Overdue | Due Soon | Upcoming | Completed
- `ObligationBase`: `obligation_name`, `type`, `authority`, `due_date`, `recurrence`, `status`
- `ObligationCreate(ObligationBase)`: adds `owner_id`
- `ObligationRead(ObligationBase)`: adds `id`, `owner: PersonRef`, `created`, `modified`
- **Status is never stored** — recalculated on every read from `due_date` vs today

**Contract Register:**
- `ContractStatus`: Active | Expired | Under Review | Terminated | Expiring Soon
- `ContractBase`: `contract_reference`, `title`, `counterparty`, `contract_type`, `owner_id`, `start_date`, `end_date`, `review_date`, `applicable_standards`, `status`
- `ContractCreate(ContractBase)`: `owner_id`
- `ContractUpdate`: all Optional
- `ContractRead(ContractBase)`: adds `id`, `owner: PersonRef`, `created`, `modified`
- **Expiring Soon** = end_date within 60 days of today (calculated, never stored)

#### grc/constants.py — SharePoint Field Mappings

The single source of truth for mapping Python schema field names to SharePoint column names (which differ in casing and sometimes naming).

```python
DOC_FIELDS = {
    "document_code": "DocumentCode",
    "title": "Title",
    "type": "DocumentType",
    "department": "Department",
    "owner": "OwnerEntraId",     # Stores OID; separate SP person column optional
    "status": "DocumentStatus",
    # ...
}
```

Also contains: threshold constants (`CAL_DUE_SOON_THRESHOLD_DAYS = 30`, `CONTRACT_EXPIRING_SOON_THRESHOLD_DAYS = 60`), valid choice lists for each register.

#### grc/service.py — Business Logic

Pure functions — no side effects beyond Graph API calls.

**Status calculation:**
- `_calculate_obligation_status(due_date: date) → ObligationStatus` — Pure: today > due_date → Overdue; within 30d → Due Soon; else Upcoming
- `_calculate_contract_status(end_date: date) → ContractStatus` — Pure: today > end_date → Expired; within 60d → Expiring Soon; else Active

**Person field helpers:**
- `_build_person_ref(fields: dict, owner_field: str) → PersonRef` — Takes a SharePoint item dict, reads the OID from `{owner_field}EntraId`, calls `resolve_user()` to get display_name + email, returns `PersonRef`
- `_person_write_field(owner_field: str, entra_oid: str) → dict` — Builds the `{owner_field}EntraId: oid` dict for writes

**CRUD per register** (same pattern for all four):
- `get_documents(filters) → list[DocumentRead]` — Calls `get_list_items()`, maps each SP item through `_build_person_ref()`, returns typed list
- `get_document(id) → DocumentRead`
- `create_document(data: DocumentCreate) → DocumentRead`
- `update_document(id, data: DocumentUpdate) → DocumentRead` — Only sends non-None fields (partial update)
- `soft_delete_document(id)` — Calls `soft_delete_list_item()` → Status = Withdrawn

#### grc/router.py — FastAPI Routes

All routes under `/api/v1/grc/`, all require `Depends(get_current_user)`.

**Document Register:**
- `GET /api/v1/grc/documents` — Optional query params: `status`, `department`, `document_type`
- `POST /api/v1/grc/documents` (201) — Body: `DocumentCreate`
- `GET /api/v1/grc/documents/{id}`
- `PATCH /api/v1/grc/documents/{id}` — Body: `DocumentUpdate`
- `DELETE /api/v1/grc/documents/{id}` — Soft delete (sets status = Withdrawn)

**Role Register:**
- `GET /api/v1/grc/roles` — Optional: `department`, `assignment_status`
- `GET /api/v1/grc/roles/unassigned` — All roles with no current_holder
- `POST /api/v1/grc/roles` (201)
- `GET /api/v1/grc/roles/{id}`
- `PATCH /api/v1/grc/roles/{id}` — Full update
- `PATCH /api/v1/grc/roles/{id}/assign` — Body: `RoleAssign` (just sets current_holder)
- `DELETE /api/v1/grc/roles/{id}` — Soft delete

**Compliance Calendar:**
- `GET /api/v1/grc/compliance` — Optional: `status`, `type`, `authority`
- `POST /api/v1/grc/compliance` (201)
- `GET /api/v1/grc/compliance/{id}`
- `PATCH /api/v1/grc/compliance/{id}`
- `DELETE /api/v1/grc/compliance/{id}`

**Contract Register:**
- `GET /api/v1/grc/contracts` — Optional: `status`, `contract_type`
- `POST /api/v1/grc/contracts` (201)
- `GET /api/v1/grc/contracts/{id}`
- `PATCH /api/v1/grc/contracts/{id}`
- `DELETE /api/v1/grc/contracts/{id}`

**User resolution helper:**
- `GET /api/v1/grc/users/resolve?email={email}` — Resolves an email address to `{oid, display_name, email, job_title}` via Graph API. Used by person-picker components in the frontend.

---

### 5.6 agents/extractor/ — Document Extraction

The core AI pipeline. Accepts a PDF/DOCX/TXT file or raw text and produces structured GRC data.

#### agents/extractor/schemas.py — Extraction Data Models

**Evidence taxonomy (16 types — DRG-QI-REF-EVTX-01-26, no free-text permitted):**

| Code | Meaning |
|---|---|
| LOG | System log export |
| CFG | Configuration evidence |
| APR | Signed approval record |
| FRM | Completed form/record |
| TRN | Training record |
| ACK | Policy acknowledgement |
| TST | Test/drill/verification |
| CRT | Certificate/external attestation |
| MTG | Meeting/governance record |
| REV | Review record |
| CHK | Checklist completion |
| CNT | Contract/agreement |
| INV | Inventory/register extract |
| CHG | Change record |
| INC | Incident record |
| RPT | Report/assessment |

**Item types by document:**

`ExtractionItem` (Policy/Contract) — Control triplet:
- Control fields: `risk_statement`, `control_statement`, `control_type (ControlType)`, `proposed_owner_role`, `iso_clause`, `completeness_flag`, `deficiency_reason`
- Contract-specific optional: `source_type`, `counterparty`, `contract_clause`, `expiry_date`, `renewal_date`, `ndpa_section`
- Evidence fields: `evidence_type (EvidenceType)`, `evidence_description`, `source_system`, `evidence_format`, `evidence_frequency`, `evidence_collection_method`, `evidence_owner_role`, `evidence_validation_criteria`, `evidence_undefined`, `evidence_undefined_reason`

`OrphanItem` (JD processing):
- `orphan_direction`: "JD_to_Doc" | "Doc_to_JD"
- `role_title`, `department`, `reports_to`, `responsibility_statement`
- `orphan_classification`: "POTENTIAL_ORPHAN" | "ROLE_REFERENCE"
- `orphan_reason`

`RegulatoryItem` (Statutory/Regulatory docs → Compliance Calendar):
- `obligation_statement`, `authority`, `deadline`, `recurrence`, `standards_reference`, `applies_to_dragnet`, `penalty_if_missed`

`AuditItem` (Audit reports/risk assessments → Gap Analysis):
- `finding_type`: NonConformity | Finding | Observation | Risk
- `severity`: Critical | Major | Minor
- `finding_statement`, `standard_reference`, `gap_type` (EvidenceGap | ControlGap | ProcessGap | Unknown)
- `remediation_required`, `triggers_document_lifecycle`, `is_repeated_finding`

All items share `BaseExtractionItem`: `document_type (ItemDocumentType)`, `extraction_category (ExtractionCategory)`, `source_clause`, `confidence_score (0.0–1.0)`.

`ExtractionRequest`: `text (min_length=50)`, `source_document_code`, `folder_path (optional)`, `write_to_sharepoint (bool)`

`ExtractionResponse`: `source_document_code`, `document_type`, `total_extracted`, `complete_count`, `deficient_count`, `written_to_sharepoint`, `skipped_reason`, `items: list[dict]` (mixed types)

#### agents/extractor/ollama_client.py — Local LLM Client

Calls the Ollama `/api/generate` endpoint running locally.

- `async classify_document(text, folder_path) → DocumentType` — Sends text to LLM, returns one of: Policy, JobDescription, Contract, Regulatory, Audit, Unclassified. Folder path is a hint for classification.
- `async run_extraction(text, doc_type, doc_code) → list[dict]` — Sends structured prompt to Ollama requesting JSON array of items matching the schema for `doc_type`. Parses response, normalises keys, validates required fields.
- `NON_EXTRACTION_TYPES`: document types that are not processed for controls (e.g., Unclassified)
- Configurable: `settings.ollama_base_url`, `settings.ollama_model`, `settings.ollama_timeout`
- Default model: `llama3` (configurable via OLLAMA_MODEL env var)

#### agents/extractor/service.py — Extraction Pipeline

**Text extraction:**
- `extract_text_from_pdf(file_bytes) → str` — `pypdf.PdfReader`, preserves page boundaries with `\n--- Page N ---\n` markers
- `extract_text_from_docx(file_bytes) → str` — `python-docx.Document`, joins paragraph text

**Classification helpers (keyword-based, not LLM — more reliable):**
- `_assign_control_type(statement) → str` — Keyword rules: "prevent" → Preventive; "detect/monitor/audit/log" → Detective; "correct/remediate/recover" → Corrective; else Directive
- `_suggest_evidence_type(statement) → Optional[str]` — Keyword rules to suggest one of the 16 EvidenceType codes

**Validation:**
- `_validate_items(items) → (complete_list, deficient_list)` — Separates COMPLETE from DEFICIENT; DEFICIENT = any required field empty or undefined

**Main pipeline functions:**
- `run_extraction_from_text(text, doc_code, write_to_sharepoint, folder_path) → ExtractionResponse` — Full pipeline: classify → extract → validate → optionally write to AI Review Queue
- `run_extraction_from_file(file_bytes, filename, doc_code, write_to_sharepoint) → ExtractionResponse` — Extracts text from file format, then calls text pipeline

Non-control detection: The LLM is prompted to reject scope statements, definitions, and preamble — only genuine control requirements produce items.

If `write_to_sharepoint=True`, COMPLETE items are written to the AI Review Queue list with `ReviewStatus = "Pending Review"`.

#### agents/extractor/router.py — Extraction Endpoints

- `POST /api/v1/agents/extract/text` — Body: `ExtractionRequest` → `ExtractionResponse`
- `POST /api/v1/agents/extract/file` — Multipart: `file` (PDF/DOCX/TXT, max 10MB) + `source_document_code` form field → `ExtractionResponse`
- `GET /api/v1/agents/health/ollama` — Checks Ollama is running and model is available
- All protected with `Depends(get_current_user)`

---

### 5.7 agents/classifier/ — Harmonisation & Dedup

Runs after extraction to detect duplicate or variant controls across documents.

**What it does:**
1. Reads all Zone 1 (Extraction) items from the AI Review Queue
2. Compares role terms across items using variant_terms from Role Register
3. Identifies items that are semantic duplicates or variations of each other
4. Writes decisions to Zone 2 (orphan handling) and Zone 3 (harmonisation queue) items

**Endpoints:**
- `POST /api/v1/agents/classify` — Trigger classification run; requires `require_compliance_lead`
- `GET /api/v1/agents/classify/status` — Returns summary of last run (items processed, duplicates found, zones populated)

---

### 5.8 agents/policy_drafter/ — AI Policy Generation

Generates CDI-compliant policy/procedure documents using Ollama and uploads them to SharePoint.

**Endpoint:** `POST /api/v1/agents/draft-document`

**Request fields:**
- `title`: Document title
- `doc_type`: Policy | Procedure | SOP
- `department`: Target department
- `notes`: Optional guidance to the LLM
- `standards_mapping`: List of applicable standards (ISO 27001/9001/NDPA)
- `trigger`: Lifecycle trigger reason (Gap Remediation, Scheduled Review, etc.)
- `linked_gap_id`: Optional link to Gap Analysis item

**Response fields:**
- `lifecycle_id`: Created Document Lifecycle entry ID
- `doc_code`: Generated document code (DRG-[DEPT]-[TYPE]-...)
- `sections`: List of section titles generated
- `full_text`: Full draft text
- `sharepoint_url`: URL to uploaded .docx in SharePoint (Drafts folder)

**docx_builder.py:**
- `async build_docx(draft_dict) → BytesIO` — Creates a formatted Word document from the draft text structure using `python-docx`. Applies Dragnet document styling.
- The generated .docx is uploaded to SharePoint `compliance_starting_folder/Drafts/` and a Document Lifecycle entry is created pointing to it.

---

### 5.9 agents/gap_analyzer/ — Gap Analysis Agent

Compares the current Control Register and Evidence Tracker state against ISO 27001, ISO 9001, and NDPA requirements to identify gaps.

**Endpoint:** `POST /api/v1/agents/gap-analysis/run` — Requires `require_compliance_lead`

**What it does:**
1. Reads all items from Control Register, Evidence Tracker, Role Register
2. Builds a coverage map: which ISO/NDPA clauses have controls, which have accepted evidence, which have assigned owners
3. Compares coverage map against the full standard clause list
4. For each uncovered or partially covered clause, writes a Gap Analysis item with:
   - Severity: Critical (no control) | Major (control, no evidence) | Minor (evidence pending)
   - `proposed_remediation`: Full remediation package JSON (Bobby's amendment — includes suggested controls, evidence types, owner roles, timeline)
5. Sets `target_date` automatically based on severity

**Status endpoint:** `GET /api/v1/agents/gap-analysis/status` — Returns last run summary.

---

### 5.10 agents/cdi_checker/ — CDI Compliance Checker

Validates documents against the CDI (Controlled Document Interface) standard — Dragnet's internal document quality framework.

**Endpoints:**
- `POST /api/v1/agents/cdi-check` (or similar) — Submit document for CDI validation
- `GET /api/v1/agents/cdi-check/status`

CDI checks include: document code format compliance, required metadata fields, version numbering, effective/review date logic, and mandatory section presence.

---

### 5.11 review_queue/ — AI Review Queue

The human-in-the-loop staging area where extracted items await human decisions before entering the active registers. Three logical zones:

**Zone 1 — Extraction items** (ExtractionCategory = "Extraction"):
Controls extracted from policy/contract documents. Reviewer decides:
- `POST /api/v1/queue/{id}/accept-control` — **Zone 1 cascade** (see Data Flows section)
- `POST /api/v1/queue/{id}/edit-accept` — Edit fields first, then trigger same cascade
- `POST /api/v1/queue/{id}/reject` — Body includes `rationale` string; logs to Audit Log
- `POST /api/v1/queue/{id}/route-to-owner` — Assign item to a role owner for input

**Zone 2 — Orphan items** (ExtractionCategory = "Orphan"):
Items from JD processing with unclear ownership or references. Decisions:
- Create new document
- Add to existing policy
- Mark as intentional (no action)
- Route to department head

**Zone 3 — Harmonisation items** (ExtractionCategory = "Harmonisation"):
Duplicate/variant controls identified by the Classifier agent. Decisions:
- Merge controls (consolidate into one canonical control)
- Keep separate (intentional variants)
- Rename and standardise (align terminology without merging)

**List endpoints:**
- `GET /api/v1/queue` — All items; filter by `zone`, `review_status`, `item_type`
- `GET /api/v1/queue/{id}` — Single item with all fields

---

### 5.12 lifecycle/ — Document Lifecycle

Tracks every document from creation trigger through stages to approval. Populated by:
- AI Policy Drafter (auto-creates entry with `AIGenerated = True`)
- Manual creation by Compliance Lead
- Gap Analysis remediation (links to Gap item)
- CDI Fix (from CDI Checker findings)
- Scheduled Review (from Compliance Calendar)

**Lifecycle stages:** Review → Sensitisation → Approval

**Endpoints:**
- `GET /api/v1/lifecycle` — All lifecycle entries
- `GET /api/v1/lifecycle/{id}` — Single entry
- `POST /api/v1/lifecycle` — Create entry; fields include `trigger`, `linked_gap_id`, `ai_generated`, `revised`
- `PATCH /api/v1/lifecycle/{id}/stage` — Progress to next stage (includes approval_by field)
- `POST /api/v1/lifecycle/{id}/upload` — Upload file; creates SharePoint link on entry
- `GET /api/v1/lifecycle/documents/{id}/download` — Download draft document from SharePoint

---

### 5.13 control_register/ — Confirmed Controls

The authoritative list of active controls that have passed human review. Populated exclusively via the Zone 1 accept cascade from the AI Review Queue.

Each control is linked to:
- A source document (Document Register)
- An owner role (Role Register)
- Evidence items (Evidence Tracker, by `control_id`)
- ISO/NDPA clauses (used by Standards Map)

**Endpoints:**
- `GET /api/v1/controls` — All controls; filter by `document_id`, `status`, `iso_clause`
- `GET /api/v1/controls/{id}` — Single control with linked evidence items (joined on read)

**Control fields:** `control_statement`, `control_type`, `source_document` (code), `iso_clause`, `owner_role` (linked to Role Register), `risk_implication`, `status` (Active | Under Review | Superseded | Withdrawn)

---

### 5.14 evidence_tracker/ — Evidence Collection

Each evidence item is linked to one control and tracks the collection/verification lifecycle.

**Evidence item statuses:** Pending → Submitted → Accepted | Rejected (Overdue is calculated)

**Endpoints:**
- `GET /api/v1/evidence` — All items; filter by `status`, `control_id`, `evidence_type`, `owner_oid`
- `GET /api/v1/evidence/{id}` — Single item
- `PATCH /api/v1/evidence/{id}/submit` — Owner submits: sets `evidence_link` (URL/path) + `submission_notes`; status → Submitted
- `PATCH /api/v1/evidence/{id}/verify` — Compliance verifies: `decision` (Accepted/Rejected) + `reviewer_notes`; status → Accepted or Rejected

**Evidence item fields:** `evidence_description`, `evidence_type (EvidenceType)`, `source_system`, `evidence_format`, `frequency`, `collection_method`, `owner_role`, `validation_criteria`, `linked_control_id`, `status`, `evidence_link`, `due_date`

**Overdue calculation:** `due_date < today AND status = Pending or Submitted` → displayed as Overdue (calculated, not stored)

---

### 5.15 standards_map/ — Standards Traffic Lights

A live coverage view across ISO 27001, ISO 9001, and NDPA clauses. No data stored — every traffic light recalculated on request from Control Register + Evidence Tracker.

**Traffic light rules:**

| Color | Condition |
|---|---|
| Green | All controls have accepted evidence, owners assigned, nothing overdue |
| Amber | Evidence due soon (≤7 days), submitted but not yet verified, or new control with no evidence yet |
| Red | Evidence overdue, no controls mapped to clause, owner unassigned, evidence rejected |

**Endpoints:**
- `GET /api/v1/standards/map` — All clauses with current traffic light colour and summary counts
- `GET /api/v1/standards/map/{clause_code}` — Full chain for one clause: clause details + all linked controls + all evidence items per control + owner info

---

### 5.16 strategic_risks/ — Strategic Risk Register

Manually curated by ExCo (Executive Committee). Three entry paths:

1. **ExCo assessment** — Direct risk identification during board review
2. **Gap acceptance** — When a Gap Analysis finding is accepted as risk (not remediated)
3. **Incident escalation** — A severity incident escalated to strategic risk level

**Risk scoring:** `risk_score = likelihood (1–3) × impact (1–4) = 1–12`

| Score | Level |
|---|---|
| 1–3 | Low |
| 4–6 | Medium |
| 7–9 | High |
| 10–12 | Critical |

**Endpoints:**
- `GET /api/v1/risks` — All risks; sorted by risk_score descending
- `GET /api/v1/risks/{id}` — Single risk
- `POST /api/v1/risks` — Create; fields: `description`, `category`, `likelihood`, `impact`, `treatment`, `status`, `related_gap_id` (optional)
- `PATCH /api/v1/risks/{id}` — Update status, treatment, notes

---

### 5.17 gap_analysis/ — Gap Findings

Tracks identified compliance gaps from two sources:
1. AI Gap Analyzer agent (from Control Register vs standard clauses)
2. AuditItem entries processed through the AI Review Queue

**Auto-generated GapId format:** `GAP-{standard}-{YY}-{NNN}` (e.g., `GAP-ISO27001-26-001`)

**Target dates by severity:**
- Critical: 30 days
- Major: 60 days
- Minor: 90 days

**Endpoints:**
- `GET /api/v1/gap-analysis` — All gaps; sorted Critical → Major → Minor; filter by `status`, `standard`, `severity`
- `GET /api/v1/gap-analysis/{id}` — Single gap with full remediation package
- `POST /api/v1/gap-analysis` — Manual gap creation
- `PATCH /api/v1/gap-analysis/{id}/status` — Update status: Open | In progress | Accepted risk | Closed
- `POST /api/v1/gap-analysis/{id}/accept-risk` — Escalate to Strategic Risk Register (creates a Risk item linked to this gap)

**`proposed_remediation` field:** Full JSON remediation package per Bobby's amendment — includes suggested controls, evidence types, owner roles, timeline, and any triggered lifecycle items.

---

### 5.18 sharepoint/ — File Browser & Extraction

Allows browsing the SharePoint Compliance document library and triggering extraction on any file.

**Compliance library:** `settings.compliance_site_url` / `settings.compliance_library_name` / `settings.compliance_starting_folder` ("GRC MASTERY")

**Endpoints:**
- `GET /api/v1/sharepoint/browse` — Root of GRC MASTERY folder; returns folder/file listing with drive item IDs
- `GET /api/v1/sharepoint/browse/{folder_id}` — Subfolder listing by drive item ID
- `POST /api/v1/sharepoint/extract/{item_id}` — Download file by item ID from SharePoint, run through extractor pipeline, return `ExtractionResponse`

---

## 6. Frontend: Module-by-Module Reference

### 6.1 Entry Point & MSAL Setup

**[frontend/src/main.jsx](frontend/src/main.jsx)**

```javascript
export const msalInstance = new PublicClientApplication(msalConfig);
await msalInstance.initialize();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 30_000,          // 30s — data considered fresh
      refetchOnWindowFocus: PROD  // Only refetch on focus in production
    },
    mutations: { retry: 0 }       // Never auto-retry mutations
  }
});
```

The app is wrapped in `<MsalProvider msalInstance={msalInstance}>` and `<QueryClientProvider client={queryClient}>`.

---

### 6.2 Auth Configuration

**[frontend/src/authConfig.js](frontend/src/authConfig.js)**

```javascript
export const msalConfig = {
  auth: {
    clientId: import.meta.env.VITE_AZURE_CLIENT_ID,
    authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    redirectUri: window.location.origin,
  },
  cache: { cacheLocation: "sessionStorage" },
};

// For acquiring tokens to call the backend
export const apiTokenRequest = {
  scopes: [`api://${VITE_AZURE_CLIENT_ID}/OrgOS.ReadWrite`]
};

// For initial login
export const loginRequest = {
  scopes: ["openid", "profile", "email", `api://.../OrgOS.ReadWrite`]
};
```

When the token expires, `acquireTokenSilent` refreshes it automatically. If silent refresh fails, it falls back to `acquireTokenPopup`.

---

### 6.3 API Client (grcApi.js)

**[frontend/src/api/grcApi.js](frontend/src/api/grcApi.js)**

Axios instance with two interceptors:

**Request interceptor:** Before every request, acquires MSAL token (`acquireTokenSilent`) and attaches as `Authorization: Bearer <token>`.

**Response interceptor:** Normalises `{ detail: "error message" }` error shapes from FastAPI into consistent JavaScript Error objects.

**API modules exported:**

```javascript
documentsApi:  { list(params), get(id), create(doc), update(id, data), softDelete(id) }
rolesApi:      { list(params), listUnassigned(), get(id), create(role), update(id, data), assign(id, oid), softDelete(id) }
complianceApi: { list(params), get(id), create(obl), update(id, data), softDelete(id) }
contractsApi:  { list(params), get(id), create(contract), update(id, data), softDelete(id) }
usersApi:      { resolve(email) }
queueApi:      { list(params), get(id), acceptControl(id), editAccept(id, data), reject(id, rationale), routeToOwner(id, oid) }
lifecycleApi:  { list(params), get(id), create(data), progressStage(id, data), upload(id, file), download(id) }
controlsApi:   { list(params), get(id) }
evidenceApi:   { list(params), get(id), submit(id, data), verify(id, data) }
standardsApi:  { getMap(), getClause(code) }
risksApi:      { list(params), get(id), create(data), update(id, data) }
gapApi:        { list(params), get(id), create(data), updateStatus(id, status), acceptRisk(id, data) }
extractorApi:  { extractText(data), extractFile(file, docCode), ollamaHealth() }
sharepointApi: { browse(folderId), extract(itemId) }
agentsApi:     { classify(), classifyStatus(), draftDocument(data), runGapAnalysis(), gapAnalysisStatus() }
```

---

### 6.4 React Query Hooks

**[frontend/src/hooks/useGrc.js](frontend/src/hooks/useGrc.js)**

Wraps every API call in a React Query `useQuery` or `useMutation` hook. This centralises:
- Caching and stale-time management
- Loading / error states
- Cache invalidation after mutations (e.g., after creating a document, invalidate the documents list)
- Retry logic

Pattern for each register:
```javascript
export function useDocuments(filters) {
  return useQuery({
    queryKey: ['documents', filters],
    queryFn: () => documentsApi.list(filters).then(r => r.data)
  });
}

export function useCreateDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => documentsApi.create(data).then(r => r.data),
    onSuccess: () => queryClient.invalidateQueries(['documents'])
  });
}
```

**[frontend/src/hooks/useCurrentUser.js](frontend/src/hooks/useCurrentUser.js)**

Parses the active MSAL account to extract user profile (name, email, OID) without an API call.

---

### 6.5 Layout Components

**[frontend/src/components/layout/Sidebar.jsx](frontend/src/components/layout/Sidebar.jsx)**
- Vertical navigation menu with icons (lucide-react)
- Collapsible (icon-only mode)
- Groups: Registers (Document, Role, Calendar, Contract), AI Workflow (Extractor, Queue, Harmonisation, Ownership), Active Governance (Control Register, Evidence, Standards Map, Lifecycle), Risk & Compliance (Gap Analysis, Strategic Risks)

**[frontend/src/components/layout/TopBar.jsx](frontend/src/components/layout/TopBar.jsx)**
- Shows current user name + avatar
- Sign out button (calls `msalInstance.logoutPopup()`)
- Page title / breadcrumb

**[frontend/src/components/layout/Layout.jsx](frontend/src/components/layout/Layout.jsx)**
- Root wrapper: `<Sidebar /> + <div className="main"><TopBar /> <content /></div>`

---

### 6.6 Shared Components

**StatusBadge.jsx** — Renders a coloured chip based on status string. Colour mapping:
- Active / Accepted / Complete / Green → green
- Under Review / Due Soon / Amber / Submitted → yellow/amber
- Overdue / Rejected / Red / Expired → red
- Withdrawn / Superseded / Terminated → grey

**LoadingState.jsx** — Spinner + skeleton placeholder for loading states

**PersonPicker.jsx** — Input field that calls `usersApi.resolve(email)` as the user types, shows Entra ID user suggestions, returns selected `{oid, display_name, email}` to parent

**Forms.jsx** — Primitive form components:
- `Field` — Label + input wrapper with error state
- `Btn` — Button with loading state and variant (primary/secondary/danger)
- `Link` — Internal nav link (wraps react-router `<Link>`)

---

### 6.7 Pages

**WorkHub/index.jsx** — Dashboard. Summary cards for each register (item counts, overdue counts, status distribution). Quick-action links.

**DocumentRegister/** — Two files:
- `index.jsx`: Filterable table (by status, department, document type). Create button opens `DocumentForm`. Row click → edit view.
- `DocumentForm.jsx`: Create/edit form with all fields. Uses `PersonPicker` for owner. Uses `useCreateDocument` / `useUpdateDocument` hooks.

**RoleRegister/** — Similar:
- `index.jsx`: Table with unassigned roles highlighted. Assign button (calls `assign` endpoint).
- `RoleForm.jsx`: Full create/edit form.

**ComplianceCalendar/** — Obligations table:
- `index.jsx`: Sorted by due_date. Overdue items highlighted red. Filter by type, authority.
- `CalendarForm.jsx`: Obligation create/edit.

**ContractRegister/** — Contract table:
- `index.jsx`: Expiry date column, Expiring Soon warnings. Filter by status, type.
- `ContractForm.jsx`: Full create/edit.

**AIReviewQueue/index.jsx** — Three-tab interface (Zone 1 / Zone 2 / Zone 3). Each tab shows pending items with decision buttons. Zone 1 items show all extracted fields. Decision buttons trigger the corresponding queue API endpoints. Optimistic updates via React Query mutations.

**DocumentLifecycle/** — Lifecycle stage tracker. Visual stage indicator (Review → Sensitisation → Approval). File upload UI. Stage progression buttons.

**ControlRegister/index.jsx** — Table of confirmed controls with linked evidence count. Click to expand evidence items. Filter by ISO clause, control type.

**EvidenceTracker/** — Evidence item table with status filtering. Submit button (opens link input). Verify button (for Compliance Lead role). Status colour-coded.

**StandardsMap/index.jsx** — Grid of ISO clauses with traffic light icons. Click clause → drill-down showing all controls + evidence for that clause. Traffic light legend.

**StrategicRisks/** — Risk register table with risk score heat map colours. Create risk form with likelihood/impact sliders. Risk treatment notes.

**GapAnalysis/index.jsx** — Gap findings sorted by severity. Status badges. Remediation package accordion (expand to see full proposed remediation JSON). Accept Risk button → creates Strategic Risk entry.

**Harmonisation/index.jsx** — Variant control pairs from Zone 3 queue. Side-by-side comparison. Merge / Keep Separate / Rename actions.

**Extractor/index.jsx** — File upload interface. Document code input. Extract button → calls `extractFile` API. Shows extraction preview (complete vs deficient items). Write to SharePoint button.

**AssignmentOwnership/index.jsx** — Orphan resolution from Zone 2 queue. Shows orphan items with classification. Decision buttons.

---

## 7. Data Models & SharePoint Lists

All data is stored in SharePoint Online lists under `dragnetnigeria.sharepoint.com/sites/orgos`.

### SharePoint List Inventory

| List | Env Var | Purpose |
|---|---|---|
| Document Register | DOCUMENT_REGISTER_LIST_ID | Policy/procedure documents |
| Role Register | ROLE_REGISTER_LIST_ID | Roles and ownership |
| Compliance Calendar | COMPLIANCE_CALENDAR_LIST_ID | Statutory/regulatory obligations |
| Contract Register | CONTRACT_REGISTER_LIST_ID | Vendor contracts |
| AI Review Queue | AI_REVIEW_QUEUE_LIST_ID | Extraction staging (Zones 1/2/3) |
| Document Lifecycle | DOCUMENT_LIFECYCLE_LIST_ID | Document creation/review workflow |
| Control Register | CONTROL_REGISTER_LIST_ID | Confirmed active controls |
| Evidence Tracker | EVIDENCE_TRACKER_LIST_ID | Evidence collection items |
| Audit Log | AUDIT_LOG_LIST_ID | Immutable decision audit trail |
| Strategic Risk Register | STRATEGIC_RISK_REGISTER_LIST_ID | ExCo risk register |
| Gap Analysis | GAP_ANALYSIS_LIST_ID | Compliance gap findings |

### Person Field Pattern

Every person reference in SharePoint uses two columns:
- `{Field}EntraId` — Text column storing the Entra ID OID (always populated, used for all logic)
- `{Field}` — SharePoint Person/Group column (optional, kept in sync)

On **read**: OID → `resolve_user(oid)` → `{display_name, email}` → `PersonRef`
On **write**: Only the `{Field}EntraId` text column is written

### Soft Delete Pattern

**Nothing is hard-deleted.** All deletions set `Status = "Withdrawn"`. Audit trail is always preserved. The `soft_delete_list_item()` function enforces this.

### Status Calculation Pattern

Several statuses are **never stored in SharePoint** — they are pure functions calculated on every read:

- `ObligationStatus`: `_calculate_obligation_status(due_date)` — Overdue / Due Soon / Upcoming
- `ContractStatus` (partially): `_calculate_contract_status(end_date)` — Expiring Soon is calculated; Active/Expired/Terminated/Under Review can be stored
- `EvidenceStatus` (Overdue): calculated from `due_date < today AND status = Pending|Submitted`
- Standards Map traffic lights: fully recalculated on every request

---

## 8. Core Data Flows

### Flow 1: Document → Control Register (Full Pipeline)

```
1. User uploads PDF/DOCX to POST /api/v1/agents/extract/file
   OR clicks file in SharePoint browser → POST /api/v1/sharepoint/extract/{item_id}

2. Backend:
   a. Extract text (pypdf or python-docx)
   b. POST to Ollama /api/generate: classify document type
   c. If NON_EXTRACTION_TYPE → return skipped_reason, no items
   d. POST to Ollama /api/generate: extract {risk, control, evidence} triplets as JSON
   e. For each item:
      - _assign_control_type() using keyword rules
      - _suggest_evidence_type() using keyword rules
      - completeness_flag = COMPLETE if all required fields present, else DEFICIENT
   f. If write_to_sharepoint=True:
      - Write COMPLETE items to AI Review Queue (ReviewStatus="Pending Review", Zone 1)
   g. Return ExtractionResponse with all items + counts

3. Reviewer opens AI Review Queue → Zone 1 tab

4. Reviewer clicks "Accept Control" on a queue item:
   POST /api/v1/queue/{id}/accept-control
   
   Zone 1 CASCADE (atomic, all or nothing):
   a. Create Control Register item (status = Active)
   b. Create Evidence Tracker item (status = Pending, linked to new control)
   c. Create Audit Log entry (who accepted, when, what)
   d. Update Queue item (ReviewStatus = "Accepted", Decision = "Accepted")
   
   Returns: { control_id, evidence_id, audit_log_id }

5. Evidence owner:
   PATCH /api/v1/evidence/{id}/submit
   Body: { evidence_link: "https://...", submission_notes: "..." }
   Evidence status → Submitted

6. Compliance Lead:
   PATCH /api/v1/evidence/{id}/verify
   Body: { decision: "Accepted", reviewer_notes: "..." }
   Evidence status → Accepted

7. Standards Map automatically shows Green for the linked ISO clause
   (next time GET /api/v1/standards/map is called)
```

### Flow 2: Gap Analysis → Remediation → Risk

```
1. POST /api/v1/agents/gap-analysis/run (Compliance Lead only)
   
   Agent reads: Control Register + Evidence Tracker + Role Register
   For each ISO 27001/9001/NDPA clause:
   - No controls → Critical gap
   - Controls but no evidence → Major gap  
   - Evidence submitted not accepted → Minor gap
   
   Writes Gap Analysis items with proposed_remediation JSON

2. Compliance reviews gaps at GET /api/v1/gap-analysis

3a. If remediating:
    PATCH /api/v1/gap-analysis/{id}/status → "In progress"
    POST /api/v1/agents/draft-document (optional — AI drafts the remediation policy)
    → Triggers Document Lifecycle entry
    → When policy approved and controls accepted → gap closes

3b. If accepting as risk:
    POST /api/v1/gap-analysis/{id}/accept-risk
    → Creates Strategic Risk Register item (linked to gap)
    PATCH /api/v1/gap-analysis/{id}/status → "Accepted risk"
```

### Flow 3: Policy Drafting

```
1. POST /api/v1/agents/draft-document
   Body: { title, doc_type, department, notes, standards_mapping, trigger, linked_gap_id }

2. Backend:
   a. Generate doc_code (DRG-[DEPT]-[TYPE]-[REF]-[YY])
   b. POST to Ollama: generate CDI-structured policy text
   c. docx_builder.build_docx(draft) → BytesIO
   d. upload_file_to_sharepoint(docx_bytes, filename, "GRC MASTERY/Drafts") → webUrl
   e. create_list_item(document_lifecycle_list_id, {
        DocumentCode: doc_code,
        Stage: "Review",
        AIGenerated: true,
        SharePointFileUrl: webUrl,
        ...
      })

3. Returns: { lifecycle_id, doc_code, sections, full_text, sharepoint_url }

4. Lifecycle proceeds: Review → Sensitisation → Approval
   PATCH /api/v1/lifecycle/{id}/stage at each step
```

---

## 9. API Endpoint Reference

### No Auth Required
```
GET  /health
GET  /api/v1/health/graph
```

### GRC Tier 1 — all require auth
```
GET    /api/v1/grc/documents              ?status=&department=&document_type=
POST   /api/v1/grc/documents              201
GET    /api/v1/grc/documents/{id}
PATCH  /api/v1/grc/documents/{id}
DELETE /api/v1/grc/documents/{id}         (soft delete)

GET    /api/v1/grc/roles                  ?department=&assignment_status=
GET    /api/v1/grc/roles/unassigned
POST   /api/v1/grc/roles                  201
GET    /api/v1/grc/roles/{id}
PATCH  /api/v1/grc/roles/{id}
PATCH  /api/v1/grc/roles/{id}/assign
DELETE /api/v1/grc/roles/{id}

GET    /api/v1/grc/compliance             ?status=&type=&authority=
POST   /api/v1/grc/compliance             201
GET    /api/v1/grc/compliance/{id}
PATCH  /api/v1/grc/compliance/{id}
DELETE /api/v1/grc/compliance/{id}

GET    /api/v1/grc/contracts              ?status=&contract_type=
POST   /api/v1/grc/contracts              201
GET    /api/v1/grc/contracts/{id}
PATCH  /api/v1/grc/contracts/{id}
DELETE /api/v1/grc/contracts/{id}

GET    /api/v1/grc/users/resolve          ?email=
```

### Extraction & Agents
```
POST   /api/v1/agents/extract/text
POST   /api/v1/agents/extract/file        (multipart)
GET    /api/v1/agents/health/ollama

POST   /api/v1/agents/classify            (require_compliance_lead)
GET    /api/v1/agents/classify/status

POST   /api/v1/agents/draft-document
GET    /api/v1/agents/gap-analysis/run    (require_compliance_lead, POST)
GET    /api/v1/agents/gap-analysis/status
```

### SharePoint Browser
```
GET    /api/v1/sharepoint/browse
GET    /api/v1/sharepoint/browse/{folder_id}
POST   /api/v1/sharepoint/extract/{item_id}
```

### Review Queue
```
GET    /api/v1/queue                      ?zone=&review_status=&item_type=
GET    /api/v1/queue/{id}
POST   /api/v1/queue/{id}/accept-control
POST   /api/v1/queue/{id}/edit-accept
POST   /api/v1/queue/{id}/reject
POST   /api/v1/queue/{id}/route-to-owner
```

### Document Lifecycle
```
GET    /api/v1/lifecycle
GET    /api/v1/lifecycle/{id}
POST   /api/v1/lifecycle                  201
PATCH  /api/v1/lifecycle/{id}/stage
POST   /api/v1/lifecycle/{id}/upload
GET    /api/v1/lifecycle/documents/{id}/download
```

### Control Register
```
GET    /api/v1/controls                   ?document_id=&status=&iso_clause=
GET    /api/v1/controls/{id}
```

### Evidence Tracker
```
GET    /api/v1/evidence                   ?status=&control_id=&evidence_type=&owner_oid=
GET    /api/v1/evidence/{id}
PATCH  /api/v1/evidence/{id}/submit
PATCH  /api/v1/evidence/{id}/verify
```

### Standards Map
```
GET    /api/v1/standards/map
GET    /api/v1/standards/map/{clause_code}
```

### Strategic Risks
```
GET    /api/v1/risks                      (sorted by risk_score desc)
GET    /api/v1/risks/{id}
POST   /api/v1/risks                      201
PATCH  /api/v1/risks/{id}
```

### Gap Analysis
```
GET    /api/v1/gap-analysis               ?status=&standard=&severity=
GET    /api/v1/gap-analysis/{id}
POST   /api/v1/gap-analysis               201
PATCH  /api/v1/gap-analysis/{id}/status
POST   /api/v1/gap-analysis/{id}/accept-risk
```

---

## 10. AI & LLM Integration

### Ollama (Local LLM)

OrgOS uses **Ollama** running locally for all LLM inference. There is no call to OpenAI, Anthropic, or any cloud LLM API.

**Default model:** `llama3` (configurable via `OLLAMA_MODEL` env var). `llama3.2:1b` used in development for speed; `llama3` or `mistral` for better extraction quality.

**Ollama endpoint:** `http://localhost:11434/api/generate` (no authentication)

**Two LLM calls per extraction:**
1. `classify_document(text, folder_path)` → `DocumentType` — Determines which extraction schema to use
2. `run_extraction(text, doc_type, doc_code)` → `list[dict]` — Produces structured JSON items

**LLM call structure (Ollama /api/generate):**
```json
{
  "model": "llama3",
  "prompt": "<structured prompt with schema and examples>",
  "stream": false,
  "format": "json",
  "options": { "temperature": 0.1 }
}
```
Low temperature (0.1) is intentional — minimises hallucination in extraction tasks.

**Post-LLM keyword override:** After LLM extraction, `_assign_control_type()` and `_suggest_evidence_type()` override the LLM's classification using keyword rules. This is deliberate — keyword rules are more consistent for well-defined taxonomies.

**Non-LLM agents:** The Gap Analyzer and CDI Checker agents use deterministic logic against the Control Register and Evidence Tracker data, not LLM inference.

**Classifier agent:** Uses string matching + variant_terms from Role Register for deduplication logic, not LLM.

---

## 11. Authentication & Security

### Frontend → Backend (Entra ID JWTs)

1. User signs in via MSAL (`loginRequest` scopes: `openid profile email OrgOS.ReadWrite`)
2. MSAL caches tokens in `sessionStorage`
3. Every API call: Axios interceptor calls `msalInstance.acquireTokenSilent(apiTokenRequest)` → gets a fresh access token with scope `api://{CLIENT_ID}/OrgOS.ReadWrite`
4. Token attached as `Authorization: Bearer {token}`
5. FastAPI receives request → `validate_entra_id_token()`:
   - Fetches Microsoft JWKS (cached 2h)
   - Decodes RS256 JWT
   - Validates `iss`, `aud`, `tid` claims
   - Returns `CurrentUser` dataclass
6. All protected routes use `Depends(get_current_user)`
7. Agent trigger routes additionally use `Depends(require_compliance_lead)` (role check)

### Backend → Graph API (Client Credentials)

1. Backend calls `get_graph_access_token()` using client_credentials grant
2. Token cached in-process, refreshed 60s before expiry
3. On 401 response: `invalidate_token_cache()` + retry once
4. Token attached as `Authorization: Bearer {token}` on all Graph API calls

### SKIP_AUTH (Development Mode)

When `SKIP_AUTH=true` in `.env`:
- `get_current_user()` returns a hardcoded `CurrentUser(oid="dev-bypass-oid", roles=["OrgOS.Admin"])`
- No JWT validation occurs
- The frontend still authenticates with MSAL (this only bypasses backend validation)
- **Never set in production**

### Roles

Two application roles defined in the Entra app registration:
- `OrgOS.Admin` — Full access including agent triggers, verification
- `Compliance.Lead` — Agent triggers and evidence verification
- Standard users — Read/write registers, submit evidence

---

## 12. Configuration & Environment Variables

### Backend (.env)

```bash
# ── Azure Entra ID ──────────────────────────────────────────────
TENANT_ID=<directory-tenant-id>
CLIENT_ID=<app-registration-client-id>
CLIENT_SECRET=<client-secret-value>

# ── SharePoint ──────────────────────────────────────────────────
SHAREPOINT_SITE_ID=<site-guid-from-graph-api>
SHAREPOINT_SITE_URL=https://dragnetnigeria.sharepoint.com/sites/orgos
COMPLIANCE_SITE_URL=https://dragnetnigeria.sharepoint.com/sites/compliance
COMPLIANCE_LIBRARY_NAME=Documents
COMPLIANCE_STARTING_FOLDER=GRC MASTERY

# ── SharePoint List IDs (fill after creating lists) ─────────────
DOCUMENT_REGISTER_LIST_ID=placeholder
ROLE_REGISTER_LIST_ID=placeholder
COMPLIANCE_CALENDAR_LIST_ID=placeholder
CONTRACT_REGISTER_LIST_ID=placeholder
AI_REVIEW_QUEUE_LIST_ID=placeholder
DOCUMENT_LIFECYCLE_LIST_ID=placeholder
CONTROL_REGISTER_LIST_ID=placeholder
EVIDENCE_TRACKER_LIST_ID=placeholder
AUDIT_LOG_LIST_ID=placeholder
STRATEGIC_RISK_REGISTER_LIST_ID=placeholder
GAP_ANALYSIS_LIST_ID=placeholder

# ── Application ──────────────────────────────────────────────────
ENVIRONMENT=development
ALLOWED_ORIGINS=http://localhost:5173
APP_PORT=8000
LOG_LEVEL=DEBUG
SKIP_AUTH=false

# ── Ollama ───────────────────────────────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
```

### Frontend (.env.local)

```bash
VITE_AZURE_CLIENT_ID=<same-client-id-as-backend>
VITE_AZURE_TENANT_ID=<same-tenant-id-as-backend>
VITE_AZURE_REDIRECT_URI=http://localhost:5173
VITE_API_BASE_URL=http://localhost:8000
```

### Environment Precedence

pydantic-settings reads `.env` → environment variables override `.env` values. `extra="ignore"` means unknown vars don't crash the app.

---

## 13. Testing

### Test Framework

- **pytest** with `asyncio_mode = auto` (set in `pytest.ini`)
- All tests are async-first
- **respx** mocks all httpx calls — no real Graph API calls in the test suite
- Auth is bypassed in all tests via `mock_current_user` fixture

### Test Layout

```
tests/
├── conftest.py                  ← Global fixtures
├── test_graph_client.py         ← Token acquisition, caching, error scenarios
└── grc/
    ├── test_document_register.py
    ├── test_role_register.py
    ├── test_compliance_calendar.py
    └── test_contract_register.py
```

### Key Fixtures (conftest.py)

```python
@pytest.fixture
def mock_current_user():
    return CurrentUser(oid="test-oid-123", name="Test User", email="test@dragnet.com", 
                       tenant_id="test-tenant", roles=["OrgOS.Admin"])

@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}  # Bypassed in tests

@pytest.fixture
def mock_document_item():  # SharePoint item dict as Graph API returns it
    return {"id": "1", "fields": {"DocumentCode": "DRG-TEST-POL-01-26", ...}}

# Similar fixtures for: mock_role_item, mock_obligation_item_overdue, 
#                       mock_contract_item_expiring
```

### Test Patterns

**Graph client tests (test_graph_client.py):**
- Token caching: verify second call hits cache, not Graph
- 401 response: verify `invalidate_token_cache()` called + retry
- Exception types: 401→GraphAuthError, 403→GraphPermissionError, 404→GraphNotFoundError, 429→GraphRateLimitError, 503→GraphServiceUnavailableError

**Register tests:**
- CRUD round-trips against mocked Graph responses
- Status calculation accuracy:
  - Obligations: past due_date → Overdue, within 30d → Due Soon, future → Upcoming
  - Contracts: past end_date → Expired, within 60d → Expiring Soon, future → Active
- Schema validation (invalid enum values, missing required fields)
- Person field resolution (mock resolve_user returns expected PersonRef)

### Running Tests

```bash
# All tests
pytest -v

# Specific test file
pytest tests/grc/test_document_register.py -v

# With coverage
pytest --cov=grc --cov=graph --cov-report=term-missing

# Specific test function
pytest tests/test_graph_client.py::test_token_cache_hit -v
```

---

## 14. Scripts & Utilities

### scripts/bulk_extract.py — Batch Extraction

**Purpose:** Scan all documents in the SharePoint Compliance library and run extraction on each, with checkpoint/resume support.

**Features:**
- Traverses `GRC MASTERY` folder and all subfolders recursively
- Processes PDF, DOCX, TXT files
- Checkpoint file at `scripts/bulk_extract_checkpoint.json` tracks processed SharePoint item IDs
- Safe to interrupt and resume — already-processed items are skipped
- Writes COMPLETE extraction results to AI Review Queue

**Usage:**
```bash
python scripts/bulk_extract.py --dry-run              # Preview files, no extraction
python scripts/bulk_extract.py --folder "Policies"   # Single folder only
python scripts/bulk_extract.py                        # All folders
python scripts/bulk_extract.py --reset                # Clear checkpoint, start fresh
```

### scripts/sync_roles.py — Role Sync

**Purpose:** Synchronise roles from Entra ID, SeamlessHR, or BitWiseFlow into the Role Register.

**What it does:** Fetches current roles from source systems, compares with Role Register, creates/updates entries. Sets `SourceSystem` field to indicate provenance.

### scripts/cdi_triage.py — CDI Pre-Validation

**Purpose:** Run CDI compliance checks on documents before they enter the extraction pipeline.

**What it does:** Validates document code format, checks required metadata, flags CDI violations so they can be fixed before extraction produces deficient results.

---

## 15. Development Setup

### Prerequisites

```bash
# System (Debian/Ubuntu)
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nodejs npm git curl

# Node ≥ 18 (if needed)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 18 && nvm use 18

# Ollama (for extraction)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3
ollama serve    # Runs on http://localhost:11434
```

### Backend

```bash
cd /path/to/Orgos

# Create virtual environment
python3 -m venv orgos_env
source orgos_env/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env: fill in TENANT_ID, CLIENT_ID, CLIENT_SECRET, SHAREPOINT_SITE_ID
# Leave List IDs as "placeholder" until SharePoint lists are provisioned

# Run
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Swagger UI: http://localhost:8000/docs
# Health:     http://localhost:8000/health
```

### Frontend

```bash
cd frontend

npm install

cp .env.local.example .env.local
# Edit .env.local: fill in VITE_AZURE_CLIENT_ID, VITE_AZURE_TENANT_ID

npm run dev
# App: http://localhost:5173
```

### Azure App Registration (One-Time Setup)

1. Azure Portal → Entra ID → App registrations → New registration
2. Name: `OrgOS`, Account type: Single tenant, Redirect URI: `http://localhost:5173`
3. Note: **Application (client) ID** → `CLIENT_ID`; **Directory (tenant) ID** → `TENANT_ID`
4. Certificates & secrets → New client secret → copy Value → `CLIENT_SECRET`
5. API permissions → Add permission → Microsoft Graph → Application permissions:
   - `Sites.ReadWrite.All`
   - `User.Read.All`
   → Grant admin consent
6. Expose an API → Add scope: `OrgOS.ReadWrite` (for frontend token requests)
7. App roles → Add: `OrgOS.Admin`, `Compliance.Lead`

### Getting SharePoint Site ID

```bash
# After backend is running with valid credentials:
curl "https://graph.microsoft.com/v1.0/sites/dragnetnigeria.sharepoint.com:/sites/orgos" \
  -H "Authorization: Bearer $(python3 -c 'import asyncio; from graph.auth import get_graph_access_token; print(asyncio.run(get_graph_access_token()))')"
# Copy the "id" field → SHAREPOINT_SITE_ID
```

Or use Graph Explorer at `developer.microsoft.com/graph/graph-explorer`.

### SharePoint List Provisioning

Each SharePoint list must be created manually in the OrgOS SharePoint site with the correct column names as defined in `grc/constants.py`. After creation, copy each list's GUID into the corresponding `*_LIST_ID` variable in `.env`.

Column naming convention: columns use PascalCase (e.g., `DocumentCode`, `OwnerEntraId`, `AssignmentStatus`).

---

## 16. Key Architectural Decisions & Invariants

### 1. No Relational Database
SharePoint Lists are the single source of truth. All CRUD goes through the Graph API. This was chosen because:
- Dragnet already uses Microsoft 365 / SharePoint
- No separate DB infrastructure to manage
- SharePoint provides built-in access control, versioning, and audit trails
- Tradeoff: No joins, no transactions, no complex queries — all cross-list aggregation happens in Python

### 2. Async Throughout
Every I/O operation is `async/await`. The httpx client is opened once at startup and reused. This is a hard constraint — never use `requests`, `aiohttp`, or synchronous file I/O in the backend.

### 3. Pydantic v2 Only
The codebase is on Pydantic v2 API. Never use v1 APIs:
- `model_validate()` not `parse_obj()`
- `model_dump()` not `.dict()`
- `@field_validator` not `@validator`
- `Field(...)` for field definitions
- `model_config = SettingsConfigDict(...)` not class `Config`

### 4. Soft Delete Everywhere
`DELETE` endpoints never hard-delete. They call `soft_delete_list_item()` which sets `Status = "Withdrawn"`. This preserves audit trail. No exceptions.

### 5. Stateless Status Calculations
Obligation status (Overdue/Due Soon/Upcoming) and contract Expiring Soon are pure functions of date fields. They are recalculated on every read, never stored. This means no background job is needed to update statuses as time passes.

### 6. Token Caching Strategy
- Graph API tokens: in-process dict cache, 60s refresh buffer
- JWKS (Microsoft public keys): module-level cache, 2h TTL, auto-refreshes on kid-not-found
- User OID resolution: in-process cache per process restart

### 7. Keyword-Based Classification Trumps LLM
After Ollama produces extraction results, `_assign_control_type()` and `_suggest_evidence_type()` use keyword rules to override the LLM's values. Keyword rules are more consistent for the 16-item evidence taxonomy and 4-item control type taxonomy. The LLM's strength is in extracting the semantic content; the taxonomy assignment is better handled deterministically.

### 8. Evidence Taxonomy is Fixed
The 16 `EvidenceType` codes (LOG, CFG, APR, etc.) from DRG-QI-REF-EVTX-01-26 are the only permitted values. No free-text evidence types. This is enforced in both the Pydantic schema and extraction validation.

### 9. Zone-Based Review Queue
The queue has three logical zones with different decision workflows:
- Zone 1 (Extraction): Policy/contract controls → Control Register + Evidence Tracker cascade
- Zone 2 (Orphans): JD-sourced ownership issues → route to departments
- Zone 3 (Harmonisation): Classifier-identified variants → merge/separate/rename

### 10. Document Code Format
All documents follow: `DRG-[DEPT]-[TYPE]-[REF]-[YY]`
- `DEPT`: Department code (ISMS, HR, FIN, etc.)
- `TYPE`: Document type (POL=Policy, PRO=Procedure, SOP, FRM=Form, etc.)
- `REF`: Abbreviated reference code
- `YY`: Two-digit year

Role JD references follow: `DRG-JD-[DEPT]-[CODE]-[NN]`

---

## 17. Known Patterns & Conventions

### Backend Patterns

**All modules import settings from config.py:**
```python
from config import settings  # NOT: import os; os.environ.get(...)
```

**All Graph API calls through graph/client.py:**
```python
from graph import client as graph_client
items = await graph_client.get_list_items(settings.document_register_list_id, ...)
```

**All routes use Depends() for auth:**
```python
@router.get("/documents")
async def list_documents(user: CurrentUser = Depends(get_current_user)):
    ...
```

**Error conversion in routers:**
```python
try:
    result = await service.do_thing()
except GraphNotFoundError:
    raise HTTPException(status_code=404, detail="Item not found")
except GraphAuthError:
    raise HTTPException(status_code=401, detail="Authentication failed")
```

**Partial updates (PATCH):**
```python
update_data = {k: v for k, v in data.model_dump().items() if v is not None}
```

### Frontend Patterns

**All data fetching through React Query hooks:**
```javascript
const { data, isLoading, error } = useDocuments({ status: 'Active' });
```

**All mutations invalidate cache:**
```javascript
onSuccess: () => queryClient.invalidateQueries(['documents'])
```

**All API calls through grcApi.js** — never `fetch()` directly in components.

**Person fields always use PersonPicker component** — never a plain text input for owner fields.

### Naming Conventions

| Context | Convention | Example |
|---|---|---|
| Python files | snake_case | `document_register.py` |
| Python classes | PascalCase | `DocumentCreate` |
| Python functions | snake_case | `get_documents()` |
| SharePoint columns | PascalCase | `DocumentCode`, `OwnerEntraId` |
| Env vars | UPPER_SNAKE_CASE | `DOCUMENT_REGISTER_LIST_ID` |
| React components | PascalCase | `DocumentForm.jsx` |
| React hooks | camelCase with `use` prefix | `useDocuments()` |
| API routes | kebab-case | `/api/v1/gap-analysis` |

---

## 18. Current State & What's Built

### Fully Implemented & Tested

- **graph/** — Complete Graph API layer with all CRUD, user resolution, file ops, error hierarchy, token caching
- **auth/** — Full JWT validation, JWKS caching, CurrentUser, dev bypass
- **grc/** — All four Tier 1 registers (Document, Role, Compliance Calendar, Contract) with CRUD, schemas, service logic, router, and tests
- **config.py / main.py** — Full settings system, all routers mounted, lifespan, CORS

### Implemented, No Tests Yet

- **agents/extractor/** — Full extraction pipeline: file parsing, Ollama classify + extract, keyword-based post-processing, SharePoint write, router
- **agents/classifier/** — Harmonisation + dedup detection
- **agents/policy_drafter/** — AI draft generation + docx_builder + SharePoint upload + lifecycle entry
- **agents/gap_analyzer/** — Gap analysis vs standards
- **agents/cdi_checker/** — CDI compliance checking
- **review_queue/** — Zone 1/2/3 decision workflows with Zone 1 cascade
- **lifecycle/** — Document lifecycle stages, file upload/download
- **control_register/** — Confirmed control CRUD + evidence join
- **evidence_tracker/** — Evidence lifecycle (Pending → Submitted → Accepted/Rejected)
- **standards_map/** — Live traffic light calculation
- **strategic_risks/** — ExCo risk register with scoring
- **gap_analysis/** — Gap findings, remediation packages, risk escalation
- **sharepoint/** — File browser + extraction trigger

### Frontend

- Full React SPA with MSAL authentication
- All 14+ pages implemented (Tier 1 fully wired, Tier 2+ in various states of connection)
- Tier 1 registers (Document, Role, Compliance Calendar, Contract) fully connected
- AI Review Queue, Standards Map, Gap Analysis, Control Register pages implemented
- `Extractor/index.jsx` and `AssignmentOwnership/index.jsx` implemented but noted as "not fully wired in current prototype"

### Scripts

- `scripts/bulk_extract.py` — Checkpoint-based batch extraction
- `scripts/sync_roles.py` — Role sync from HR/identity systems
- `scripts/cdi_triage.py` — Pre-extraction CDI validation

### What Is Not Yet Built

Based on code state:
- No production deployment configuration (no Dockerfile, no docker-compose, no nginx config)
- No CI/CD pipeline configuration
- Tests only cover Tier 1 (grc/) and graph/ — agents, queue, lifecycle etc. have no tests
- No database migrations (not applicable — SharePoint is the store, but list schema provisioning scripts are absent)
- No monitoring/observability integration (no Prometheus metrics, no structured logging to external sink)
- Frontend has no build/deploy pipeline beyond `npm run build`
