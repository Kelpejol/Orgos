// =============================================================================
// api/grcApi.js — OrgOS GRC API client
// All HTTP calls to the FastAPI backend go through this module.
// Auth is the erp_auth HttpOnly cookie (set by the Dragnet ERP backend) — it
// travels automatically with every request; no token handling happens here.
// Depends on: axios
// =============================================================================

import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// =============================================================================
//  Axios instance
// =============================================================================

const apiClient = axios.create({
  baseURL: BASE_URL,
  withCredentials: true, // send the erp_auth cookie on every request
  headers: { "Content-Type": "application/json" },
  timeout: 1200000, // default — extraction endpoints override this per-call
});

/**
 * Response interceptor — normalises error messages from the backend.
 * FastAPI returns errors as { detail: "message" }.
 */
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error.response?.data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object"
          ? JSON.stringify(detail)
          : error.message || "An unexpected error occurred";

    return Promise.reject(new Error(message));
  },
);

// =============================================================================
//  Document Register
// =============================================================================

export const documentsApi = {
  /**
   * @param {{ status?: string, department?: string }} params
   * @returns {Promise<Array>}
   */
  list: (params = {}) =>
    apiClient.get("/api/v1/grc/documents", { params }).then((r) => r.data),

  /** @param {string} id */
  get: (id) => apiClient.get(`/api/v1/grc/documents/${id}`).then((r) => r.data),

  /** @param {Object} doc */
  create: (doc) =>
    apiClient.post("/api/v1/grc/documents", doc).then((r) => r.data),

  /**
   * @param {string} id
   * @param {Object} updates
   */
  update: (id, updates) =>
    apiClient.patch(`/api/v1/grc/documents/${id}`, updates).then((r) => r.data),

  /** @param {string} id */
  softDelete: (id) =>
    apiClient.delete(`/api/v1/grc/documents/${id}`).then((r) => r.data),
};

// =============================================================================
//  Compliance Calendar
// =============================================================================

export const complianceApi = {
  /** @param {{ type?: string, authority?: string }} params */
  list: (params = {}) =>
    apiClient.get("/api/v1/grc/compliance", { params }).then((r) => r.data),

  /** @param {string} id */
  get: (id) =>
    apiClient.get(`/api/v1/grc/compliance/${id}`).then((r) => r.data),

  /** @returns {Promise<Array>} Items with status=Overdue */
  listOverdue: () =>
    apiClient.get("/api/v1/grc/compliance/overdue").then((r) => r.data),

  /** @returns {Promise<Array>} Items due within 30 days */
  listDueSoon: () =>
    apiClient.get("/api/v1/grc/compliance/due-soon").then((r) => r.data),

  /** @param {Object} obligation */
  create: (obligation) =>
    apiClient.post("/api/v1/grc/compliance", obligation).then((r) => r.data),

  /**
   * @param {string} id
   * @param {Object} updates
   */
  update: (id, updates) =>
    apiClient
      .patch(`/api/v1/grc/compliance/${id}`, updates)
      .then((r) => r.data),

  /**
   * Mark an obligation as completed.
   * For recurring obligations, rolls the due date forward one period.
   * @param {string} id
   * @param {{ completion_notes?: string }} body
   */
  complete: (id, body = {}) =>
    apiClient
      .patch(`/api/v1/grc/compliance/${id}/complete`, body)
      .then((r) => r.data),

  /**
   * Escalate an overdue obligation to Gap Analysis.
   * Idempotent — repeated calls return the existing gap ID.
   * @param {string} id
   * @param {{ escalation_notes?: string }} body
   */
  escalate: (id, body = {}) =>
    apiClient
      .post(`/api/v1/grc/compliance/${id}/escalate`, body)
      .then((r) => r.data),

  /** @param {string} id */
  softDelete: (id) =>
    apiClient.delete(`/api/v1/grc/compliance/${id}`).then((r) => r.data),
};

// =============================================================================
//  Contract Register
// =============================================================================

export const contractsApi = {
  /** @param {{ type?: string, lifecycle_status?: string }} params */
  list: (params = {}) =>
    apiClient.get("/api/v1/grc/contracts", { params }).then((r) => r.data),

  /** @param {string} id */
  get: (id) => apiClient.get(`/api/v1/grc/contracts/${id}`).then((r) => r.data),

  /** @returns {Promise<Array>} Contracts expiring within 60 days */
  listExpiring: () =>
    apiClient.get("/api/v1/grc/contracts/expiring").then((r) => r.data),

  /** @param {Object} contract */
  create: (contract) =>
    apiClient.post("/api/v1/grc/contracts", contract).then((r) => r.data),

  /**
   * @param {string} id
   * @param {Object} updates
   */
  update: (id, updates) =>
    apiClient.patch(`/api/v1/grc/contracts/${id}`, updates).then((r) => r.data),

  /**
   * Update contract lifecycle status (Terminate, Under Review, Supersede).
   * Requires Compliance role.
   * @param {string} id
   * @param {string} lifecycleStatus — "Active" | "Under Review" | "Terminated" | "Superseded"
   */
  updateLifecycle: (id, lifecycleStatus) =>
    apiClient
      .patch(`/api/v1/grc/contracts/${id}/lifecycle`, JSON.stringify(lifecycleStatus), {
        headers: { "Content-Type": "application/json" },
      })
      .then((r) => r.data),

  /**
   * Create a Compliance Calendar obligation linked to this contract.
   * @param {string} id — contract SharePoint item ID
   * @param {Object} body — { obligation_name, type, authority, due_date, recurrence, owner_id, notes? }
   */
  addObligation: (id, body) =>
    apiClient
      .post(`/api/v1/grc/contracts/${id}/add-obligation`, body)
      .then((r) => r.data),

  /** @param {string} id */
  softDelete: (id) =>
    apiClient.delete(`/api/v1/grc/contracts/${id}`).then((r) => r.data),
};

