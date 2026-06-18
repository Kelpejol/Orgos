// =============================================================================
// pages/DocumentLifecycle/index.jsx
// Document Lifecycle — fully wired, all five entry types handled.
// Every action button works. New document form handles all scenarios.
// CDI Fix cards show the specific failures. Gap Remediation shows linked gap.
// Three-column kanban: Review → Sensitisation → Approval.
// =============================================================================

import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { LoadingState, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import UserSearchField from "../../components/shared/UserSearchField.jsx";
import apiClient from "../../api/grcApi.js";
import { useAiSuggestion } from "../../hooks/useAiSuggestion.js";

// =============================================================================
//  API layer
// =============================================================================

const lifecycleApi = {
  list: (stage, trigger) => {
    const params = {};
    if (stage)   params.stage   = stage;
    if (trigger) params.trigger = trigger;
    return apiClient.get("/api/v1/lifecycle/documents", { params }).then(r => r.data);
  },

  get: (id) =>
    apiClient.get(`/api/v1/lifecycle/documents/${id}`).then(r => r.data),

  create: (body) =>
    apiClient.post("/api/v1/lifecycle/documents", body).then(r => r.data),

  progress: (id, currentStage, extra = {}) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/progress`,
      { current_stage: currentStage, ...extra }).then(r => r.data),

  approve: (id, body = {}) =>
    apiClient.post(`/api/v1/lifecycle/documents/${id}/approve`, body).then(r => r.data),

  reassign: (id, ownerId, ownerName) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/reassign`,
      { owner_id: ownerId, owner_name: ownerName }).then(r => r.data),

  upload: async (id, file) => {
    // File upload requires multipart form — use fetch directly with MSAL token
    const { msalInstance } = await import("../../main.jsx");
    const { apiTokenRequest } = await import("../../authConfig.js");
    const accounts = msalInstance.getAllAccounts();
    if (!accounts.length) throw new Error("Not authenticated");
    let tokenResp;
    try {
      tokenResp = await msalInstance.acquireTokenSilent({ ...apiTokenRequest, account: accounts[0] });
    } catch {
      tokenResp = await msalInstance.acquireTokenPopup(apiTokenRequest);
    }
    const form = new FormData();
    form.append("file", file);
    const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
    const resp = await fetch(`${BASE}/api/v1/lifecycle/documents/${id}/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${tokenResp.accessToken}` },
      body: form,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Upload failed: ${resp.status}`);
    }
    return resp.json();
  },

  downloadUrl: (id) => {
    const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
    return `${BASE}/api/v1/lifecycle/documents/${id}/download`;
  },

  updateFeedback: (id, feedbackJson) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/feedback`, {
      feedback: feedbackJson,
    }).then(r => r.data),

  claim: (id) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/claim`).then(r => r.data),
};




async function authenticatedDownload(url, filename) {
  const { msalInstance } = await import("../../main.jsx");
  const { apiTokenRequest } = await import("../../authConfig.js");
 
  const accounts = msalInstance.getAllAccounts();
  if (!accounts.length) throw new Error("Not authenticated — please sign in.");
 
  let tokenResp;
  try {
    tokenResp = await msalInstance.acquireTokenSilent({
      ...apiTokenRequest,
      account: accounts[0],
    });
  } catch {
    tokenResp = await msalInstance.acquireTokenPopup(apiTokenRequest);
  }
 
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${tokenResp.accessToken}` },
  });
 
  if (!resp.ok) {
    let detail = `Download failed: ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch { /**/ }
    throw new Error(detail);
  }
 
  const blob = await resp.blob();
  const disposition = resp.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^;"'\n]+)/i);
  const resolvedName = match ? decodeURIComponent(match[1].trim()) : filename;
 
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = resolvedName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objectUrl);
}
 

// =============================================================================
//  Date helper — turns "2026-05-05T07:00:00Z" into "5 May 2026"
// =============================================================================

function fmtDate(str) {
  if (!str) return "—";
  try {
    const d = new Date(str);
    if (isNaN(d.getTime())) return str;
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return str;
  }
}

function dateOnlyDaysUntil(dateStr) {
  if (!dateStr) return { expired: false, daysLeft: null };
  const deadline = new Date(dateStr);
  if (Number.isNaN(deadline.getTime())) return { expired: false, daysLeft: null };

  const today = new Date();
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const deadlineStart = new Date(deadline.getFullYear(), deadline.getMonth(), deadline.getDate());
  const daysLeft = Math.round((deadlineStart - todayStart) / 86400000);

  return { expired: daysLeft < 0, daysLeft: Math.max(0, daysLeft) };
}

// =============================================================================
//  Feedback parser — handles both JSON (old OrgOS format) and plain text
//  [Name — Date, Time] marker format written by stakeholders/external systems.
// =============================================================================

function parseFeedback(raw) {
  if (!raw) return [];
  // Try JSON array {text, submittedBy, submittedAt}
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed[0]?.text) {
      return parsed.map(f => ({
        author:    f.submittedBy || "",
        timestamp: f.submittedAt ? fmtDate(f.submittedAt) : "",
        text:      f.text || "",
      }));
    }
  } catch { /**/ }
  // Parse [Name — Date, Time] marker format
  const entries = [];
  const headerRe = /^\[([^\]]+?)\s*[—–\-]\s*([^\]]+)\]$/;
  let current = null;
  for (const line of raw.split(/\r?\n/)) {
    const m = headerRe.exec(line.trim());
    if (m) {
      if (current) entries.push({ ...current, text: current.text.trim() });
      current = { author: m[1].trim(), timestamp: m[2].trim(), text: "" };
    } else if (current !== null) {
      current.text += (current.text ? "\n" : "") + line;
    }
  }
  if (current) entries.push({ ...current, text: current.text.trim() });
  if (!entries.length && raw.trim()) {
    return [{ author: "", timestamp: "", text: raw.trim() }];
  }
  return entries;
}

function parseJsonLike(value) {
  if (typeof value !== "string") return null;
  const cleaned = value
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/i, "");
  const candidates = [cleaned];
  const arrayMatch = cleaned.match(/\[[\s\S]*\]/);
  if (arrayMatch) candidates.push(arrayMatch[0]);
  const objectMatch = cleaned.match(/\{[\s\S]*\}/);
  if (objectMatch) candidates.push(objectMatch[0]);

  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch { /**/ }
  }
  return null;
}

function normalizeCdiSuggestions(value) {
  let payload = value?.suggestions ?? value;

  if (typeof payload === "string") {
    payload = parseJsonLike(payload) ?? [{ suggestion: payload }];
  }

  if (payload && !Array.isArray(payload) && typeof payload === "object") {
    payload = payload.suggestions || payload.fixes || payload.items || [payload];
  }

  if (!Array.isArray(payload)) return [];

  return payload.flatMap((item) => {
    if (typeof item === "string") {
      const parsed = parseJsonLike(item);
      return parsed ? normalizeCdiSuggestions(parsed) : [{ check: "General", finding: "See AI suggestion", suggestion: item }];
    }
    if (!item || typeof item !== "object") return [];

    const suggestion = item.suggestion ?? item.fix ?? item.proposed_fix ?? item.action ?? "";
    if (typeof suggestion === "string") {
      const parsedSuggestion = parseJsonLike(suggestion);
      if (Array.isArray(parsedSuggestion)) return normalizeCdiSuggestions(parsedSuggestion);
    }

    return [{
      check: String(item.check || item.check_id || item.id || "CDI"),
      finding: String(item.finding || item.detail || item.problem || ""),
      suggestion: typeof suggestion === "string" ? suggestion : JSON.stringify(suggestion),
    }];
  }).filter(s => s.finding || s.suggestion);
}

function lifecycleSortValue(doc) {
  const dateValue = Date.parse(doc.modified || doc.created || "");
  if (!Number.isNaN(dateValue)) return dateValue;
  const numericId = Number(doc.id);
  return Number.isNaN(numericId) ? 0 : numericId;
}

function sortNewestFirst(a, b) {
  return lifecycleSortValue(b) - lifecycleSortValue(a);
}

const FEEDBACK_PREVIEW = 160;

const FeedbackEntry = ({ entry }) => {
  const [expanded, setExpanded] = useState(false);
  const long = entry.text.length > FEEDBACK_PREVIEW;
  const display = expanded ? entry.text : entry.text.slice(0, FEEDBACK_PREVIEW);
  return (
    <div style={{
      padding: "10px 12px", background: "#FAECE7", borderRadius: 8,
      border: "0.5px solid #F0997B", fontSize: 11, color: "#712B13",
    }}>
      {(entry.author || entry.timestamp) && (
        <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 11, color: "#D85A30" }}>
          {entry.author}{entry.timestamp ? ` — ${entry.timestamp}` : ""}
        </div>
      )}
      <div style={{ lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
        {display}{long && !expanded ? "..." : ""}
      </div>
      {long && (
        <button onClick={() => setExpanded(e => !e)} style={{
          background: "none", border: "none", cursor: "pointer",
          color: "#D85A30", fontSize: 10, fontWeight: 600, padding: "4px 0 0",
        }}>
          {expanded ? "See less ▲" : "See more ▼"}
        </button>
      )}
    </div>
  );
};

// =============================================================================
//  Hooks
// =============================================================================

function useLifecycleDocs() {
  return useQuery({
    queryKey: ["lifecycle"],
    queryFn:  () => lifecycleApi.list(),
    staleTime: 30_000,
  });
}


// =============================================================================
//  Stage config
// =============================================================================

const STAGES = [
  { key: "Review",        color: "#BA7517", bg: "#FAEEDA", bd: "#FAC775",
    desc: "Drafting and revision — download, revise, upload, then progress" },
  { key: "Sensitisation", color: "#D85A30", bg: "#FAECE7", bd: "#F0997B",
    desc: "Audience briefing — staff are notified before the policy takes effect" },
  { key: "Approval",      color: "#993556", bg: "#FBEAF0", bd: "#E8A0BD",
    desc: "Awaiting sign-off — approver reviews and publishes via Teams" },
];

const TRIGGER_LABELS = {
  "Manual":              { color: "#595952", bg: "#F1EFE8", bd: "#B4B2A9" },
  "CDI Fix":             { color: "#A32D2D", bg: "#FCEBEB", bd: "#F09595" },
  "Scheduled Review":    { color: "#0C447C", bg: "#E6F1FB", bd: "#85B7EB" },
  "Gap Remediation":     { color: "#3C3489", bg: "#EEEDFE", bd: "#AFA9EC" },
  "Harmonisation Fix":   { color: "#3C3489", bg: "#EEEDFE", bd: "#AFA9EC" },
  "NC Corrective Action":{ color: "#791F1F", bg: "#FCEBEB", bd: "#F09595" },
  "Business":            { color: "#085041", bg: "#E1F5EE", bd: "#5DCAA5" },
};

// =============================================================================
//  Details modal
// =============================================================================

const DetailsModal = ({ doc, onClose }) => {
  if (!doc) return null;

  let cdiFailures = [];
  if (doc.CDIFailures) {
    try {
      cdiFailures = JSON.parse(doc.CDIFailures);
    } catch {
      cdiFailures = [{ check: "CDI", detail: doc.CDIFailures }];
    }
  }

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000,
               display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{ background: "var(--color-background-primary)", borderRadius: 14, padding: "24px 28px",
                 maxWidth: 540, width: "100%", maxHeight: "82vh", overflowY: "auto",
                 boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.4, marginBottom: 6 }}>
              {doc.Title || doc.DocumentCode || "Untitled document"}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <StatusBadge label={doc.Stage} />
              {doc.Trigger && <StatusBadge label={doc.Trigger} />}
              {doc.AIGenerated && <StatusBadge label="AI draft" />}
              {doc.Revised && <StatusBadge label="Revised" />}
            </div>
          </div>
          <button onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer",
                     fontSize: 20, color: "var(--color-text-tertiary)", lineHeight: 1 }}>×</button>
        </div>

        {/* Core fields */}
        {doc.DocumentCode && <Field l="Document code"  v={doc.DocumentCode} />}
        {doc.DocumentType  && <Field l="Document type"  v={doc.DocumentType} />}
        {doc.Department    && <Field l="Department"     v={doc.Department} />}
        <Field l="Stage"              v={doc.Stage} />
        <Field l="Owner"              v={doc.OwnerName || doc.OwnerEntraId || "—"} />
        <Field l="Trigger"            v={doc.Trigger} />
        <Field l="Days in stage"      v={`${Math.max(0, doc.DaysInStage || 0)}d`} />
        {doc.StandardsMapping && <Field l="Standards"   v={doc.StandardsMapping} />}
        {doc.LinkedNCId   && <Field l="Linked NC"        v={doc.LinkedNCId} />}
        {doc.ApprovalStatus && <Field l="Approval status" v={doc.ApprovalStatus} />}
        {doc.ApproverName   && <Field l="Approver"       v={doc.ApproverName} />}
        {doc.SubmittedForApproval && <Field l="Submitted for approval" v={fmtDate(doc.SubmittedForApproval)} />}
        {doc.ApprovedDate && <Field l="Approved date"    v={fmtDate(doc.ApprovedDate)} />}
        {doc.created && <Field l="Created"               v={fmtDate(doc.created)} />}
        {doc.Notes        && <Field l="Notes"            v={doc.Notes} />}
        {doc.RejectionReason && (
          <Field l="Rejection reason" v={doc.RejectionReason} color="#A32D2D" />
        )}

        {/* CDI failures */}
        {cdiFailures.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#A32D2D", marginBottom: 8 }}>
              CDI failures — fix these before progressing
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {cdiFailures.map((f, i) => (
                <div key={i} style={{
                  padding: "8px 12px", background: "#FCEBEB",
                  borderRadius: 8, fontSize: 12, color: "#791F1F",
                  border: "0.5px solid #F09595",
                }}>
                  <span style={{ fontWeight: 600 }}>{f.check}</span>
                  {f.detail && ` — ${f.detail}`}
                  {f.fix && (
                    <div style={{ marginTop: 3, fontSize: 11, fontStyle: "italic" }}>
                      Fix: {f.fix}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* SharePoint file link */}
        {doc.SharePointFileUrl && (
          <div style={{ marginTop: 14 }}>
            <a href={doc.SharePointFileUrl} target="_blank" rel="noreferrer"
              style={{ fontSize: 12, color: "var(--color-text-info)", textDecoration: "underline" }}>
              Open in SharePoint ↗
            </a>
          </div>
        )}

        <div style={{ marginTop: 18 }}>
          <button onClick={onClose}
            style={{ padding: "8px 16px", fontSize: 12, borderRadius: 8,
                     border: "1.5px solid #C0C0C0", background: "transparent",
                     color: "var(--color-text-secondary)", cursor: "pointer" }}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

// =============================================================================
//  New document form — Manual creation only.
//  All other triggers (Gap Remediation, Scheduled Review, CDI Fix, NC) are
//  created automatically by agents and Power Automate flows — never manually.
// =============================================================================

const DEPARTMENTS = [
  { code: "QI",   label: "QI — Quality & Information" },
  { code: "ISMS", label: "ISMS — Information Security" },
  { code: "HR",   label: "HR — Human Resources" },
  { code: "FIN",  label: "FIN — Finance & Admin" },
  { code: "REC",  label: "REC — Recruitment" },
  { code: "IT",   label: "IT — IT Support" },
  { code: "TES",  label: "TES — Testing Operations" },
  { code: "VER",  label: "VER — Verification" },
  { code: "CX",   label: "CX — Client Experience" },
  { code: "SD",   label: "SD — Software Development" },
  { code: "EX",   label: "EX — Executive" },
];

const DOC_TYPES = [
  { value: "Policy",    label: "Policy — defines what must happen and who is responsible" },
  { value: "Procedure", label: "Procedure — step-by-step instructions for how to do something" },
  { value: "Combined",  label: "Combined Policy & Procedure — policy and procedure in one document" },
  { value: "Manual",    label: "Manual — comprehensive reference document" },
  { value: "Guideline", label: "Guideline — advisory best practices (non-mandatory)" },
  { value: "Standard",  label: "Standard — technical specifications and requirements" },
  { value: "SLA",       label: "SLA — service level agreement obligations" },
];

const NewDocForm = ({ onSuccess, onCancel }) => {
  const { oid, name } = useCurrentUserRole();
  const qc = useQueryClient();
  const [form, setForm] = useState({
    title:             "",
    document_code:     "",
    document_type:     "Policy",
    department:        "",
    standards_mapping: "",
    notes:             "",
    ai_generated:      false,
  });
  const [saving,   setSaving]   = useState(false);
  const [error,    setError]    = useState("");
  const [aiResult, setAiResult] = useState(null); // holds draft API response after success

  const set = k => e => setForm(f => ({
    ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value,
  }));

  // Trigger a browser download from a base64-encoded docx string
  const downloadBase64Docx = (b64, filename) => {
    try {
      const bytes  = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      const blob   = new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
      const url    = URL.createObjectURL(blob);
      const a      = document.createElement("a");
      a.href       = url;
      a.download   = filename || "draft.docx";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      setError("Download failed — try again.");
    }
  };

  const handleCreate = async () => {
    if (!form.title.trim())  { setError("Document title is required."); return; }
    if (!form.document_type) { setError("Document type is required."); return; }
    if (!form.department)    { setError("Department is required."); return; }
    setSaving(true);
    setError("");
    try {
      if (form.ai_generated) {
        const resp = await apiClient.post("/api/v1/agents/draft-document", {
          title:             form.title.trim(),
          doc_type:          form.document_type,
          department:        form.department,
          notes:             form.notes.trim() || undefined,
          standards_mapping: form.standards_mapping.trim() || undefined,
          trigger:           "Manual",
        });
        // Store result to show inline success panel — no alert/copy-paste needed
        setAiResult(resp.data);
        qc.invalidateQueries({ queryKey: ["lifecycle"] });
        // Don't call onSuccess() yet — keep form visible to show the result panel
      } else {
        await lifecycleApi.create({
          title:             form.title.trim(),
          document_code:     form.document_code.trim() || undefined,
          document_type:     form.document_type,
          department:        form.department,
          trigger:           "Manual",
          ai_generated:      false,
          notes:             form.notes.trim() || undefined,
          standards_mapping: form.standards_mapping.trim() || undefined,
        });
        qc.invalidateQueries({ queryKey: ["lifecycle"] });
        onSuccess();
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to create. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const inp = {
    width: "100%", fontSize: 12, padding: "9px 11px", borderRadius: 8,
    border: "1.5px solid #D0D0D0", background: "var(--color-background-primary)",
    color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box",
    transition: "border-color 0.1s",
  };
  const lbl = {
    display: "block", fontSize: 11, fontWeight: 600,
    color: "var(--color-text-secondary)", marginBottom: 5,
    textTransform: "uppercase", letterSpacing: "0.5px",
  };
  const focus = e => (e.target.style.borderColor = "#378ADD");
  const blur  = e => (e.target.style.borderColor = "#D0D0D0");

  return (
    <div style={{
      padding: "20px", background: "var(--color-background-primary)",
      borderRadius: 14, border: "1.5px solid #378ADD",
      boxShadow: "0 4px 20px rgba(55,138,221,0.12)", marginBottom: 16,
    }}>
      {/* Form header */}
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 18 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 3 }}>
            New controlled document
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
            Creates a Review stage entry. Write or generate a draft, upload it, then progress to Sensitisation.
          </div>
        </div>
        <button onClick={onCancel}
          style={{ background: "none", border: "none", cursor: "pointer",
                   fontSize: 18, color: "var(--color-text-tertiary)", lineHeight: 1 }}>
          ×
        </button>
      </div>

      {error && (
        <div style={{ padding: "9px 12px", background: "#FCEBEB", border: "1px solid #F09595",
                      borderRadius: 8, fontSize: 12, color: "#791F1F", marginBottom: 14 }}>
          {error}
        </div>
      )}

      {/* Title — full width, most prominent */}
      <div style={{ marginBottom: 14 }}>
        <label style={lbl}>
          Document title <span style={{ color: "#A32D2D" }}>*</span>
        </label>
        <input
          type="text" value={form.title} onChange={set("title")}
          placeholder="e.g. Access Control Policy and Procedures"
          title="Full name of the document as it will appear in the Document Register and on the cover page."
          style={{ ...inp, fontSize: 13, padding: "10px 12px" }}
          onFocus={focus} onBlur={blur}
          autoFocus
        />
      </div>

      {/* Type and department — two columns */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
        <div>
          <label style={lbl}>
            Document type <span style={{ color: "#A32D2D" }}>*</span>
          </label>
          <select value={form.document_type} onChange={set("document_type")}
            title="Determines the type code in the document code (e.g. Policy → POL, Procedure → PRO) and controls what sections the AI generates."
            style={inp} onFocus={focus} onBlur={blur}>
            {DOC_TYPES.map(t => (
              <option key={t.value} value={t.value}>{t.value}</option>
            ))}
          </select>
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4, lineHeight: 1.4 }}>
            {DOC_TYPES.find(t => t.value === form.document_type)?.label.split(" — ")[1] || ""}
          </div>
        </div>
        <div>
          <label style={lbl}>
            Department <span style={{ color: "#A32D2D" }}>*</span>
          </label>
          <select value={form.department} onChange={set("department")}
            title="Sets the department code in the document code (e.g. SD, ISMS, HR) and scopes the document to the right team."
            style={inp} onFocus={focus} onBlur={blur}>
            <option value="">Select department...</option>
            {DEPARTMENTS.map(d => (
              <option key={d.code} value={d.code}>{d.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Document code and standards mapping — two columns */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
        <div>
          <label style={lbl}>Document code</label>
          <input
            type="text" value={form.document_code} onChange={set("document_code")}
            placeholder="Generated automatically — leave blank"
            title="Leave blank and the system generates a unique code from the department, type, and title. Only set this manually if you are continuing a pre-existing document series."
            style={{ ...inp, fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.3px" }}
            onFocus={focus} onBlur={blur}
          />
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4 }}>
            Will be: DRG-{form.department || "DEPT"}-
            {({ Policy:"POL", Procedure:"PRO", Combined:"POL", Manual:"MAN", Guideline:"GUI", Standard:"STD", SLA:"SLA" }[form.document_type] || "DOC")}
            -[SHORT]-[NN]-26
          </div>
        </div>
        <div>
          <label style={lbl}>Standards mapping</label>
          <input
            type="text" value={form.standards_mapping} onChange={set("standards_mapping")}
            placeholder="Defaults to ISO 27001, ISO 9001, NDPA"
            title="Which standards this document addresses. If left blank the system defaults to ISO 27001, ISO 9001, and NDPA. You can add specific clause references e.g. 'ISO 27001 A.5.18, NDPA S.39'."
            style={inp} onFocus={focus} onBlur={blur}
          />
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4 }}>
            Blank → defaults to ISO 27001, ISO 9001, NDPA
          </div>
        </div>
      </div>

      {/* Notes / brief */}
      <div style={{ marginBottom: 14 }}>
        <label style={lbl}>Brief / notes</label>
        <textarea
          value={form.notes} onChange={set("notes")}
          placeholder="What should this document cover? Scope, key controls, any specific requirements or context for the author..."
          title="Used as the brief when generating an AI draft. The more specific you are here, the better the output — e.g. 'covers user onboarding, password resets, and MFA enforcement for all cloud systems'."
          rows={3}
          style={{ ...inp, resize: "vertical", fontFamily: "var(--font-sans)", lineHeight: 1.5 }}
          onFocus={focus} onBlur={blur}
        />
      </div>

      {/* AI draft toggle */}
      <div style={{
        display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 16,
        padding: "10px 12px", background: form.ai_generated ? "#E1F5EE" : "var(--color-background-secondary)",
        borderRadius: 8, border: `1px solid ${form.ai_generated ? "#5DCAA5" : "var(--color-border-tertiary)"}`,
        cursor: "pointer", transition: "all 0.15s",
      }}
        onClick={() => setForm(f => ({ ...f, ai_generated: !f.ai_generated }))}
      >
        <input type="checkbox" checked={form.ai_generated} readOnly
          style={{ cursor: "pointer", marginTop: 1, flexShrink: 0 }} />
        <div>
          <div style={{ fontSize: 12, fontWeight: 500,
                        color: form.ai_generated ? "#085041" : "var(--color-text-primary)" }}>
            Generate first draft with Document Drafter
          </div>
          <div style={{ fontSize: 11, color: form.ai_generated ? "#085041" : "var(--color-text-secondary)",
                        marginTop: 2, opacity: 0.85 }}>
            Document Drafter agent generates a CDI-compliant first draft using the type, department, and brief above. Takes 30–60 seconds. The draft is not uploaded anywhere — you download it, revise it, then upload your final version.
          </div>
        </div>
      </div>

      {/* Owner — auto-resolved */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "8px 12px", background: "#E1F5EE", borderRadius: 8,
        border: "0.5px solid #5DCAA5", marginBottom: 18,
      }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#085041" }}>Owner</div>
          <div style={{ fontSize: 11, color: "#085041", opacity: 0.85 }}>
            {name || "You"} — resolved from Microsoft 365
          </div>
        </div>
        <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4,
                       background: "#5DCAA5", color: "#fff", fontWeight: 500 }}>
          Auto
        </span>
      </div>

      {/* Document Drafter success panel — shown after the agent responds */}
      {aiResult && (
        <div style={{
          padding: "14px 16px", background: "#E1F5EE", borderRadius: 10,
          border: "1px solid #5DCAA5", marginBottom: 14,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#085041", marginBottom: 2 }}>
                Draft created — {aiResult.doc_code}
              </div>
              <div style={{ fontSize: 11, color: "#085041", opacity: 0.85 }}>
                Review card is now in the Review column. Download the .docx, revise it, then upload it back.
              </div>
            </div>
            <button onClick={() => { setAiResult(null); onSuccess(); }}
              style={{ background: "none", border: "none", cursor: "pointer",
                       fontSize: 16, color: "#085041", lineHeight: 1 }}>×</button>
          </div>

          {/* CDI check results */}
          {aiResult.cdi_check && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6,
                            color: aiResult.cdi_check.status === "Passed" ? "#085041"
                                 : aiResult.cdi_check.status === "Failed" ? "#A32D2D" : "#BA7517" }}>
                CDI check: {aiResult.cdi_check.status}
                {" "}({aiResult.cdi_check.pass_count} passed, {aiResult.cdi_check.fail_count} failed)
              </div>
              {aiResult.cdi_check.failures.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  {aiResult.cdi_check.failures.map((f, i) => (
                    <div key={i} style={{
                      padding: "7px 10px", background: "#FCEBEB", borderRadius: 7,
                      border: "0.5px solid #F09595", fontSize: 11, color: "#791F1F",
                    }}>
                      <span style={{ fontWeight: 600 }}>{f.check}</span> — {f.detail}
                      {f.fix && (
                        <div style={{ fontSize: 10, fontStyle: "italic", marginTop: 3, color: "#A32D2D" }}>
                          Fix: {f.fix}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Download .docx */}
          <div style={{ marginBottom: 10, fontSize: 11, color: "#085041", opacity: 0.8, lineHeight: 1.5 }}>
            The draft is <strong>not yet on SharePoint</strong>. Download it, make your changes, then come back and use the Upload button on the lifecycle card to submit your revised version.
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {aiResult.docx_base64 && (
              <button
                onClick={() => downloadBase64Docx(aiResult.docx_base64, aiResult.filename)}
                style={{
                  padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "none",
                  background: "#085041", color: "#fff", cursor: "pointer", fontWeight: 600,
                }}
              >
                Download .docx ↓
              </button>
            )}
            <button
              onClick={() => { setAiResult(null); onSuccess(); }}
              style={{
                padding: "8px 14px", fontSize: 12, borderRadius: 8,
                border: "1.5px solid #C0C0C0", background: "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Actions — hide once AI result is shown */}
      {!aiResult && <div style={{ display: "flex", gap: 10 }}>
        <button
          onClick={handleCreate}
          disabled={saving || !form.title.trim() || !form.department}
          style={{
            flex: 1, padding: "11px", fontSize: 13, borderRadius: 9,
            border: "none", fontWeight: 600,
            background: saving || !form.title.trim() || !form.department
              ? "#E8E8E8" : "#1D9E75",
            color: saving || !form.title.trim() || !form.department ? "#999" : "#fff",
            cursor: saving || !form.title.trim() || !form.department ? "not-allowed" : "pointer",
            transition: "background 0.15s",
          }}
        >
          {saving
            ? (form.ai_generated ? "Drafting with AI... (may take 30–60s)" : "Creating...")
            : "Create and enter Review →"}
        </button>
        <button onClick={onCancel}
          style={{ padding: "11px 18px", fontSize: 13, borderRadius: 9,
                   border: "1.5px solid #D0D0D0", background: "transparent",
                   color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Cancel
        </button>
      </div>}
    </div>
  );
};

// =============================================================================
//  Lifecycle card
// =============================================================================

// const LifecycleCard = ({
//   doc, stageConfig, currentUserOid,
//   onViewDetails, onProgress, onUpload, onReassign,
//   progressPending,
// }) => {
//   const uploadRef  = useRef();
//   const [uploading, setUploading] = useState(false);
//   const [uploadError, setUploadError] = useState("");
//   const [showFeedback, setShowFeedback] = useState(false);
//   const [feedbackText, setFeedbackText] = useState("");
//   const [submittingFeedback, setSubmittingFeedback] = useState(false);
//   const qc = useQueryClient();

//   const isOwner    = doc.OwnerEntraId === currentUserOid;
//   const daysIn     = doc.DaysInStage || 0;
//   const isStalled  = daysIn > 14;
//   const canProgress= isOwner && doc.Revised;
//   const isSensitisation = doc.Stage === "Sensitisation";
//   const triggerStyle = TRIGGER_LABELS[doc.Trigger] || TRIGGER_LABELS["Manual"];

//   // CDI failures parsed
//   let cdiCount = 0;
//   if (doc.CDIFailures) {
//     try {
//       const parsed = JSON.parse(doc.CDIFailures);
//       cdiCount = Array.isArray(parsed) ? parsed.length : 1;
//     } catch { cdiCount = 1; }
//   }

//   // Parse sensitisation feedback
//   let feedbackItems = [];
//   if (doc.SensitisationFeedback) {
//     try {
//       feedbackItems = JSON.parse(doc.SensitisationFeedback);
//     } catch {
//       feedbackItems = [];
//     }
//   }

//   const handleFileSelect = async (e) => {
//     const file = e.target.files[0];
//     if (!file) return;
//     setUploading(true);
//     setUploadError("");
//     try {
//       await lifecycleApi.upload(doc.id, file);
//       qc.invalidateQueries({ queryKey: ["lifecycle"] });
//     } catch (err) {
//       setUploadError(err.message || "Upload failed");
//     } finally {
//       setUploading(false);
//       if (uploadRef.current) uploadRef.current.value = "";
//     }
//   };

//   const handleSubmitFeedback = async () => {
//     if (!feedbackText.trim()) return;
//     setSubmittingFeedback(true);
//     try {
//       const existing = feedbackItems;
//       const newEntry = {
//         text:      feedbackText.trim(),
//         submittedAt: new Date().toISOString(),
//         submittedBy: "You",
//       };
//       const updated = [...existing, newEntry];
//       await lifecycleApi.updateFeedback(doc.id, JSON.stringify(updated));
//       qc.invalidateQueries({ queryKey: ["lifecycle"] });
//       setFeedbackText("");
//       setShowFeedback(false);
//     } catch (err) {
//       setUploadError(err.message || "Failed to submit feedback.");
//     } finally {
//       setSubmittingFeedback(false);
//     }
//   };

//   return (
//     <div style={{
//       background: "var(--color-background-primary)",
//       border: isOwner ? `1.5px solid ${stageConfig.color}` : "1px solid #D0D0D0",
//       borderRadius: 12, padding: "10px 12px",
//       boxShadow: isStalled ? `0 0 0 2px #F09595` : "none",
//     }}>
//       {/* Your action badge */}
//       {isOwner && (
//         <div style={{ fontSize: 9, fontWeight: 600, color: stageConfig.color,
//                       marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.5px" }}>
//           Your action
//         </div>
//       )}

//       {/* Title + View details link */}
//       <div style={{ display: "flex", justifyContent: "space-between",
//                     alignItems: "flex-start", marginBottom: 6, gap: 8 }}>
//         <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4, flex: 1 }}>
//           {doc.Title || doc.DocumentCode || "Untitled document"}
//         </div>
//         <span
//           role="button" tabIndex={0}
//           onClick={() => onViewDetails(doc)}
//           onKeyDown={e => e.key === "Enter" && onViewDetails(doc)}
//           style={{ fontSize: 11, color: "var(--color-text-tertiary)",
//                    textDecoration: "underline", cursor: "pointer",
//                    flexShrink: 0, marginTop: 2, userSelect: "none" }}
//         >
//           View details
//         </span>
//       </div>

//       {/* Badges row */}
//       <div style={{ display: "flex", gap: 4, marginBottom: 6, flexWrap: "wrap" }}>
//         {doc.Trigger && (
//           <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, fontWeight: 500,
//                          background: triggerStyle.bg, color: triggerStyle.color,
//                          border: `0.5px solid ${triggerStyle.bd}` }}>
//             {doc.Trigger}
//           </span>
//         )}
//         {doc.AIGenerated  && <StatusBadge label="AI draft" />}
//         {doc.Revised      && <StatusBadge label="Revised" />}
//         {doc.DocumentType && <StatusBadge label={doc.DocumentType} />}
//       </div>

//       {/* CDI failure notice */}
//       {cdiCount > 0 && (
//         <div style={{ padding: "6px 10px", background: "#FCEBEB", borderRadius: 6,
//                       fontSize: 11, color: "#791F1F", marginBottom: 8 }}>
//           {cdiCount} CDI failure{cdiCount > 1 ? "s" : ""} to fix — click View details
//         </div>
//       )}

//       {/* Gap link */}
//       {doc.LinkedGapId && (
//         <div style={{ fontSize: 10, color: "#3C3489", marginBottom: 6 }}>
//           Gap: {doc.LinkedGapId}
//         </div>
//       )}

//       {/* Upload error */}
//       {uploadError && (
//         <div style={{ padding: "5px 8px", background: "#FCEBEB", borderRadius: 6,
//                       fontSize: 11, color: "#791F1F", marginBottom: 6 }}>
//           Upload failed: {uploadError}
//         </div>
//       )}

//       {/* Action buttons — owner only */}
//       {isOwner && (
//         <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginTop: 6 }}>

//           {/* Download */}
//           <a
//             href={doc.SharePointFileUrl || lifecycleApi.downloadUrl(doc.id)}
//             target="_blank"
//             rel="noreferrer"
//             style={{
//               padding: "7px", fontSize: 11, borderRadius: 7,
//               border: "1.5px solid #C0C0C0", background: "transparent",
//               color: "var(--color-text-primary)", cursor: "pointer",
//               textDecoration: "none", textAlign: "center",
//               display: "block",
//             }}
//           >
//             Download ↓
//           </a>

//           {/* Upload */}
//           <div>
//             <input
//               ref={uploadRef} type="file"
//               accept=".pdf,.docx,.doc"
//               style={{ display: "none" }}
//               onChange={handleFileSelect}
//             />
//             <button
//               onClick={() => uploadRef.current?.click()}
//               disabled={uploading}
//               style={{
//                 width: "100%", padding: "7px", fontSize: 11, borderRadius: 7,
//                 border: "1.5px solid #C0C0C0", background: "transparent",
//                 color: uploading ? "#999" : "var(--color-text-primary)",
//                 cursor: uploading ? "not-allowed" : "pointer",
//               }}
//             >
//               {uploading ? "Uploading..." : "Upload ↑"}
//             </button>
//           </div>

//           {/* Reassign */}
//           <button
//             onClick={() => onReassign(doc)}
//             style={{
//               padding: "7px", fontSize: 11, borderRadius: 7,
//               border: "1.5px solid #C0C0C0", background: "transparent",
//               color: "var(--color-text-secondary)", cursor: "pointer",
//             }}
//           >
//             Reassign
//           </button>

//           {/* Progress */}
//           <button
//             onClick={() => canProgress && onProgress(doc.id, doc.Stage)}
//             disabled={!canProgress || progressPending}
//             title={!canProgress ? "Upload a revised version to unlock Progress" : undefined}
//             style={{
//               padding: "7px", fontSize: 11, borderRadius: 7, fontWeight: 500,
//               border: canProgress && !progressPending ? "none" : "1.5px solid #E0E0E0",
//               background: canProgress && !progressPending ? stageConfig.color : "transparent",
//               color: canProgress && !progressPending ? "#fff" : "#B0B0B0",
//               cursor: canProgress && !progressPending ? "pointer" : "not-allowed",
//             }}
//           >
//             {progressPending ? "Moving..." : "Progress →"}
//           </button>
//         </div>
//       )}

//       {/* Sensitisation feedback panel */}
//       {isSensitisation && (
//         <div style={{ marginTop: 10 }}>
//           {/* Collected feedback */}
//           {feedbackItems.length > 0 && (
//             <div style={{ marginBottom: 8 }}>
//               <div style={{ fontSize: 10, fontWeight: 600, color: "#D85A30",
//                             textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6 }}>
//                 Feedback received ({feedbackItems.length})
//               </div>
//               <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
//                 {feedbackItems.map((fb, i) => (
//                   <div key={i} style={{
//                     padding: "7px 10px", background: "#FAECE7", borderRadius: 7,
//                     border: "0.5px solid #F0997B", fontSize: 11, color: "#712B13",
//                   }}>
//                     <div style={{ lineHeight: 1.4 }}>{fb.text}</div>
//                     <div style={{ fontSize: 10, opacity: 0.7, marginTop: 2 }}>
//                       {fb.submittedBy} · {fb.submittedAt
//                         ? new Date(fb.submittedAt).toLocaleDateString("en-GB", {
//                             day: "numeric", month: "short", year: "numeric",
//                           })
//                         : ""}
//                     </div>
//                   </div>
//                 ))}
//               </div>
//             </div>
//           )}

//           {/* Submit feedback button — visible to all, not just owner */}
//           {!showFeedback && (
//             <button
//               onClick={() => setShowFeedback(true)}
//               style={{
//                 width: "100%", padding: "7px", fontSize: 11, borderRadius: 7,
//                 border: "1.5px solid #F0997B", background: "transparent",
//                 color: "#D85A30", cursor: "pointer", fontWeight: 500,
//               }}
//             >
//               + Add feedback or comment
//             </button>
//           )}

//           {showFeedback && (
//             <div style={{ padding: "10px 12px", background: "#FAECE7",
//                           borderRadius: 8, border: "1px solid #F0997B" }}>
//               <div style={{ fontSize: 11, fontWeight: 600, color: "#D85A30", marginBottom: 6 }}>
//                 Your feedback on this document
//               </div>
//               <textarea
//                 value={feedbackText}
//                 onChange={e => setFeedbackText(e.target.value)}
//                 placeholder="What needs to change? Any concerns, suggestions, or comments for the document owner..."
//                 rows={3}
//                 style={{
//                   width: "100%", fontSize: 11, padding: "8px 10px", borderRadius: 7,
//                   border: "1.5px solid #F0997B", background: "var(--color-background-primary)",
//                   color: "var(--color-text-primary)", resize: "vertical",
//                   fontFamily: "var(--font-sans)", outline: "none",
//                   boxSizing: "border-box", marginBottom: 8,
//                 }}
//                 onFocus={e => (e.target.style.borderColor = "#D85A30")}
//                 onBlur={e => (e.target.style.borderColor = "#F0997B")}
//               />
//               <div style={{ display: "flex", gap: 6 }}>
//                 <button
//                   onClick={handleSubmitFeedback}
//                   disabled={!feedbackText.trim() || submittingFeedback}
//                   style={{
//                     padding: "7px 14px", fontSize: 11, borderRadius: 7, border: "none",
//                     fontWeight: 500,
//                     background: !feedbackText.trim() || submittingFeedback ? "#E8E8E8" : "#D85A30",
//                     color: !feedbackText.trim() || submittingFeedback ? "#999" : "#fff",
//                     cursor: !feedbackText.trim() || submittingFeedback ? "not-allowed" : "pointer",
//                   }}
//                 >
//                   {submittingFeedback ? "Submitting..." : "Submit feedback"}
//                 </button>
//                 <button
//                   onClick={() => { setShowFeedback(false); setFeedbackText(""); }}
//                   style={{ padding: "7px 12px", fontSize: 11, borderRadius: 7,
//                            border: "1.5px solid #C0C0C0", background: "transparent",
//                            color: "var(--color-text-secondary)", cursor: "pointer" }}
//                 >
//                   Cancel
//                 </button>
//               </div>
//             </div>
//           )}
//         </div>
//       )}

//       {/* Footer */}
//       <div style={{ display: "flex", justifyContent: "space-between",
//                     fontSize: 11, marginTop: isOwner ? 8 : 4 }}>
//         <span style={{ color: "var(--color-text-secondary)" }}>
//           {doc.OwnerName || "Unassigned"}
//         </span>
//         <span style={{ color: isStalled ? "#A32D2D" : "var(--color-text-tertiary)",
//                        fontWeight: isStalled ? 500 : 400 }}>
//           {daysIn}d {isStalled && "— stalled"}
//         </span>
//       </div>
//     </div>
//   );
// };


const LifecycleCard = ({
  doc, stageConfig, currentUserOid,
  onViewDetails, onProgressClick, onReassign, onApprove,
}) => {
  const uploadRef  = useRef();
  const navigate   = useNavigate();
  const [uploading,       setUploading]       = useState(false);
  const [uploadError,     setUploadError]     = useState("");
  const [uploadCdiResult, setUploadCdiResult] = useState(null);
  const [downloading,     setDownloading]     = useState(false);
  const [downloadError,   setDownloadError]   = useState("");
  const cdiFix = useAiSuggestion(
    doc.id,
    'cdi_fix',
    () => apiClient.post(`/api/v1/lifecycle/documents/${doc.id}/cdi-fix-suggestions`).then(r => r.data),
  );
  const [claiming,        setClaiming]        = useState(false);
  const [claimError,      setClaimError]      = useState("");
  const qc = useQueryClient();

  const isOwner         = doc.OwnerEntraId === currentUserOid;
  const isUnowned       = !doc.OwnerEntraId;
  const daysIn          = Math.max(0, doc.DaysInStage || 0);
  const isStalled       = daysIn > 14;
  const isReview        = doc.Stage === "Review";
  const isSensitisation = doc.Stage === "Sensitisation";
  const isApproval      = doc.Stage === "Approval";
  const isApproved      = doc.ApprovalStatus === "Approved";
  const needsUpload     = isReview && !doc.Revised && !doc.SharePointFileUrl;
  // CDI gate temporarily disabled: keep CDI results visible, but allow progress
  // while onboarding legacy documents.
  // const canProgress  = isOwner && !needsUpload && !isApproval && doc.CDIStatus !== "Failed";
  const canProgress     = isOwner && !needsUpload && !isApproval;
  const triggerStyle    = TRIGGER_LABELS[doc.Trigger] || TRIGGER_LABELS["Manual"];

  // Sensitisation deadline helpers
  const dlDeadline = doc.SensitisationDeadline;
  const dlStatus = dateOnlyDaysUntil(dlDeadline);
  const dlExpired  = dlDeadline && dlStatus.expired;
  const dlDaysLeft = dlDeadline ? dlStatus.daysLeft : 0;

  const handleGetCdiFix = () => cdiFix.hasSuggestion ? cdiFix.regenerate() : cdiFix.generate();

  let cdiCount = 0;
  if (doc.CDIFailures) {
    try {
      const parsed = JSON.parse(doc.CDIFailures);
      cdiCount = Array.isArray(parsed) ? parsed.length : 1;
    } catch { cdiCount = 1; }
  }

  const feedbackEntries = parseFeedback(doc.SensitisationFeedback);
  const aiFixSuggestions = normalizeCdiSuggestions(cdiFix.suggestion);
  const stakeholderCount = (doc.Stakeholders || []).length;
  const hasStakeholders = stakeholderCount > 0;
 
  // ── Upload — CDI check runs server-side on every upload ────────────────────
  const handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setUploadError("");
    setUploadCdiResult(null);
    try {
      const updated = await lifecycleApi.upload(doc.id, file);
      // Surface the CDI result immediately from the upload response
      if (updated?.CDIStatus) {
        let failCount   = 0;
        let errorDetail = "";
        if (updated.CDIFailures) {
          try {
            const parsed = JSON.parse(updated.CDIFailures);
            failCount = parsed.length;
            // For Error status, grab the human-readable reason from the first entry
            if (updated.CDIStatus === "Error" && parsed[0]?.detail) {
              errorDetail = parsed[0].detail;
            }
          } catch { failCount = 1; }
        }
        setUploadCdiResult({ status: updated.CDIStatus, failCount, errorDetail });
      }
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
    } catch (err) {
      setUploadError(err.message || "Upload failed");
    } finally {
      setUploading(false);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  };
 
  // ── Download — authenticated fetch, never a bare <a href> ──────────────────
  const handleDownload = async () => {
    setDownloading(true);
    setDownloadError("");
    try {
      const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
      const filename = `${doc.DocumentCode || doc.id}_v1.0_DRAFT.docx`;
 
      if (doc.SharePointFileUrl) {
        // File already lives in SharePoint — the user is authenticated via
        // their M365 browser session, so a direct tab open works fine.
        window.open(doc.SharePointFileUrl, "_blank", "noreferrer");
      } else {
        // Stream via the backend endpoint using the MSAL bearer token.
        await authenticatedDownload(
          `${BASE}/api/v1/lifecycle/documents/${doc.id}/download`,
          filename,
        );
      }
    } catch (err) {
      setDownloadError(err.message || "Download failed");
    } finally {
      setDownloading(false);
    }
  };
 
  return (
    <div style={{
      background: "var(--color-background-primary)",
      border: isOwner
        ? `1.5px solid ${stageConfig.color}`
        : isUnowned
          ? "1.5px solid #FAC775"
          : "1px solid #D0D0D0",
      borderRadius: 12, padding: "10px 12px",
      boxShadow: isStalled ? "0 0 0 2px #F09595" : "none",
    }}>
      {/* Your action badge */}
      {isOwner && (
        <div style={{ fontSize: 9, fontWeight: 600, color: stageConfig.color,
                      marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.5px" }}>
          Your action
        </div>
      )}
 
      {/* Title + View details */}
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 6, gap: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4, flex: 1 }}>
          {doc.Title || doc.DocumentCode || "Untitled document"}
        </div>
        <span
          role="button" tabIndex={0}
          onClick={() => onViewDetails(doc)}
          onKeyDown={e => e.key === "Enter" && onViewDetails(doc)}
          style={{ fontSize: 11, color: "var(--color-text-tertiary)",
                   textDecoration: "underline", cursor: "pointer",
                   flexShrink: 0, marginTop: 2, userSelect: "none" }}
        >
          View details
        </span>
      </div>
 
      {/* Badges */}
      <div style={{ display: "flex", gap: 4, marginBottom: 6, flexWrap: "wrap" }}>
        {doc.Trigger && (
          <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, fontWeight: 500,
                         background: triggerStyle.bg, color: triggerStyle.color,
                         border: `0.5px solid ${triggerStyle.bd}` }}>
            {doc.Trigger}
          </span>
        )}
        {doc.AIGenerated  && <StatusBadge label="AI draft" />}
        {doc.Revised      && <StatusBadge label="Revised" />}
        {doc.DocumentType && <StatusBadge label={doc.DocumentType} />}
      </div>
 
      {/* Rejection banner — shown in Review when document was previously rejected */}
      {isReview && doc.RejectionCount > 0 && doc.RejectionReason && (
        <div style={{
          padding: "8px 10px", background: "#FCEBEB", borderRadius: 7,
          border: "1px solid #F09595", fontSize: 11, color: "#791F1F", marginBottom: 8,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 3 }}>
            Rejected (×{doc.RejectionCount}) — address this before re-progressing
          </div>
          <div style={{ lineHeight: 1.5, opacity: 0.9 }}>{doc.RejectionReason}</div>
        </div>
      )}

      {/* CDI failure notice */}
      {cdiCount > 0 && (
        <div style={{ padding: "6px 10px", background: "#FCEBEB", borderRadius: 6,
                      fontSize: 11, color: "#791F1F", marginBottom: 8 }}>
          {cdiCount} CDI failure{cdiCount > 1 ? "s" : ""} to fix — click View details
        </div>
      )}

      {/* AI fix suggestions panel */}
      {cdiFix.hasSuggestion && !cdiFix.suggestion?.error && (
        <div style={{
          padding: "10px 12px", background: "#F0F4FF", borderRadius: 8,
          border: "1px solid #AFA9EC", marginBottom: 8, fontSize: 11,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={{ fontWeight: 600, color: "#3C3489" }}>
              AI fix suggestions
            </div>
            {cdiFix.generatedAt && (
              <span style={{ fontSize: 9, color: "#9ca3af" }}>
                {new Date(cdiFix.generatedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
                {cdiFix.isFromCache ? " (cached)" : ""}
              </span>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {aiFixSuggestions.map((s, i) => (
              <div key={i} style={{
                padding: "6px 8px", background: "#fff", borderRadius: 6,
                border: "0.5px solid #CCC",
              }}>
                <div style={{ fontWeight: 600, fontSize: 10, color: "#333", marginBottom: 2 }}>
                  {s.check}
                </div>
                {s.finding && <div style={{ color: "#555", marginBottom: 3 }}>{s.finding}</div>}
                {s.suggestion && <div style={{ color: "#1D9E75", fontStyle: "italic" }}>→ {s.suggestion}</div>}
              </div>
            ))}
            {!aiFixSuggestions.length && (
              <div style={{ color: "#555" }}>
                No structured suggestions returned. Try again after re-opening the document.
              </div>
            )}
          </div>
        </div>
      )}
      {cdiFix.suggestion?.error && (
        <div style={{ padding: "6px 10px", background: "#FCEBEB", borderRadius: 6,
                      fontSize: 11, color: "#791F1F", marginBottom: 8 }}>
          {cdiFix.suggestion.error}
        </div>
      )}

      {/* Gap link */}
      {doc.LinkedGapId && (
        <div style={{ fontSize: 10, color: "#3C3489", marginBottom: 6 }}>
          Gap: {doc.LinkedGapId}
        </div>
      )}
 
      {/* Error banners */}
      {uploadError && (
        <div style={{ padding: "5px 8px", background: "#FCEBEB", borderRadius: 6,
                      fontSize: 11, color: "#791F1F", marginBottom: 6 }}>
          Upload failed: {uploadError}
        </div>
      )}
      {downloadError && (
        <div style={{ padding: "5px 8px", background: "#FCEBEB", borderRadius: 6,
                      fontSize: 11, color: "#791F1F", marginBottom: 6 }}>
          Download failed: {downloadError}
        </div>
      )}

      {/* CDI result banner — shown immediately after upload completes */}
      {uploadCdiResult && (
        <div style={{
          padding: "6px 10px", borderRadius: 6, fontSize: 11, marginBottom: 6,
          display: "flex", justifyContent: "space-between", alignItems: "center",
          background: uploadCdiResult.status === "Passed" ? "#E1F5EE" : uploadCdiResult.status === "Failed" ? "#FCEBEB" : "#FFF8E6",
          border: `0.5px solid ${uploadCdiResult.status === "Passed" ? "#5DCAA5" : uploadCdiResult.status === "Failed" ? "#F09595" : "#FAC775"}`,
          color: uploadCdiResult.status === "Passed" ? "#085041" : uploadCdiResult.status === "Failed" ? "#791F1F" : "#7A5000",
        }}>
          <span>
            CDI check: <strong>{uploadCdiResult.status}</strong>
            {uploadCdiResult.status === "Failed" && ` — ${uploadCdiResult.failCount} issue${uploadCdiResult.failCount !== 1 ? "s" : ""} to fix`}
            {uploadCdiResult.status === "Passed" && " — document meets all CDI standards"}
            {uploadCdiResult.status === "Error"  && ` — ${uploadCdiResult.errorDetail || "check could not run"}`}
          </span>
          <span role="button" onClick={() => setUploadCdiResult(null)}
            style={{ cursor: "pointer", opacity: 0.6, marginLeft: 8, fontSize: 13 }}>×</span>
        </div>
      )}
 
      {/* ── Unowned: Claim / Reassign visible to all ── */}
      {isUnowned && (
        <div style={{ marginTop: 6 }}>
          <div style={{ padding: "5px 8px", background: "#FFF8E6", borderRadius: 6, marginBottom: 6,
                        border: "0.5px solid #FAC775", fontSize: 10, color: "#7A5000" }}>
            No owner — claim to take ownership, or reassign to a colleague.
          </div>
          {claimError && (
            <div style={{ padding: "5px 8px", background: "#FCEBEB", borderRadius: 6,
                          fontSize: 10, color: "#791F1F", marginBottom: 5 }}>
              {claimError}
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            <button
              onClick={async () => {
                setClaiming(true); setClaimError("");
                try {
                  await lifecycleApi.claim(doc.id);
                  qc.invalidateQueries({ queryKey: ["lifecycle"] });
                } catch (err) {
                  setClaimError(err.response?.data?.detail || err.message || "Could not claim document.");
                } finally { setClaiming(false); }
              }}
              disabled={claiming}
              style={{
                padding: "7px", fontSize: 11, borderRadius: 7,
                border: "none", background: claiming ? "#E8E8E8" : "#BA7517",
                color: claiming ? "#999" : "#fff",
                cursor: claiming ? "not-allowed" : "pointer", fontWeight: 500,
              }}
            >
              {claiming ? "Claiming..." : "Claim"}
            </button>
            <button onClick={() => onReassign(doc)} style={{
              padding: "7px", fontSize: 11, borderRadius: 7,
              border: "1.5px solid #FAC775", background: "#FFF8E6",
              color: "#7A5000", cursor: "pointer", fontWeight: 500,
            }}>Reassign</button>
          </div>
        </div>
      )}

      {/* ── Sensitisation: stakeholders + deadline + feedback ── */}
      {isSensitisation && (
        <div style={{ marginTop: 8 }}>
          {/* Deadline badge */}
          {dlDeadline && (
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "5px 8px", borderRadius: 6, marginBottom: 8,
              background: dlExpired ? "#FCEBEB" : dlDaysLeft <= 2 ? "#FAEEDA" : "#E6F1FB",
              border: `0.5px solid ${dlExpired ? "#F09595" : dlDaysLeft <= 2 ? "#FAC775" : "#85B7EB"}`,
              fontSize: 11,
              color: dlExpired ? "#791F1F" : dlDaysLeft <= 2 ? "#633806" : "#0C447C",
            }}>
              <span>
                {dlExpired
                  ? `Deadline passed — ${fmtDate(dlDeadline)}`
                  : dlDaysLeft === 0
                    ? "Feedback closes today"
                    : `${dlDaysLeft}d left — deadline ${fmtDate(dlDeadline)}`}
              </span>
              {isOwner && (
                <span
                  role="button" tabIndex={0}
                  onClick={() => onProgressClick({ ...doc, _extendDeadline: true })}
                  onKeyDown={e => e.key === "Enter" && onProgressClick({ ...doc, _extendDeadline: true })}
                  style={{ fontSize: 10, textDecoration: "underline", cursor: "pointer", marginLeft: 8 }}>
                  Extend
                </span>
              )}
            </div>
          )}

          {/* Response counter */}
          {hasStakeholders && (
            <div style={{ fontSize: 10, color: "#D85A30", marginBottom: 6 }}>
              {doc.StakeholderResponseCount || 0} of {stakeholderCount} stakeholder{stakeholderCount !== 1 ? "s" : ""} responded
            </div>
          )}

          {/* Stakeholders */}
          {hasStakeholders && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#D85A30",
                            textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 5 }}>
                Stakeholders notified ({stakeholderCount})
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {doc.Stakeholders.map((s, i) => (
                  <span key={i} style={{
                    fontSize: 10, padding: "2px 8px", borderRadius: 10,
                    background: "#FAECE7", color: "#D85A30", border: "0.5px solid #F0997B",
                  }}>
                    {s.name || s.email || "Unknown"}
                  </span>
                ))}
              </div>
            </div>
          )}
          {/* Feedback — read-only, written by stakeholders externally */}
          {(hasStakeholders || feedbackEntries.length > 0) && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#D85A30",
                            textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 5 }}>
                Stakeholder feedback
                {feedbackEntries.length > 0 && ` (${feedbackEntries.length})`}
              </div>
              {feedbackEntries.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {feedbackEntries.map((f, i) => <FeedbackEntry key={i} entry={f} />)}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Approval: approver info + approved state ── */}
      {isApproval && (
        <div style={{ marginTop: 8 }}>
          {doc.ApproverName && !isApproved && (
            <div style={{ padding: "8px 12px", background: "#F4EEFB", borderRadius: 8,
                          border: "0.5px solid #C9A8E0", marginBottom: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#6B2FA0", marginBottom: 2 }}>
                Pending approval from
              </div>
              <div style={{ fontSize: 12, fontWeight: 500, color: "#4A1F73" }}>
                {doc.ApproverName}
              </div>
              {doc.SubmittedForApproval && (
                <div style={{ fontSize: 10, color: "#6B2FA0", opacity: 0.7, marginTop: 2 }}>
                  Submitted {fmtDate(doc.SubmittedForApproval)}
                </div>
              )}
            </div>
          )}
          {isApproved && (
            <div style={{ padding: "8px 12px", background: "#E1F5EE", borderRadius: 8,
                          border: "0.5px solid #5DCAA5", marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#085041" }}>
                ✓ Approved {doc.ApprovedDate ? `— ${fmtDate(doc.ApprovedDate)}` : ""}
              </div>
              <div style={{ fontSize: 10, color: "#085041", opacity: 0.8, marginTop: 2 }}>
                Approved by {doc.ApproverName || "—"} · Added to Document Register
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Owner action buttons ── */}
      {isOwner && (
        <div style={{ marginTop: 8 }}>

          {/* Review + Sensitisation: View / Upload / Reassign / Progress */}
          {(isReview || isSensitisation) && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {/* View */}
              {doc.SharePointFileUrl || doc.Revised ? (
                <button onClick={handleDownload} disabled={downloading} style={{
                  padding: "7px", fontSize: 11, borderRadius: 7,
                  border: "1.5px solid #C0C0C0", background: "transparent",
                  color: downloading ? "#999" : "var(--color-text-primary)",
                  cursor: downloading ? "not-allowed" : "pointer",
                }}>{downloading ? "Opening..." : "View ↗"}</button>
              ) : (
                <div style={{
                  padding: "7px", fontSize: 10, borderRadius: 7, textAlign: "center",
                  border: `1px dashed ${needsUpload ? "#FAC775" : "#D0D0D0"}`,
                  color: needsUpload ? "#7A5000" : "var(--color-text-tertiary)",
                  background: needsUpload ? "#FFFBF0" : "transparent",
                }}>
                  {needsUpload ? "Upload required to progress" : "No file yet"}
                </div>
              )}
              {/* Upload (Review only) */}
              {isReview ? (
                <div>
                  <input ref={uploadRef} type="file" accept=".pdf,.docx,.doc"
                    style={{ display: "none" }} onChange={handleFileSelect} />
                  <button onClick={() => uploadRef.current?.click()} disabled={uploading} style={{
                    width: "100%", padding: "7px", fontSize: 11, borderRadius: 7,
                    border: "1.5px solid #C0C0C0", background: "transparent",
                    color: uploading ? "#999" : "var(--color-text-primary)",
                    cursor: uploading ? "not-allowed" : "pointer",
                  }}>{uploading ? "Uploading & checking CDI..." : "Upload ↑"}</button>
                </div>
              ) : (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
                              fontSize: 10, color: "var(--color-text-tertiary)" }}>
                  — no upload needed
                </div>
              )}
              {/* Fix with AI — only in Review when CDI failures exist */}
              {isReview && cdiCount > 0 && (
                <button onClick={handleGetCdiFix} disabled={cdiFix.loading} style={{
                  padding: "7px", fontSize: 11, borderRadius: 7,
                  border: "1.5px solid #AFA9EC", background: cdiFix.loading ? "#F0F0F0" : "#EEEDFE",
                  color: cdiFix.loading ? "#999" : "#3C3489",
                  cursor: cdiFix.loading ? "not-allowed" : "pointer", fontWeight: 500,
                }}>
                  {cdiFix.loading ? "Thinking..." : cdiFix.hasSuggestion ? "Refresh AI fix" : "Fix with AI"}
                </button>
              )}
              {/* Reassign */}
              <button onClick={() => onReassign(doc)} style={{
                padding: "7px", fontSize: 11, borderRadius: 7,
                border: "1.5px solid #C0C0C0", background: "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer",
                gridColumn: isReview && cdiCount > 0 ? "auto" : "auto",
              }}>Reassign</button>
              {/* Progress → opens stage-specific modal */}
              <button
                onClick={() => canProgress && onProgressClick(doc)}
                disabled={!canProgress}
                title={
                  needsUpload ? "Upload a revised version before progressing"
                  // CDI gate temporarily disabled.
                  // : doc.CDIStatus === "Failed" ? "Fix CDI failures before progressing"
                  : undefined
                }
                style={{
                  padding: "7px", fontSize: 11, borderRadius: 7, fontWeight: 500,
                  border: canProgress ? "none" : "1.5px solid #E0E0E0",
                  background: canProgress ? stageConfig.color : "transparent",
                  color: canProgress ? "#fff" : "#B0B0B0",
                  cursor: canProgress ? "pointer" : "not-allowed",
                  gridColumn: isReview && cdiCount > 0 ? "1 / -1" : "auto",
                }}
              >
                {needsUpload ? "Upload first →" : "Progress →"}
              </button>
            </div>
          )}

          {/* Approval stage: View + Recall + Review & Decide */}
          {isApproval && !isApproved && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {doc.SharePointFileUrl && (
                <button onClick={handleDownload} disabled={downloading} style={{
                  padding: "7px", fontSize: 11, borderRadius: 7,
                  border: "1.5px solid #C0C0C0", background: "transparent",
                  color: downloading ? "#999" : "var(--color-text-primary)",
                  cursor: downloading ? "not-allowed" : "pointer",
                }}>{downloading ? "Opening..." : "View ↗"}</button>
              )}
              <button onClick={() => onReassign(doc)} style={{
                padding: "7px", fontSize: 11, borderRadius: 7,
                border: "1.5px solid #C0C0C0", background: "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer",
              }}>Reassign</button>
              {/* Route to the dedicated approver review page */}
              <button
                onClick={() => navigate(`/lifecycle/approve/${doc.id}`)}
                style={{
                  padding: "7px", fontSize: 11, borderRadius: 7, fontWeight: 600,
                  border: "none", background: "#993556", color: "#fff", cursor: "pointer",
                  gridColumn: "1 / -1",
                }}
              >
                Review &amp; Decide →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div style={{ display: "flex", justifyContent: "space-between",
                    fontSize: 11, marginTop: isOwner ? 8 : 4 }}>
        <span style={{ color: "var(--color-text-secondary)" }}>
          {doc.OwnerName || doc.OwnerEntraId || "Unassigned"}
        </span>
        <span style={{ color: isStalled ? "#A32D2D" : "var(--color-text-tertiary)",
                       fontWeight: isStalled ? 500 : 400 }}>
          {daysIn}d {isStalled && "— stalled"}
        </span>
      </div>
    </div>
  );
};
 

// =============================================================================
//  Reassign modal
// =============================================================================

const ReassignModal = ({ doc, onSave, onClose }) => {
  const [resolved, setResolved] = useState(null);
  const [saving,   setSaving]   = useState(false);
  const [error,    setError]    = useState("");

  const handleSave = async () => {
    if (!resolved) { setError("Select a person first."); return; }
    setSaving(true);
    try {
      await onSave(doc.id, resolved.oid, resolved.display_name);
      onClose();
    } catch (err) {
      setError(err.message || "Reassign failed.");
      setSaving(false);
    }
  };

  return (
    <div onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000,
               display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div onClick={e => e.stopPropagation()}
        style={{ background: "var(--color-background-primary)", borderRadius: 14,
                 padding: "24px 28px", maxWidth: 440, width: "100%",
                 boxShadow: "0 20px 60px rgba(0,0,0,0.25)" }}>

        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 3 }}>
              Reassign document
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)",
                          maxWidth: 340, lineHeight: 1.4 }}>
              {doc.Title}
            </div>
          </div>
          <button onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer",
                     fontSize: 18, color: "var(--color-text-tertiary)", lineHeight: 1 }}>
            ×
          </button>
        </div>

        {error && (
          <div style={{ padding: "9px 12px", background: "#FCEBEB", borderRadius: 8,
                        fontSize: 12, color: "#791F1F", marginBottom: 12,
                        border: "1px solid #F09595" }}>
            {error}
          </div>
        )}

        <UserSearchField
          onSelect={(u) => { setResolved(u); if (error) setError(""); }}
          label="New owner — type name or email"
          placeholder="Search by name or email..."
          accentColor="#534AB7"
        />

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button
            onClick={handleSave}
            disabled={saving || !resolved}
            style={{ flex: 1, padding: "10px", fontSize: 13, borderRadius: 9,
                     border: "none", fontWeight: 600,
                     background: saving || !resolved ? "#E8E8E8" : "#534AB7",
                     color: saving || !resolved ? "#999" : "#fff",
                     cursor: saving || !resolved ? "not-allowed" : "pointer" }}
          >
            {saving ? "Reassigning..." : resolved ? `Assign to ${resolved.display_name}` : "Select a person above"}
          </button>
          <button onClick={onClose}
            style={{ padding: "10px 16px", fontSize: 13, borderRadius: 9,
                     border: "1.5px solid #D0D0D0", background: "transparent",
                     color: "var(--color-text-secondary)", cursor: "pointer" }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

// =============================================================================
//  StakeholdersModal — Review → Sensitisation
//  Collect one or more Dragnet email addresses, resolve each via Graph API,
//  then submit to the progress endpoint with the stakeholders list.
// =============================================================================

const StakeholdersModal = ({ doc, onClose, onDone }) => {
  const qc = useQueryClient();
  const [stakeholders, setStakeholders] = useState([]);
  const [deadline,     setDeadline]     = useState("");   // ISO date "YYYY-MM-DD"
  const [saving,       setSaving]       = useState(false);
  const [error,        setError]        = useState("");
  const [dupError,     setDupError]     = useState("");

  // Default deadline: 7 days from today
  const defaultDeadline = (() => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  })();

  const handleSelectStakeholder = (u) => {
    if (!u) return;
    if (stakeholders.some(s => s.oid === u.oid)) {
      setDupError(`${u.display_name} is already in the list.`);
      return;
    }
    setDupError("");
    setStakeholders(prev => [...prev, { oid: u.oid, name: u.display_name, email: u.email }]);
  };

  const handleRemove = (oid) => setStakeholders(prev => prev.filter(s => s.oid !== oid));

  const handleSubmit = async () => {
    if (stakeholders.length === 0) { setError("Add at least one stakeholder."); return; }
    setSaving(true); setError("");
    try {
      await lifecycleApi.progress(doc.id, "Review", {
        stakeholders,
        sensitisation_deadline: deadline || defaultDeadline,
      });
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      onDone();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to progress document.");
      setSaving(false);
    }
  };

  const handleSkip = async () => {
    setSaving(true); setError("");
    try {
      await lifecycleApi.progress(doc.id, "Review", { skip_stakeholders: true });
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      onDone();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to progress document.");
      setSaving(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: "var(--color-background-primary)", borderRadius: 14,
        padding: "24px 28px", maxWidth: 480, width: "100%", maxHeight: "88vh",
        overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Progress to Sensitisation</div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", maxWidth: 360, lineHeight: 1.4 }}>
              {doc.Title}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: "var(--color-text-tertiary)", lineHeight: 1 }}>×</button>
        </div>

        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 14, lineHeight: 1.5 }}>
          Select the people who need to review this document before it takes effect.
          They will be recorded as stakeholders for this sensitisation round.
        </div>

        {/* Error banner */}
        {error && (
          <div style={{ padding: "9px 12px", background: "#FCEBEB", border: "1px solid #F09595",
                        borderRadius: 8, fontSize: 12, color: "#791F1F", marginBottom: 12 }}>
            {error}
          </div>
        )}

        {/* Person search */}
        <div style={{ marginBottom: 12 }}>
          <UserSearchField
            onSelect={handleSelectStakeholder}
            label="Add stakeholder"
            placeholder="Search by name or email..."
            accentColor="#D85A30"
            clearAfterSelect
          />
          {dupError && (
            <div style={{ fontSize: 11, color: "#A32D2D", marginTop: -8, marginBottom: 6 }}>
              {dupError}
            </div>
          )}
        </div>

        {/* Feedback deadline */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600,
                          color: "var(--color-text-secondary)", marginBottom: 5,
                          textTransform: "uppercase", letterSpacing: "0.5px" }}>
            Feedback deadline (optional — default 7 days)
          </label>
          <input
            type="date"
            value={deadline || defaultDeadline}
            min={new Date().toISOString().slice(0, 10)}
            onChange={e => setDeadline(e.target.value)}
            style={{
              width: "100%", fontSize: 12, padding: "9px 11px", borderRadius: 8,
              border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
              color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box",
            }}
          />
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 3 }}>
            Stakeholders who submit feedback after this date will be blocked. You can extend it later.
          </div>
        </div>

        {/* Stakeholders list */}
        {stakeholders.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)",
                          textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8 }}>
              Selected ({stakeholders.length})
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {stakeholders.map(s => (
                <div key={s.oid} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 12px", background: "var(--color-background-secondary)",
                  borderRadius: 8, border: "0.5px solid var(--color-border-tertiary)",
                }}>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 500 }}>{s.name}</div>
                    <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 1 }}>{s.email}</div>
                  </div>
                  <button onClick={() => handleRemove(s.oid)} style={{
                    background: "none", border: "none", cursor: "pointer",
                    color: "var(--color-text-tertiary)", fontSize: 16, lineHeight: 1,
                  }}>×</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={handleSubmit}
            disabled={saving || stakeholders.length === 0}
            style={{
              flex: 1, padding: "11px", fontSize: 13, borderRadius: 9, border: "none", fontWeight: 600,
              background: saving || stakeholders.length === 0 ? "#E8E8E8" : "#D85A30",
              color: saving || stakeholders.length === 0 ? "#999" : "#fff",
              cursor: saving || stakeholders.length === 0 ? "not-allowed" : "pointer",
              minWidth: 180,
            }}
          >
            {saving ? "Progressing..." : `Proceed to Sensitisation with ${stakeholders.length} stakeholder${stakeholders.length !== 1 ? "s" : ""}`}
          </button>
          <button
            onClick={handleSkip}
            disabled={saving}
            title="Move to Sensitisation without adding stakeholders"
            style={{
              padding: "11px 14px", fontSize: 12, borderRadius: 9, fontWeight: 500,
              border: "1.5px solid #D0D0D0", background: "transparent",
              color: saving ? "#999" : "var(--color-text-secondary)",
              cursor: saving ? "not-allowed" : "pointer",
            }}
          >
            Skip
          </button>
          <button onClick={onClose} style={{
            padding: "11px 14px", fontSize: 13, borderRadius: 9,
            border: "1.5px solid #D0D0D0", background: "transparent",
            color: "var(--color-text-secondary)", cursor: "pointer",
          }}>Cancel</button>
        </div>
      </div>
    </div>
  );
};


