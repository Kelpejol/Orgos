# OrgOS — Dragnet Solutions Limited
**Internal Engineering | GRC Orchestration Module | DRG-AUTO-BRIEF-GRC-01-26**

---

## Project Structure

```
orgos/                              ← Root — open this folder in VS Code
├── .env                            ← YOUR secrets — never commit (gitignored)
├── .env.example                    ← Template — commit this
├── .gitignore
├── README.md
├── requirements.txt
├── pytest.ini
├── config.py                       ← All settings loaded from .env
├── main.py                         ← FastAPI app entry point
│
├── graph/                          ← Microsoft Graph API layer
│   ├── __init__.py
│   ├── auth.py                     ← Client credentials token acquisition + cache
│   ├── client.py                   ← Async httpx Graph API client (all CRUD)
│   └── exceptions.py               ← Graph API error types
│
├── auth/                           ← Entra ID token validation (incoming requests)
│   ├── __init__.py
│   └── validator.py                ← Validates bearer tokens from MSAL frontend
│
├── grc/                            ← GRC module — Tier 1 registers
│   ├── __init__.py
│   ├── constants.py                ← List IDs, field names, choice values
│   ├── schemas.py                  ← Pydantic v2 models for all 4 registers
│   ├── service.py                  ← Business logic — calls graph client
│   └── router.py                   ← FastAPI routes — /api/v1/grc/
│
├── agents/                         ← AI agents (Phase 3)
│   ├── __init__.py
│   └── extractor/
│       ├── __init__.py
│       ├── schemas.py              ← Extraction input/output models
│       ├── ollama_client.py        ← Ollama API client (local GPU)
│       ├── service.py              ← Extraction logic + SharePoint write
│       └── router.py               ← POST /api/v1/agents/extract
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 ← Fixtures, mock Graph responses
│   ├── test_graph_client.py
│   └── grc/
│       ├── __init__.py
│       ├── test_document_register.py
│       ├── test_role_register.py
│       ├── test_compliance_calendar.py
│       └── test_contract_register.py
│
└── frontend/                       ← Standalone React app
    ├── package.json
    ├── vite.config.js
    ├── index.html
    ├── .env.local                  ← YOUR frontend secrets (gitignored)
    ├── .env.local.example
    └── src/
        ├── main.jsx                ← React entry point (MSAL provider)
        ├── App.jsx                 ← Main app shell + navigation
        ├── authConfig.js           ← MSAL configuration
        ├── api/
        │   └── grcApi.js           ← All API calls to FastAPI
        ├── hooks/
        │   └── useGrc.js           ← React Query hooks
        ├── components/
        │   ├── layout/
        │   │   ├── Sidebar.jsx
        │   │   ├── TopBar.jsx
        │   │   └── Layout.jsx
        │   └── shared/
        │       ├── StatusBadge.jsx
        │       ├── LoadingState.jsx
        │       ├── PersonPicker.jsx
        │       └── Forms.jsx       ← Field, Btn, Link from prototype
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
            └── ContractRegister/
                ├── index.jsx
                └── ContractForm.jsx
```

---

## Prerequisites — Install on Debian

```bash
# 1. System packages
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nodejs npm git curl

# 2. Node version — must be 18+
node --version   # if below 18, install via nvm:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 18 && nvm use 18

# 3. Ollama (for Phase 3 — Extractor agent)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3          # or: ollama pull mistral
ollama serve                # runs on http://localhost:11434
```

---

## Backend Setup

```bash
# 1. Clone / open this folder in VS Code terminal

# 2. Create and activate virtual environment
python3 -m venv orgos_env
source orgos_env/bin/activate
# You should see (orgos_env) in your prompt

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your .env file
cp .env.example .env
# Open .env in VS Code and fill in your real values:
#   TENANT_ID, CLIENT_ID, CLIENT_SECRET — from Azure Portal
#   SHAREPOINT_SITE_ID — from Graph Explorer
# Leave List IDs as "placeholder" until SharePoint lists are created

# 5. Run the backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Backend is now live at: http://localhost:8000
# API docs (Swagger): http://localhost:8000/docs
# Health check: http://localhost:8000/health
```

---

## Frontend Setup

```bash
# 1. Open a NEW terminal in VS Code (keep backend running)
cd frontend

# 2. Install dependencies
npm install

# 3. Create your .env.local file
cp .env.local.example .env.local
# Open .env.local and fill in:
#   VITE_AZURE_CLIENT_ID — same Client ID as backend
#   VITE_AZURE_TENANT_ID — same Tenant ID as backend

# 4. Run the frontend
npm run dev

# Frontend is now live at: http://localhost:5173
```

---

## Running Tests

```bash
# From the orgos/ root with (orgos_env) activated:
pytest -v

# Run a specific test file:
pytest tests/grc/test_document_register.py -v

# Run with coverage:
pytest --cov=grc --cov=graph --cov-report=term-missing
```

---

## Azure App Registration Setup (One-Time)

1. Go to: https://portal.azure.com → Entra ID → App registrations → New registration
2. Name: `OrgOS`, Supported account types: Single tenant, Redirect URI: `http://localhost:5173`
3. After creation, note: **Application (client) ID** → `CLIENT_ID` and **Directory (tenant) ID** → `TENANT_ID`
4. Go to Certificates & secrets → New client secret → copy the **Value** → `CLIENT_SECRET`
5. Go to API permissions → Add permission → Microsoft Graph → Application permissions → Add: `Sites.ReadWrite.All`, `User.Read.All`
6. Click **Grant admin consent**

---

## Getting Your SharePoint Site ID

```bash
# With your credentials in .env, run this after backend starts:
curl "https://graph.microsoft.com/v1.0/sites/dragnet.sharepoint.com:/sites/orgos" \
  -H "Authorization: Bearer YOUR_TOKEN"
# Copy the "id" field into SHAREPOINT_SITE_ID in .env
```

Or use Graph Explorer: https://developer.microsoft.com/en-us/graph/graph-explorer

---

## Phase 3 — Extractor Agent (Ollama)

The extractor is ready to use once Ollama is running and Tier 1 is live:

```bash
# Test the extractor endpoint:
curl -X POST http://localhost:8000/api/v1/agents/extract/text \
  -H "Content-Type: application/json" \
  -d '{"text": "The ISMS Lead shall conduct quarterly access reviews...", "source_document_code": "DRG-ISMS-POL-ACP-01-25"}'

# Or upload a file:
curl -X POST http://localhost:8000/api/v1/agents/extract/file \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/policy.pdf" \
  -F "source_document_code=DRG-ISMS-POL-ACP-01-25"
```

---

## VS Code Recommended Extensions

Install these from the Extensions panel (Ctrl+Shift+X):
- Python (ms-python.python)
- Pylance (ms-python.vscode-pylance)
- ES7+ React/Redux/React-Native snippets
- Prettier - Code formatter
- REST Client (for .http test files)
- GitLens
