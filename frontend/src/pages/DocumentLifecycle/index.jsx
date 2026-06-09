// =============================================================================
// pages/DocumentLifecycle/index.jsx
// Document Lifecycle — fully wired, all five entry types handled.
// Every action button works. New document form handles all scenarios.
// CDI Fix cards show the specific failures. Gap Remediation shows linked gap.
// Three-column kanban: Review → Sensitisation → Approval.
// =============================================================================

import { useState, useRef } from "react";
import { useMsal } from "@azure/msal-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { LoadingState, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import apiClient from "../../api/grcApi.js";

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

  progress: (id, currentStage) =>
    apiClient.patch(`/api/v1/lifecycle/documents/${id}/progress`,
      { current_stage: currentStage }).then(r => r.data),

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

function useProgress() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, stage }) => lifecycleApi.progress(id, stage),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ["lifecycle"] }),
  });
}

function useCurrentUser() {
  const { accounts } = useMsal();
  const a = accounts[0];
  return {
    oid:  a?.idTokenClaims?.oid || a?.localAccountId || "",
    name: a?.name || a?.username || "",
  };
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
        {doc.LinkedGapId  && <Field l="Linked gap"       v={doc.LinkedGapId} />}
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
  const { oid, name } = useCurrentUser();
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
  const [saving, setSaving] = useState(false);
  const [error,  setError]  = useState("");

  const set = k => e => setForm(f => ({
    ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value,
  }));

  const handleCreate = async () => {
    if (!form.title.trim())  { setError("Document title is required."); return; }
    if (!form.document_type) { setError("Document type is required."); return; }
    if (!form.department)    { setError("Department is required."); return; }
    setSaving(true);
    setError("");
    try {
      if (form.ai_generated) {
        // Call Policy Drafter — creates lifecycle entry automatically
        const resp = await apiClient.post("/api/v1/agents/draft-document", {
          title:             form.title.trim(),
          doc_type:          form.document_type,
          department:        form.department,
          notes:             form.notes.trim() || undefined,
          standards_mapping: form.standards_mapping.trim() || undefined,
          trigger:           "Manual",
        });
        // Show the generated draft to the user
        const draft = resp.data;
        alert(
          `Draft generated — ${draft.doc_code}\n\n` +
          `A Document Lifecycle entry has been created.\n` +
          `Copy the draft from the API response into a Word document, ` +
          `format per CDI standards, and upload via the lifecycle Upload button.`
        );
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
      }
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      onSuccess();
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
            Creates a Review stage entry. Download the template, revise, upload, then progress to Sensitisation.
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
            placeholder="Auto-generated if blank"
            style={{ ...inp, fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.3px" }}
            onFocus={focus} onBlur={blur}
          />
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4 }}>
            Format: DRG-{form.department || "DEPT"}-{form.document_type === "Policy" ? "POL" : form.document_type === "Procedure" ? "PRO" : "DOC"}-XXX-01-26
          </div>
        </div>
        <div>
          <label style={lbl}>Standards mapping</label>
          <input
            type="text" value={form.standards_mapping} onChange={set("standards_mapping")}
            placeholder="e.g. ISO 27001 A.5.18, NDPA S.39"
            style={inp} onFocus={focus} onBlur={blur}
          />
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4 }}>
            Which standards clauses does this document address?
          </div>
        </div>
      </div>

      {/* Notes */}
      <div style={{ marginBottom: 14 }}>
        <label style={lbl}>Notes</label>
        <textarea
          value={form.notes} onChange={set("notes")}
          placeholder="What should this document cover? Any specific requirements, scope boundaries, or context for the author..."
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
            Request AI-generated first draft
          </div>
          <div style={{ fontSize: 11, color: form.ai_generated ? "#085041" : "var(--color-text-secondary)",
                        marginTop: 2, opacity: 0.85 }}>
            Policy Drafter agent will generate a CDI-compliant draft using the document type, department, and notes above.
            Available when the GPU model is running. Your notes above are the brief.
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

      {/* Actions */}
      <div style={{ display: "flex", gap: 10 }}>
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
          {saving ? "Creating..." : "Create and enter Review →"}
        </button>
        <button onClick={onCancel}
          style={{ padding: "11px 18px", fontSize: 13, borderRadius: 9,
                   border: "1.5px solid #D0D0D0", background: "transparent",
                   color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Cancel
        </button>
      </div>
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
//       alert(err.message || "Failed to submit feedback.");
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
  onViewDetails, onProgress, onUpload, onReassign,
  progressPending,
}) => {
  const uploadRef  = useRef();
  const [uploading,      setUploading]      = useState(false);
  const [uploadError,    setUploadError]    = useState("");
  const [downloading,    setDownloading]    = useState(false);
  const [downloadError,  setDownloadError]  = useState("");
  const [showFeedback,   setShowFeedback]   = useState(false);
  const [feedbackText,   setFeedbackText]   = useState("");
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const qc = useQueryClient();
 
  const isOwner    = doc.OwnerEntraId === currentUserOid;
  const daysIn     = Math.max(0, doc.DaysInStage || 0);
  const isStalled  = daysIn > 14;
  const canProgress = isOwner;
  const isSensitisation = doc.Stage === "Sensitisation";
  const triggerStyle = TRIGGER_LABELS[doc.Trigger] || TRIGGER_LABELS["Manual"];
 
  let cdiCount = 0;
  if (doc.CDIFailures) {
    try {
      const parsed = JSON.parse(doc.CDIFailures);
      cdiCount = Array.isArray(parsed) ? parsed.length : 1;
    } catch { cdiCount = 1; }
  }
 
  let feedbackItems = [];
  if (doc.SensitisationFeedback) {
    try { feedbackItems = JSON.parse(doc.SensitisationFeedback); }
    catch { feedbackItems = []; }
  }
 
  // ── Upload ──────────────────────────────────────────────────────────────────
  const handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setUploadError("");
    try {
      await lifecycleApi.upload(doc.id, file);
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
 
  // ── Feedback ────────────────────────────────────────────────────────────────
  const handleSubmitFeedback = async () => {
    if (!feedbackText.trim()) return;
    setSubmittingFeedback(true);
    try {
      const newEntry = {
        text: feedbackText.trim(),
        submittedAt: new Date().toISOString(),
        submittedBy: "You",
      };
      const updated = [...feedbackItems, newEntry];
      await lifecycleApi.updateFeedback(doc.id, JSON.stringify(updated));
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      setFeedbackText("");
      setShowFeedback(false);
    } catch (err) {
      alert(err.message || "Failed to submit feedback.");
    } finally {
      setSubmittingFeedback(false);
    }
  };
 
  return (
    <div style={{
      background: "var(--color-background-primary)",
      border: isOwner ? `1.5px solid ${stageConfig.color}` : "1px solid #D0D0D0",
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
 
      {/* CDI failure notice */}
      {cdiCount > 0 && (
        <div style={{ padding: "6px 10px", background: "#FCEBEB", borderRadius: 6,
                      fontSize: 11, color: "#791F1F", marginBottom: 8 }}>
          {cdiCount} CDI failure{cdiCount > 1 ? "s" : ""} to fix — click View details
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
 
      {/* Action buttons — owner only */}
      {isOwner && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginTop: 6 }}>
 
          {/* ── Download — authenticated, no bare <a href> ── */}
          <button
            onClick={handleDownload}
            disabled={downloading}
            style={{
              padding: "7px", fontSize: 11, borderRadius: 7,
              border: "1.5px solid #C0C0C0", background: "transparent",
              color: downloading ? "#999" : "var(--color-text-primary)",
              cursor: downloading ? "not-allowed" : "pointer",
            }}
          >
            {downloading ? "Downloading..." : "Download ↓"}
          </button>
 
          {/* ── Upload ── */}
          <div>
            <input
              ref={uploadRef} type="file"
              accept=".pdf,.docx,.doc"
              style={{ display: "none" }}
              onChange={handleFileSelect}
            />
            <button
              onClick={() => uploadRef.current?.click()}
              disabled={uploading}
              style={{
                width: "100%", padding: "7px", fontSize: 11, borderRadius: 7,
                border: "1.5px solid #C0C0C0", background: "transparent",
                color: uploading ? "#999" : "var(--color-text-primary)",
                cursor: uploading ? "not-allowed" : "pointer",
              }}
            >
              {uploading ? "Uploading..." : "Upload ↑"}
            </button>
          </div>
 
          {/* ── Reassign ── */}
          <button
            onClick={() => onReassign(doc)}
            style={{
              padding: "7px", fontSize: 11, borderRadius: 7,
              border: "1.5px solid #C0C0C0", background: "transparent",
              color: "var(--color-text-secondary)", cursor: "pointer",
            }}
          >
            Reassign
          </button>
 
          {/* ── Progress ── */}
          <button
            onClick={() => canProgress && onProgress(doc.id, doc.Stage)}
            disabled={!canProgress || progressPending}
            style={{
              padding: "7px", fontSize: 11, borderRadius: 7, fontWeight: 500,
              border: canProgress && !progressPending ? "none" : "1.5px solid #E0E0E0",
              background: canProgress && !progressPending ? stageConfig.color : "transparent",
              color: canProgress && !progressPending ? "#fff" : "#B0B0B0",
              cursor: canProgress && !progressPending ? "pointer" : "not-allowed",
            }}
          >
            {progressPending ? "Moving..." : "Progress →"}
          </button>
        </div>
      )}
 
      {/* Sensitisation feedback panel */}
      {isSensitisation && (
        <div style={{ marginTop: 10 }}>
          {feedbackItems.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#D85A30",
                            textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6 }}>
                Feedback received ({feedbackItems.length})
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {feedbackItems.map((fb, i) => (
                  <div key={i} style={{
                    padding: "7px 10px", background: "#FAECE7", borderRadius: 7,
                    border: "0.5px solid #F0997B", fontSize: 11, color: "#712B13",
                  }}>
                    <div style={{ lineHeight: 1.4 }}>{fb.text}</div>
                    <div style={{ fontSize: 10, opacity: 0.7, marginTop: 2 }}>
                      {fb.submittedBy} · {fb.submittedAt
                        ? new Date(fb.submittedAt).toLocaleDateString("en-GB", {
                            day: "numeric", month: "short", year: "numeric",
                          })
                        : ""}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
 
          {!showFeedback && (
            <button
              onClick={() => setShowFeedback(true)}
              style={{
                width: "100%", padding: "7px", fontSize: 11, borderRadius: 7,
                border: "1.5px solid #F0997B", background: "transparent",
                color: "#D85A30", cursor: "pointer", fontWeight: 500,
              }}
            >
              + Add feedback or comment
            </button>
          )}
 
          {showFeedback && (
            <div style={{ padding: "10px 12px", background: "#FAECE7",
                          borderRadius: 8, border: "1px solid #F0997B" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#D85A30", marginBottom: 6 }}>
                Your feedback on this document
              </div>
              <textarea
                value={feedbackText}
                onChange={e => setFeedbackText(e.target.value)}
                placeholder="What needs to change? Any concerns, suggestions, or comments..."
                rows={3}
                style={{
                  width: "100%", fontSize: 11, padding: "8px 10px", borderRadius: 7,
                  border: "1.5px solid #F0997B", background: "var(--color-background-primary)",
                  color: "var(--color-text-primary)", resize: "vertical",
                  fontFamily: "var(--font-sans)", outline: "none", boxSizing: "border-box",
                  marginBottom: 8,
                }}
                onFocus={e => (e.target.style.borderColor = "#D85A30")}
                onBlur={e => (e.target.style.borderColor = "#F0997B")}
              />
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  onClick={handleSubmitFeedback}
                  disabled={!feedbackText.trim() || submittingFeedback}
                  style={{
                    padding: "7px 14px", fontSize: 11, borderRadius: 7, border: "none",
                    fontWeight: 500,
                    background: !feedbackText.trim() || submittingFeedback ? "#E8E8E8" : "#D85A30",
                    color: !feedbackText.trim() || submittingFeedback ? "#999" : "#fff",
                    cursor: !feedbackText.trim() || submittingFeedback ? "not-allowed" : "pointer",
                  }}
                >
                  {submittingFeedback ? "Submitting..." : "Submit feedback"}
                </button>
                <button
                  onClick={() => { setShowFeedback(false); setFeedbackText(""); }}
                  style={{ padding: "7px 12px", fontSize: 11, borderRadius: 7,
                           border: "1.5px solid #C0C0C0", background: "transparent",
                           color: "var(--color-text-secondary)", cursor: "pointer" }}
                >
                  Cancel
                </button>
              </div>
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
  const [email,    setEmail]    = useState("");
  const [resolved, setResolved] = useState(null); // { oid, display_name, job_title, email }
  const [looking,  setLooking]  = useState(false);
  const [saving,   setSaving]   = useState(false);
  const [error,    setError]    = useState("");

  const handleLookup = async () => {
    if (!email.trim()) return;
    setLooking(true);
    setError("");
    setResolved(null);
    try {
      const resp = await apiClient.get("/api/v1/grc/users/resolve", {
        params: { email: email.trim() },
      });
      setResolved(resp.data);
    } catch (err) {
      setError(
        err.response?.data?.detail ||
        `No Microsoft 365 account found for "${email}". Check the email address.`
      );
    } finally {
      setLooking(false);
    }
  };

  const handleSave = async () => {
    if (!resolved) { setError("Look up a person first."); return; }
    setSaving(true);
    try {
      await onSave(doc.id, resolved.oid, resolved.display_name);
      onClose();
    } catch (err) {
      setError(err.message || "Reassign failed.");
      setSaving(false);
    }
  };

  const inp = {
    width: "100%", fontSize: 13, padding: "9px 11px", borderRadius: 8,
    border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
    color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box",
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

        {/* Email lookup */}
        <div style={{ marginBottom: 12 }}>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600,
                          color: "var(--color-text-secondary)", marginBottom: 5,
                          textTransform: "uppercase", letterSpacing: "0.5px" }}>
            New owner — Microsoft 365 email
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="email" value={email}
              onChange={e => { setEmail(e.target.value); setResolved(null); }}
              onKeyDown={e => e.key === "Enter" && handleLookup()}
              placeholder="firstname.lastname@dragnet-solutions.com"
              style={{ ...inp, flex: 1 }}
              onFocus={e => (e.target.style.borderColor = "#378ADD")}
              onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
            />
            <button
              onClick={handleLookup}
              disabled={!email.trim() || looking}
              style={{ padding: "9px 14px", fontSize: 12, borderRadius: 8,
                       border: "none", fontWeight: 500, flexShrink: 0,
                       background: !email.trim() || looking ? "#E8E8E8" : "#378ADD",
                       color: !email.trim() || looking ? "#999" : "#fff",
                       cursor: !email.trim() || looking ? "not-allowed" : "pointer" }}
            >
              {looking ? "Looking..." : "Look up"}
            </button>
          </div>
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4 }}>
            Must be a Dragnet Microsoft 365 account. Press Enter or click Look up.
          </div>
        </div>

        {/* Resolved person card */}
        {resolved && (
          <div style={{
            padding: "12px 14px", background: "#E1F5EE", borderRadius: 10,
            border: "1px solid #5DCAA5", marginBottom: 16,
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#085041" }}>
                {resolved.display_name}
              </div>
              <div style={{ fontSize: 11, color: "#085041", opacity: 0.8, marginTop: 2 }}>
                {resolved.job_title && `${resolved.job_title} · `}{resolved.email}
              </div>
            </div>
            <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 5,
                           background: "#5DCAA5", color: "#fff", fontWeight: 500 }}>
              ✓ Found
            </span>
          </div>
        )}

        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={handleSave}
            disabled={saving || !resolved}
            style={{ flex: 1, padding: "10px", fontSize: 13, borderRadius: 9,
                     border: "none", fontWeight: 600,
                     background: saving || !resolved ? "#E8E8E8" : "#534AB7",
                     color: saving || !resolved ? "#999" : "#fff",
                     cursor: saving || !resolved ? "not-allowed" : "pointer" }}
          >
            {saving ? "Reassigning..." : `Assign to ${resolved?.display_name || "..."}`}
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
//  Main component
// =============================================================================

export default function DocumentLifecycle() {
  const [showForm,     setShowForm]     = useState(false);
  const [detailsDoc,   setDetailsDoc]   = useState(null);
  const [reassignDoc,  setReassignDoc]  = useState(null);

  const { oid: currentUserOid } = useCurrentUser();
  const { data: docs = [], isLoading, error, refetch } = useLifecycleDocs();
  const progress = useProgress();
  const qc       = useQueryClient();

  const handleProgress = async (id, stage) => {
    try {
      await progress.mutateAsync({ id, stage });
    } catch (err) {
      alert(err.message || "Could not progress document.");
    }
  };

  const handleReassign = async (id, ownerOid, ownerName) => {
    await lifecycleApi.reassign(id, ownerOid, ownerName);
    qc.invalidateQueries({ queryKey: ["lifecycle"] });
  };

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
            const stageDocs = docs.filter(d => d.Stage === stage.key);
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
                        onProgress={handleProgress}
                        onUpload={() => {}} // handled inside card via file input
                        onReassign={setReassignDoc}
                        progressPending={progress.isPending}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modals */}
      <DetailsModal doc={detailsDoc} onClose={() => setDetailsDoc(null)} />
      {reassignDoc && (
        <ReassignModal
          doc={reassignDoc}
          onSave={handleReassign}
          onClose={() => setReassignDoc(null)}
        />
      )}
    </>
  );
}