// =============================================================================
//  ExtendDeadlineModal — extend the sensitisation feedback deadline
// =============================================================================

const ExtendDeadlineModal = ({ doc, onClose }) => {
  const qc = useQueryClient();
  const current   = doc.SensitisationDeadline || "";
  const minDate   = new Date().toISOString().slice(0, 10);
  const [newDate, setNewDate] = useState(current ? current.slice(0, 10) : "");
  const [saving,  setSaving]  = useState(false);
  const [error,   setError]   = useState("");

  const handleSave = async () => {
    if (!newDate) { setError("Select a new deadline date."); return; }
    setSaving(true); setError("");
    try {
      await apiClient.patch(`/api/v1/lifecycle/documents/${doc.id}/deadline`, { new_deadline: newDate });
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to extend deadline.");
      setSaving(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: "var(--color-background-primary)", borderRadius: 14,
        padding: "24px 28px", maxWidth: 400, width: "100%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Extend feedback deadline</div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: "#888" }}>×</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 16, lineHeight: 1.5 }}>
          Current deadline: <strong>{current ? fmtDate(current) : "none set"}</strong>
          <br />Choose a new later date to give stakeholders more time to submit feedback.
        </div>
        {error && (
          <div style={{ padding: "8px 12px", background: "#FCEBEB", border: "1px solid #F09595",
                        borderRadius: 8, fontSize: 12, color: "#791F1F", marginBottom: 12 }}>
            {error}
          </div>
        )}
        <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)",
                        marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.5px" }}>
          New deadline
        </label>
        <input
          type="date"
          value={newDate}
          min={minDate}
          onChange={e => setNewDate(e.target.value)}
          style={{
            width: "100%", fontSize: 12, padding: "9px 11px", borderRadius: 8,
            border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
            color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box",
            marginBottom: 16,
          }}
        />
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={handleSave} disabled={saving || !newDate} style={{
            flex: 1, padding: "11px", fontSize: 13, borderRadius: 9, border: "none", fontWeight: 600,
            background: saving || !newDate ? "#E8E8E8" : "#D85A30",
            color: saving || !newDate ? "#999" : "#fff",
            cursor: saving || !newDate ? "not-allowed" : "pointer",
          }}>{saving ? "Saving..." : "Save new deadline"}</button>
          <button onClick={onClose} style={{
            padding: "11px 16px", fontSize: 13, borderRadius: 9, border: "1.5px solid #D0D0D0",
            background: "transparent", color: "var(--color-text-secondary)", cursor: "pointer",
          }}>Cancel</button>
        </div>
      </div>
    </div>
  );
};


// =============================================================================
//  ApproverModal — Sensitisation → Approval
//  Collect a single approver email, resolve via Graph API, submit to progress.
// =============================================================================

const ApproverModal = ({ doc, onClose, onDone }) => {
  const qc = useQueryClient();
  const [resolved,    setResolved]    = useState(null);
  const [saving,      setSaving]      = useState(false);
  const [error,       setError]       = useState("");

  const handleSubmit = async () => {
    if (!resolved) { setError("Select an approver first."); return; }
    setSaving(true); setError("");
    try {
      await lifecycleApi.progress(doc.id, "Sensitisation", {
        approver_id:    resolved.oid,
        approver_name:  resolved.display_name,
        approver_email: resolved.email,
      });
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      onDone();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to progress document.");
      setSaving(false);
    }
  };

  const handleSkip = async () => {
    setSaving(true); setError("");
    try {
      await lifecycleApi.progress(doc.id, "Sensitisation", { skip_approver: true });
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      onDone();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to progress document.");
      setSaving(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: "var(--color-background-primary)", borderRadius: 14,
        padding: "24px 28px", maxWidth: 440, width: "100%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Submit for Approval</div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", maxWidth: 330, lineHeight: 1.4 }}>
              {doc.Title}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: "var(--color-text-tertiary)", lineHeight: 1 }}>×</button>
        </div>

        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 14, lineHeight: 1.5 }}>
          Select the person who will formally sign off this document.
          They will be recorded as the approver on the document cover page.
        </div>

        {error && (
          <div style={{ padding: "9px 12px", background: "#FCEBEB", border: "1px solid #F09595",
                        borderRadius: 8, fontSize: 12, color: "#791F1F", marginBottom: 12 }}>
            {error}
          </div>
        )}

        {/* Person search */}
        <div style={{ marginBottom: 16 }}>
          <UserSearchField
            onSelect={(u) => { setResolved(u); if (error) setError(""); }}
            label="Approver — type name or email"
            placeholder="Search by name or email..."
            accentColor="#993556"
          />
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={handleSubmit}
            disabled={saving || !resolved}
            style={{
              flex: 1, padding: "11px", fontSize: 13, borderRadius: 9, border: "none", fontWeight: 600,
              background: saving || !resolved ? "#E8E8E8" : "#993556",
              color: saving || !resolved ? "#999" : "#fff",
              cursor: saving || !resolved ? "not-allowed" : "pointer",
              minWidth: 160,
            }}
          >
            {saving ? "Submitting..." : `Submit for Approval${resolved ? ` — ${resolved.display_name}` : ""}`}
          </button>
          <button
            onClick={handleSkip}
            disabled={saving}
            title="Move to Approval stage without assigning an approver"
            style={{
              padding: "11px 14px", fontSize: 12, borderRadius: 9, fontWeight: 500,
              border: "1.5px solid #D0D0D0", background: "transparent",
              color: saving ? "#999" : "var(--color-text-secondary)",
              cursor: saving ? "not-allowed" : "pointer",
            }}
          >
            Skip
          </button>
          <button onClick={onClose} style={{
            padding: "11px 14px", fontSize: 13, borderRadius: 9,
            border: "1.5px solid #D0D0D0", background: "transparent",
            color: "var(--color-text-secondary)", cursor: "pointer",
          }}>Cancel</button>
        </div>
      </div>
    </div>
  );
};