// =============================================================================
//  Health checks
// =============================================================================

export const healthApi = {
  check: () => axios.get(`${BASE_URL}/health`).then((r) => r.data),
  checkGraph: () => apiClient.get("/api/v1/health/graph").then((r) => r.data),
  checkOllama: () =>
    apiClient.get("/api/v1/agents/health/ollama").then((r) => r.data),
};

export default apiClient;

// =============================================================================
//  NL Search (chatbot backend)
// =============================================================================

export const nlSearchApi = {
  /**
   * Send a question to the dual-mode NL Search pipeline.
   * @param {string} question
   * @param {string|null} sessionId  — informational, stored by frontend in IndexedDB
   * @returns {Promise<{mode, answer, sources, compliance_data, procedural_data, intent}>}
   */
  query: (question, sessionId = null, conversationHistory = []) =>
    apiClient
      .post('/api/v1/nl-search/query', {
        question,
        session_id:           sessionId,
        conversation_history: conversationHistory,
      })
      .then(r => r.data),

  /**
   * Health check — ChromaDB collections + embed model status.
   * No auth required.
   */
  health: () =>
    axios.get(`${BASE_URL}/api/v1/nl-search/health`).then(r => r.data),

  /**
   * Trigger a full index rebuild (Compliance role only).
   */
  rebuildIndex: () =>
    apiClient
      .post('/api/v1/nl-search/index/rebuild', { confirm: true })
      .then(r => r.data),
};

// =============================================================================
//  Extractor Agent
// =============================================================================

export const extractorApi = {
  /**
   * Upload a file and extract GRC controls from it.
   * @param {File} file — PDF, DOCX, or TXT
   * @param {string} sourceDocumentCode — e.g. DRG-ISMS-POL-ACP-01-25
   */
  extractFile: async (file, sourceDocumentCode) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("source_document_code", sourceDocumentCode);
    formData.append("write_to_sharepoint", "false");

    const BASE_URL =
      import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
    const response = await fetch(`${BASE_URL}/api/v1/agents/extract/file`, {
      method: "POST",
      credentials: "include",
      body: formData,
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Extraction failed: ${response.status}`);
    }

    return response.json();
  },

  /**
   * Extract from a file already in SharePoint.
   * Backend fetches the file bytes directly — no upload needed.
   */
  extractFromSharePoint: (itemId, sourceDocumentCode) =>
    apiClient
      .post(
        `/api/v1/sharepoint/extract/${itemId}`,
        {
          source_document_code: sourceDocumentCode,
          write_to_sharepoint: false,
        },
        { timeout: 300_000 }, // 5 minutes — extraction is slow on small GPU
      )
      .then((r) => r.data),

  /**
   * Submit a confirmed extraction item to the AI Review Queue staging list.
   * Becomes active when Tier 2 AI Review Queue list is created in SharePoint.
   */
  submitToQueue: (item, sourceDocumentCode) =>
    apiClient
      .post("/api/v1/agents/queue/submit", {
        ...item,
        source_document_code: sourceDocumentCode,
      })
      .then((r) => r.data),
};

// =============================================================================
//  Document Lifecycle
// =============================================================================

export const lifecycleApi = {
  list: (params) =>
    apiClient.get("/api/v1/lifecycle/documents", { params }),
  get: (id) =>
    apiClient.get(`/api/v1/lifecycle/documents/${id}`),
  create: (body) =>
    apiClient.post("/api/v1/lifecycle/documents", body),
  progress: (id, stage, body = {}) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/progress`, { current_stage: stage, ...body }),
  approve: (id, body) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/approve`, body),
  reject: (id, body) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/reject`, body),
  recall: (id) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/recall`),
  reassign: (id, body) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/reassign`, body),
  extendDeadline: (id, newDeadline) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/deadline`, { new_deadline: newDeadline }),
  updateFeedback: (id, feedback) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/feedback`, { feedback }),
  submitFeedback: (id, body) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/feedback/submit`, body),
  cdiFix: (id) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/cdi-fix-suggestions`),
  cdiFixPlan: (id) =>
    apiClient.get(`/api/v1/lifecycle/documents/${id}/cdi-fix/plan`),
  cdiFixApply: (id, fixes) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/cdi-fix/apply`, { fixes }),
  feedbackAiSuggestions: (id) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/feedback/ai-suggestions`),
  aiAssessment: (id) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/ai-assessment`),
  upload: async (id, file) => {
    const formData = new FormData();
    formData.append("file", file);
    const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
    const response = await fetch(`${BASE}/api/v1/lifecycle/documents/${id}/upload`, {
      method: "POST",
      credentials: "include",
      body: formData,
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Upload failed: ${response.status}`);
    }
    return response.json();
  },
  downloadUrl: (id) =>
    `${BASE_URL}/api/v1/lifecycle/documents/${id}/download`,
};

// =============================================================================
//  SharePoint File Browser
// =============================================================================

export const sharePointApi = {
  /**
   * Browse a folder in the Compliance GRC MASTERY library.
   * @param {string|null} folderId — null for root
   */
  browse: (folderId) => {
    const url = folderId
      ? `/api/v1/sharepoint/browse/${folderId}`
      : `/api/v1/sharepoint/browse`;
    return apiClient.get(url).then((r) => r.data);
  },
};

// =============================================================================
//  Org Roles — read-only directory of users and their org_roles, sourced
//  live from Entra ID. Compliance/OrgOS Admin only.
// =============================================================================

export const orgRolesApi = {
  list: () => apiClient.get("/api/v1/org-roles").then((r) => r.data),
};