// =============================================================================
//  ApproveConfirmModal — Approval stage → Mark as Approved
// =============================================================================

const ApproveConfirmModal = ({ doc, onClose, onDone }) => {
  const qc = useQueryClient();
  const [notes,  setNotes]  = useState("");
  const [saving, setSaving] = useState(false);
  const [error,  setError]  = useState("");

  const handleApprove = async () => {
    setSaving(true); setError("");
    try {
      await lifecycleApi.approve(doc.id, { notes: notes.trim() || undefined });
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      onDone();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Approval failed.");
      setSaving(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: "var(--color-background-primary)", borderRadius: 14,
        padding: "24px 28px", maxWidth: 420, width: "100%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Mark as Approved</div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", maxWidth: 320, lineHeight: 1.4 }}>
              {doc.Title}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: "var(--color-text-tertiary)" }}>×</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 14, lineHeight: 1.5 }}>
          This will mark the document as Approved and create an entry in the Document Register.
          This action cannot be undone.
        </div>
        {error && (
          <div style={{ padding: "9px 12px", background: "#FCEBEB", border: "1px solid #F09595",
                        borderRadius: 8, fontSize: 12, color: "#791F1F", marginBottom: 12 }}>
            {error}
          </div>
        )}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600,
                          color: "var(--color-text-secondary)", marginBottom: 5 }}>
            Approval note (optional)
          </label>
          <textarea
            value={notes} onChange={e => setNotes(e.target.value)}
            placeholder="Any notes or conditions on this approval..."
            rows={3}
            style={{
              width: "100%", fontSize: 12, padding: "9px 11px", borderRadius: 8,
              border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
              color: "var(--color-text-primary)", resize: "vertical",
              fontFamily: "var(--font-sans)", outline: "none", boxSizing: "border-box",
            }}
            onFocus={e => (e.target.style.borderColor = "#993556")}
            onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
          />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={handleApprove} disabled={saving} style={{
            flex: 1, padding: "11px", fontSize: 13, borderRadius: 9, border: "none", fontWeight: 600,
            background: saving ? "#E8E8E8" : "#1D9E75",
            color: saving ? "#999" : "#fff", cursor: saving ? "not-allowed" : "pointer",
          }}>{saving ? "Approving..." : "Confirm Approval ✓"}</button>
          <button onClick={onClose} style={{
            padding: "11px 16px", fontSize: 13, borderRadius: 9,
            border: "1.5px solid #D0D0D0", background: "transparent",
            color: "var(--color-text-secondary)", cursor: "pointer",
          }}>Cancel</button>
        </div>
      </div>
    </div>
  );
};


// =============================================================================
//  Main component
// =============================================================================

export default function DocumentLifecycle() {
  const [showForm,          setShowForm]          = useState(false);
  const [detailsDoc,        setDetailsDoc]        = useState(null);
  const [reassignDoc,       setReassignDoc]       = useState(null);
  const [progressingDoc,    setProgressingDoc]    = useState(null); // doc whose Progress → was clicked
  const [approvingDoc,      setApprovingDoc]      = useState(null); // doc being approved
  const [extendDeadlineDoc, setExtendDeadlineDoc] = useState(null); // doc for deadline extension

  const { oid: currentUserOid } = useCurrentUserRole();
  const { data: docs = [], isLoading, error, refetch } = useLifecycleDocs();
  const qc = useQueryClient();

  const handleReassign = async (id, ownerOid, ownerName) => {
    await lifecycleApi.reassign(id, ownerOid, ownerName);
    qc.invalidateQueries({ queryKey: ["lifecycle"] });
  };

  const handleProgressClick = (doc) => {
    if (doc._extendDeadline) {
      // Strip the internal flag and show deadline extension modal
      const { _extendDeadline, ...cleanDoc } = doc;
      setExtendDeadlineDoc(cleanDoc);
    } else {
      setProgressingDoc(doc);
    }
  };

  const closeProgress      = () => setProgressingDoc(null);
  const closeApprove       = () => setApprovingDoc(null);
  const closeExtendDeadline = () => setExtendDeadlineDoc(null);

  if (isLoading) return <LoadingState message="Loading document lifecycle..." />;
  if (error)     return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Document lifecycle</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Every new and revised document passes through Review → Sensitisation → Approval before entering the Document Register.
          </div>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          style={{ padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "none",
                   background: "#378ADD", color: "#fff", cursor: "pointer",
                   fontWeight: 500, flexShrink: 0 }}
        >
          + New document
        </button>
      </div>

      {/* New document form */}
      {showForm && (
        <NewDocForm
          onSuccess={() => setShowForm(false)}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* Kanban */}
      {docs.length === 0 && !showForm ? (
        <EmptyState message="No documents in the lifecycle. Click + New document to start one." />
      ) : (
        <div style={{ display: "flex", gap: 12 }}>
          {STAGES.map(stage => {
            const stageDocs = docs
              .filter(d => d.Stage === stage.key)
              .sort(sortNewestFirst);
            return (
              <div key={stage.key} style={{ flex: 1, minWidth: 0 }}>
                {/* Column header */}
                <div style={{ padding: "7px 10px", borderRadius: 8, marginBottom: 10,
                              background: stage.bg,
                              display: "flex", justifyContent: "space-between",
                              alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: stage.color }}>
                      {stage.key}
                    </div>
                    <div style={{ fontSize: 10, color: stage.color, opacity: 0.8, marginTop: 1,
                                  lineHeight: 1.4 }}>
                      {stage.desc}
                    </div>
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 600, color: stage.color,
                                 background: stage.color + "20", padding: "1px 8px",
                                 borderRadius: 10, flexShrink: 0 }}>
                    {stageDocs.length}
                  </span>
                </div>

                {/* Cards */}
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {stageDocs.length === 0 ? (
                    <div style={{ padding: "20px 12px", textAlign: "center",
                                  border: `1px dashed ${stage.bd}`, borderRadius: 10,
                                  fontSize: 11, color: stage.color, opacity: 0.6 }}>
                      No documents
                    </div>
                  ) : (
                    stageDocs.map(doc => (
                      <LifecycleCard
                        key={doc.id}
                        doc={doc}
                        stageConfig={stage}
                        currentUserOid={currentUserOid}
                        onViewDetails={setDetailsDoc}
                        onProgressClick={handleProgressClick}
                        onReassign={setReassignDoc}
                        onApprove={setApprovingDoc}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Modals ── */}
      <DetailsModal doc={detailsDoc} onClose={() => setDetailsDoc(null)} />

      {reassignDoc && (
        <ReassignModal
          doc={reassignDoc}
          onSave={handleReassign}
          onClose={() => setReassignDoc(null)}
        />
      )}

      {/* Progress modal — picks StakeholdersModal or ApproverModal based on stage */}
      {progressingDoc?.Stage === "Review" && (
        <StakeholdersModal
          doc={progressingDoc}
          onClose={closeProgress}
          onDone={closeProgress}
        />
      )}
      {progressingDoc?.Stage === "Sensitisation" && (
        <ApproverModal
          doc={progressingDoc}
          onClose={closeProgress}
          onDone={closeProgress}
        />
      )}

      {approvingDoc && (
        <ApproveConfirmModal
          doc={approvingDoc}
          onClose={closeApprove}
          onDone={closeApprove}
        />
      )}

      {extendDeadlineDoc && (
        <ExtendDeadlineModal
          doc={extendDeadlineDoc}
          onClose={closeExtendDeadline}
        />
      )}
    </>
  );
}
