// =============================================================================
// pages/ExtractionReview/index.jsx
// Zone 1 — Extraction Review
// Reviews controls and evidence extracted from policies and contracts.
// Accept triggers full cascade: Control Register + Evidence Tracker + Audit Log.
// Per DRG-QI-REF-DINT-01-26 Section 4.1
// =============================================================================

import { useState, useMemo, useEffect } from "react";
import { useMsal } from "@azure/msal-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { LoadingState, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import apiClient from "../../api/grcApi.js";

const EVIDENCE_TYPES = [
  ["", "Select evidence type"],
  ["LOG", "LOG — System log export"],
  ["CFG", "CFG — Configuration evidence"],
  ["APR", "APR — Signed approval record"],
  ["FRM", "FRM — Completed form/record"],
  ["TRN", "TRN — Training record"],
  ["ACK", "ACK — Policy acknowledgement"],
  ["TST", "TST — Test/drill/verification"],
  ["CRT", "CRT — Certificate/attestation"],
  ["MTG", "MTG — Meeting/governance record"],
  ["REV", "REV — Review record"],
  ["CHK", "CHK — Checklist completion"],
  ["CNT", "CNT — Contract/agreement"],
  ["INV", "INV — Inventory/register extract"],
  ["CHG", "CHG — Change record"],
  ["INC", "INC — Incident record"],
  ["RPT", "RPT — Report/assessment"],
];

const EVIDENCE_SOURCE_SYSTEMS = [
  "",
  "SharePoint",
  "Entra ID",
  "Intune",
  "Microsoft 365",
  "GitHub",
  "Jira",
  "HRIS",
  "LMS",
  "Finance system",
  "Manual register",
  "Supplier portal",
];

const CONTROL_TYPES = [
  "",
  "Preventive",
  "Detective",
  "Corrective",
  "Directive",
];

const EVIDENCE_FORMATS = [
  "",
  "URL/link",
  "PDF",
  "DOCX",
  "XLSX/CSV export",
  "Screenshot",
  "System export",
  "Email/EML",
  "Signed form",
  "Ticket/reference ID",
  "Certificate",
];

const EVIDENCE_FREQUENCIES = [
  "",
  "Continuous",
  "Monthly",
  "Per event",
  "Per occurrence",
  "Quarterly",
  "Bi-annually",
  "Annual",
  "On-demand",
];

const evidenceTypeLabel = (code) =>
  EVIDENCE_TYPES.find(([value]) => value === code)?.[1]?.replace(`${code} — `, "") || code;

// =============================================================================
//  API
// =============================================================================

const zone1Api = {
  list: () =>
    apiClient.get("/api/v1/queue/items", { params: { item_type: "Extraction" } })
      .then(r => r.data),

  acceptControl: (itemId, body) =>
    apiClient.post(`/api/v1/queue/items/${itemId}/accept-control`, body)
      .then(r => r.data),

  reject: (itemId, rationale, rejectType = "Reject") =>
    apiClient.post(`/api/v1/queue/items/${itemId}/reject`,
      { rationale, reject_type: rejectType }).then(r => r.data),

  requestSecondReview: (itemId, body) =>
    apiClient.post(`/api/v1/queue/items/${itemId}/request-second-review`, body)
      .then(r => r.data),
};

// =============================================================================
//  Hooks
// =============================================================================

function useUserRoles() {
  const { accounts } = useMsal();
  const roles = accounts[0]?.idTokenClaims?.roles || [];
  return {
    isCompliance: roles.includes("Compliance.Lead") || roles.includes("OrgOS.Admin"),
  };
}

function useZone1Items() {
  return useQuery({
    queryKey: ["zone1"],
    queryFn:  zone1Api.list,
    staleTime: 30_000,
  });
}

// =============================================================================
//  Confidence indicator
// =============================================================================

const ConfidenceDot = ({ score }) => {
  const pct = Math.round((score || 0) * 100);
  const color = pct >= 90 ? "#1D9E75" : pct >= 80 ? "#BA7517" : pct >= 60 ? "#A32D2D" : "#A32D2D";
  const label = pct >= 90 ? "High" : pct >= 80 ? "Amber" : pct >= 60 ? "Low" : "Very low";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
      <div style={{ flex: 1, height: 5, borderRadius: 3, background: "#E8E8E8", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 10, fontWeight: 600, color, minWidth: 56 }}>{pct}% {label}</span>
    </div>
  );
};

// =============================================================================
//  Chain preview — shows what Accept will create
// =============================================================================

const ChainPreview = ({ item }) => {
  const hasEvidence = item.EvidenceType && item.EvidenceDescription;
  return (
    <div style={{
      padding: "10px 12px", background: "#E6F1FB",
      borderRadius: 8, marginBottom: 12,
      border: "0.5px solid #85B7EB",
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#0C447C", marginBottom: 6 }}>
        If accepted, this creates:
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ fontSize: 11, color: "#0C447C" }}>
          → Control Register entry — {item.ControlType ? `${item.ControlType} · ` : ""}{item.ISOClause || "No clause"} · Owner: {item.ProposedOwnerRole || "Unresolved"}
        </div>
        {hasEvidence && (
          <div style={{ fontSize: 11, color: "#0C447C" }}>
            → Evidence Tracker entry — {item.EvidenceType} · {item.EvidenceFrequency || "frequency TBD"} · From: {item.EvidenceSourceSystem || "source TBD"}
          </div>
        )}
        {!hasEvidence && (
          <div style={{ fontSize: 11, color: "#BA7517" }}>
            → No evidence entry — evidence fields undefined on this item
          </div>
        )}
        <div style={{ fontSize: 11, color: "#0C447C" }}>
          → Audit log record — your identity, timestamp, rationale
        </div>
      </div>
    </div>
  );
};

// =============================================================================
//  Evidence panel
// =============================================================================

const EvidencePanel = ({ item }) => {
  if (!item.EvidenceType && !item.EvidenceDescription) return null;
  const hasUndefined = item.EvidenceUndefined && !item.EvidenceType;
  return (
    <div style={{
      padding: "10px 12px",
      background: hasUndefined ? "#FAEEDA" : "#EEEDFE",
      borderRadius: 8, marginTop: 8,
      border: `0.5px solid ${hasUndefined ? "#FAC775" : "#AFA9EC"}`,
    }}>
      <div style={{ fontSize: 11, fontWeight: 600,
                    color: hasUndefined ? "#633806" : "#3C3489", marginBottom: 6 }}>
        {hasUndefined ? "Evidence undefined — requires design" : `Evidence: ${item.EvidenceType}`}
      </div>
      {hasUndefined ? (
        <div style={{ fontSize: 11, color: "#633806" }}>
          {item.EvidenceUndefinedReason || "No source system, format, or frequency identified."}
        </div>
      ) : (
        <>
          {item.EvidenceDescription && <Field l="Description"  v={item.EvidenceDescription} />}
          {item.EvidenceSourceSystem && <Field l="Source"       v={item.EvidenceSourceSystem} />}
          {item.EvidenceFormat && <Field l="Format"       v={item.EvidenceFormat} />}
          {item.EvidenceFrequency && <Field l="Frequency"    v={item.EvidenceFrequency} />}
    
          {item.EvidenceOwnerRole && <Field l="Owner role"   v={item.EvidenceOwnerRole} />}
          {item.EvidenceValidationCriteria && (
            <Field l="Validation" v={item.EvidenceValidationCriteria} />
          )}
        </>
      )}
    </div>
  );
};


// =============================================================================
//  Decision panel
// =============================================================================

const DecisionPanel = ({ item, onDecide, onRequestSecondReview, isPending }) => {
  const [rationale, setRationale]     = useState("");
  const [editMode, setEditMode]       = useState(false);
  const [edits, setEdits]             = useState({});
  const [activeAction, setActiveAction] = useState(null);

  useEffect(() => {
    if (!editMode) return;
    setEdits(prev => ({
      control_statement: prev.control_statement ?? item.ControlStatement ?? "",
      control_type:      prev.control_type      ?? item.ControlType ?? "",
      iso_clause:        prev.iso_clause        ?? item.ISOClause ?? "",
      owner_role:        prev.owner_role        ?? item.ProposedOwnerRole ?? "",
      risk_implication:  prev.risk_implication  ?? item.RiskStatement ?? "",
      evidence_type: prev.evidence_type ?? item.EvidenceType ?? "",
      evidence_description: prev.evidence_description ?? item.EvidenceDescription ?? "",
      evidence_source_system: prev.evidence_source_system ?? item.EvidenceSourceSystem ?? "",
      evidence_format: prev.evidence_format ?? item.EvidenceFormat ?? "",
      evidence_frequency: prev.evidence_frequency ?? item.EvidenceFrequency ?? "",
    }));
  }, [editMode, item]);

  const ratOk = rationale.trim().length >= 10;

  const handleAction = async (action) => {
    if (!ratOk) return;
    if (action === "second_review") {
      setActiveAction(action);
      await onRequestSecondReview();
      setActiveAction(null);
      return;
    }
    setActiveAction(action);
    await onDecide(action, rationale.trim(), editMode ? edits : {});
    setActiveAction(null);
  };

  const editField = (k) => (e) => setEdits(p => ({ ...p, [k]: e.target.value }));

  const inputStyle = {
    width: "100%", fontSize: 11, padding: "5px 8px", borderRadius: 6,
    border: "1px solid #C0C0C0", background: "var(--color-background-primary)",
    color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box",
    marginTop: 3,
  };

  const labelStyle = {
    fontSize: 10,
    color: "var(--color-text-tertiary)",
    textTransform: "uppercase",
    letterSpacing: "0.4px",
  };

  const selectStyle = {
    ...inputStyle,
    appearance: "auto",
  };

  return (
    <div style={{ marginTop: 12 }}>
      {/* Edit toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
        <input type="checkbox" id={`edit-${item.id}`}
          checked={editMode} onChange={e => setEditMode(e.target.checked)} />
        <label htmlFor={`edit-${item.id}`}
          style={{ fontSize: 11, color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Edit before accepting
        </label>
      </div>

      {/* Edit fields */}
      {editMode && (
        <div style={{ padding: "10px 12px", background: "var(--color-background-secondary)",
                      borderRadius: 8, marginBottom: 10, border: "1px solid #D0D0D0" }}>
          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 8, color: "var(--color-text-secondary)" }}>
            Override AI values (leave blank to keep original)
          </div>
          {[
            ["control_statement", "Control statement", item.ControlStatement],
            ["iso_clause",        "ISO clause",        item.ISOClause],
            ["owner_role",        "Owner role",        item.ProposedOwnerRole],
            ["risk_implication",  "Risk implication",  item.RiskStatement],
          ].map(([key, label, placeholder]) => (
            <div key={key} style={{ marginBottom: 6 }}>
              <label style={labelStyle}>{label}</label>
              <input type="text" value={edits[key] || ""}
                onChange={editField(key)}
                placeholder={placeholder || ""}
                style={inputStyle} />
            </div>
          ))}

          <div style={{ marginBottom: 6 }}>
            <label style={labelStyle}>Control type</label>
            <select value={edits.control_type || ""} onChange={editField("control_type")} style={selectStyle}>
              {CONTROL_TYPES.map(value => (
                <option key={value || "empty"} value={value}>{value || "Select control type"}</option>
              ))}
            </select>
          </div>

          <div style={{
            marginTop: 10,
            paddingTop: 10,
            borderTop: "0.5px solid var(--color-border-tertiary)",
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 8, color: "#3C3489" }}>
              Evidence requirement
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div>
                <label style={labelStyle}>Evidence type</label>
                <select value={edits.evidence_type || ""} onChange={editField("evidence_type")} style={selectStyle}>
                  {EVIDENCE_TYPES.map(([value, label]) => (
                    <option key={value || "empty"} value={value}>{label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={labelStyle}>Source system</label>
                <select value={edits.evidence_source_system || ""} onChange={editField("evidence_source_system")} style={selectStyle}>
                  {EVIDENCE_SOURCE_SYSTEMS.map(value => (
                    <option key={value || "empty"} value={value}>{value || "Select source system"}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={labelStyle}>Format</label>
                <select value={edits.evidence_format || ""} onChange={editField("evidence_format")} style={selectStyle}>
                  {EVIDENCE_FORMATS.map(value => (
                    <option key={value || "empty"} value={value}>{value || "Select format"}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={labelStyle}>Frequency</label>
                <select value={edits.evidence_frequency || ""} onChange={editField("evidence_frequency")} style={selectStyle}>
                  {EVIDENCE_FREQUENCIES.map(value => (
                    <option key={value || "empty"} value={value}>{value || "Select frequency"}</option>
                  ))}
                </select>
              </div>
            </div>
            <div style={{ marginTop: 6 }}>
              <label style={labelStyle}>Evidence description</label>
              <input type="text" value={edits.evidence_description || ""}
                onChange={editField("evidence_description")}
                placeholder={item.EvidenceDescription || "Describe the artefact that proves the control operates"}
                style={inputStyle} />
            </div>
          </div>
        </div>
      )}

      {/* Rationale */}
      <textarea
        value={rationale}
        onChange={e => setRationale(e.target.value)}
        placeholder="Decision rationale — required (min 10 characters). Explain why you are making this decision. This is your audit trail."
        rows={3}
        style={{
          width: "100%", fontSize: 12, padding: "9px 12px", borderRadius: 8,
          border: `1.5px solid ${ratOk ? "#5DCAA5" : "#C0C0C0"}`,
          background: "var(--color-background-primary)",
          color: "var(--color-text-primary)", resize: "vertical",
          fontFamily: "var(--font-sans)", marginBottom: 10,
          boxSizing: "border-box", outline: "none",
        }}
        onFocus={e => (e.target.style.borderColor = "#378ADD")}
        onBlur={e => (e.target.style.borderColor = ratOk ? "#5DCAA5" : "#C0C0C0")}
      />

      {!ratOk && rationale.length > 0 && (
        <div style={{ fontSize: 10, color: "#A32D2D", marginBottom: 8 }}>
          Rationale must be at least 10 characters
        </div>
      )}

      {/* Decision buttons */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <button
          onClick={() => handleAction("accept")}
          disabled={!ratOk || isPending}
          style={{ padding: "10px", fontSize: 12, borderRadius: 8, border: "none",
                   background: !ratOk || isPending ? "#E8E8E8" : "#1D9E75",
                   color: !ratOk || isPending ? "#999" : "#fff",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer",
                   fontWeight: 600, gridColumn: editMode ? "1 / 3" : "1" }}
        >
          {activeAction === "accept" ? "Creating records..." : editMode ? "Edit & Accept →" : "Accept →"}
        </button>

        {!editMode && (
          <button
            onClick={() => setEditMode(true)}
            disabled={isPending}
            style={{ padding: "10px", fontSize: 12, borderRadius: 8,
                     border: "1.5px solid #C0C0C0", background: "transparent",
                     color: "var(--color-text-primary)", cursor: "pointer" }}
          >
            Edit & accept
          </button>
        )}

        <button
          onClick={() => handleAction("reject")}
          disabled={!ratOk || isPending}
          style={{ padding: "10px", fontSize: 12, borderRadius: 8, border: "none",
                   background: !ratOk || isPending ? "#E8E8E8" : "#A32D2D",
                   color: !ratOk || isPending ? "#999" : "#fff",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer", fontWeight: 500 }}
        >
          Reject
        </button>

        <button
          onClick={() => handleAction("false_positive")}
          disabled={!ratOk || isPending}
          style={{ padding: "10px", fontSize: 12, borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "transparent",
                   color: "var(--color-text-secondary)",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer" }}
        >
          Mark false positive
        </button>

        <button
          onClick={() => handleAction("second_review")}
          disabled={!ratOk || isPending}
          style={{ padding: "10px", fontSize: 12, borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "transparent",
                   color: "var(--color-text-secondary)",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer" }}
        >
          Request 2nd review
        </button>
      </div>
    </div>
  );
};

const SecondReviewModal = ({ open, item, onClose, onSubmit, isPending }) => {
  const [query, setQuery] = useState("");
  const [reviewer, setReviewer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [rationale, setRationale] = useState("");

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setReviewer(null);
    setError("");
    setRationale("");
  }, [open, item]);

  const searchReviewer = async () => {
    const value = query.trim();
    if (!value) {
      setError("Enter a Microsoft 365 email or UPN.");
      return;
    }
    setLoading(true);
    setError("");
    setReviewer(null);
    try {
      const data = await apiClient.get("/api/v1/grc/users/resolve", { params: { email: value } }).then(r => r.data);
      setReviewer(data);
    } catch (err) {
      setError(err.message || "No person found.");
    } finally {
      setLoading(false);
    }
  };

  const canSubmit = reviewer && rationale.trim().length >= 10;

  if (!open || !item) return null;

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
               display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: 480, maxWidth: "100%", background: "var(--color-background-primary)",
                 borderRadius: 16, boxShadow: "0 24px 60px rgba(0,0,0,0.18)", padding: 20 }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Request second review</div>
            <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 4 }}>
              Search for the person who should conduct the second review and add a rationale.
            </div>
          </div>
          <button onClick={onClose} style={{ border: "none", background: "transparent", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>
            ×
          </button>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={{ display: "block", marginBottom: 6, fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.4px" }}>
            Reviewer dragnet mail
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="user@dragnet.com"
              style={{ flex: 1, fontSize: 13, padding: "10px 12px", borderRadius: 10, border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)", color: "var(--color-text-primary)" }}
            />
            <button
              onClick={searchReviewer}
              disabled={loading}
              style={{ minWidth: 112, padding: "10px 14px", borderRadius: 10, border: "1px solid #0C447C", background: "#0C447C", color: "#fff", cursor: "pointer", fontWeight: 600 }}
            >
              {loading ? "Searching…" : "Find"}
            </button>
          </div>
          {error && <div style={{ marginTop: 8, fontSize: 11, color: "#A32D2D" }}>{error}</div>}
        </div>

        {reviewer && (
          <div style={{ padding: 12, borderRadius: 12, border: "1px solid #D0D0D0", background: "var(--color-background-secondary)", marginBottom: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)", marginBottom: 4 }}>
              {reviewer.display_name || reviewer.email}
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 6 }}>
              {reviewer.email} {reviewer.job_title ? `· ${reviewer.job_title}` : ""}
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
              Selected reviewer for second review.
            </div>
          </div>
        )}

        <div style={{ marginBottom: 14 }}>
          <label style={{ display: "block", marginBottom: 6, fontSize: 10, fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.4px" }}>
            second review request
          </label>
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            rows={4}
            placeholder="Explain to your reviewer why you are requesting a second review. This helps them understand what to focus on and provides context. Minimum 10 characters."
            style={{ width: "100%", fontSize: 13, padding: "10px 12px", borderRadius: 10, border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)", color: "var(--color-text-primary)", resize: "vertical" }}
          />
          {rationale.trim().length > 0 && rationale.trim().length < 10 && (
            <div style={{ marginTop: 6, fontSize: 11, color: "#A32D2D" }}>
              Rationale must be at least 10 characters.
            </div>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button onClick={onClose} style={{ padding: "10px 14px", borderRadius: 10, background: "transparent", color: "var(--color-text-secondary)", border: "1.5px solid #C0C0C0", cursor: "pointer" }}>
            Cancel
          </button>
          <button
            onClick={() => onSubmit({ rationale: rationale.trim(), reviewer })}
            disabled={!canSubmit || isPending}
            style={{ padding: "10px 14px", borderRadius: 10, border: "none", background: canSubmit && !isPending ? "#1D9E75" : "#E8E8E8", color: canSubmit && !isPending ? "#fff" : "#999", cursor: canSubmit && !isPending ? "pointer" : "not-allowed", fontWeight: 600 }}
          >
            {isPending ? "Requesting…" : "Send request"}
          </button>
        </div>
      </div>
    </div>
  );
};

// =============================================================================
//  Document viewer — embeds SharePoint document inline
// =============================================================================

const DocumentViewer = ({ url, docCode }) => {
  const [expanded, setExpanded] = useState(false);

  // Use the URL directly in the iframe — SharePoint handles sharing link redirects.
  // The wdStartOn and action=embedview params only work with direct file URLs, not sharing links.
  const embedUrl = url;

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "#0C447C" }}>
          Source document — {docCode}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
         
          <a href={url} target="_blank" rel="noreferrer"
            style={{ fontSize: 11, padding: "3px 10px", borderRadius: 5,
                     border: "1px solid #85B7EB", background: "transparent",
                     color: "#0C447C", textDecoration: "none" }}>
            Open in SharePoint ↗
          </a>
        </div>
      </div>

      {expanded && (
        <div style={{ borderRadius: 8, overflow: "hidden",
                      border: "1px solid #85B7EB" }}>
          <div style={{ padding: "10px 14px", background: "#E6F1FB",
                        fontSize: 11, color: "#0C447C" }}>
            SharePoint preview — use "Open in SharePoint ↗" for full editing access.
          </div>
          <iframe
            src={embedUrl}
            width="100%"
            height="520"
            frameBorder="0"
            title={`Source: ${docCode}`}
            style={{ display: "block" }}
          />
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Extraction item card
// =============================================================================

const ExtractionCard = ({ item, isCompliance, onDecide, onRequestSecondReview, isPending }) => {
  const [expanded, setExpanded] = useState(false);
  const isDecided = item.ReviewStatus && item.ReviewStatus !== "Pending Review";
  const pct = Math.round((item.ConfidenceScore || 0) * 100);

  return (
    <div style={{
      border: `1px solid ${isDecided ? "#D0D0D0" : "#85B7EB"}`,
      borderLeft: `4px solid ${isDecided ? "#D0D0D0" : "#0C447C"}`,
      borderRadius: 12,
      background: isDecided ? "var(--color-background-secondary)" : "var(--color-background-primary)",
      opacity: isDecided ? 0.65 : 1,
      transition: "box-shadow 0.15s",
    }}
      onMouseEnter={e => !isDecided && (e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)")}
      onMouseLeave={e => (e.currentTarget.style.boxShadow = "none")}
    >
      {/* Header */}
      <div
        role="button" tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={e => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "12px 14px", cursor: "pointer" }}
      >
        {/* Badges */}
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 6, flexWrap: "wrap", gap: 4 }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {item.DocumentType    && <StatusBadge label={item.DocumentType} />}
            {item.ControlType     && <StatusBadge label={item.ControlType} />}
            {item.CompletenessFlag === "DEFICIENT" && <StatusBadge label="Deficient" />}
            {pct < 60 && (
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3,
                             background: "#FCEBEB", color: "#791F1F",
                             border: "0.5px solid #F09595", fontWeight: 600 }}>
                VERY LOW CONFIDENCE
              </span>
            )}
            {isDecided && <StatusBadge label={item.ReviewStatus} />}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        {/* Control statement */}
        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 6 }}>
          {item.ControlStatement || item.Title || "Untitled item"}
        </div>


        {/* Risk + confidence */}
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", gap: 12 }}>
          {item.RiskStatement && (
            <div style={{ fontSize: 11, color: "#A32D2D", flex: 1 }}>
              Risk: {item.RiskStatement.length > 400
                ? item.RiskStatement.slice(0, 400) + "..." : item.RiskStatement}
            </div>
          )}
          <div style={{ minWidth: 160 }}>
            <ConfidenceDot score={item.ConfidenceScore} />
          </div>
        </div>

        {/* Source */}
        <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4 }}>
          {item.SourceDocumentCode}{item.SourceClause ? ` · ${item.SourceClause}` : ""}
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div style={{ borderTop: `1px solid #85B7EB`, padding: "14px 14px" }}>

          {/* If already decided — show outcome */}
          {isDecided ? (
            <div style={{ padding: "10px 12px", background: "#E1F5EE",
                          borderRadius: 8, marginBottom: 12,
                          border: "1px solid #5DCAA5" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#085041", marginBottom: 3 }}>
                {item.ReviewStatus} — {item.Decision}
              </div>
              {item.DecisionRationale && (
                <div style={{ fontSize: 11, color: "#085041", fontStyle: "italic" }}>
                  "{item.DecisionRationale}"
                </div>
              )}
              {item.CascadeResult && (
                <div style={{ fontSize: 10, color: "#085041", marginTop: 4, opacity: 0.8 }}>
                  {item.CascadeResult}
                </div>
              )}
            </div>
          ) : isCompliance ? (
            <>
              <ChainPreview item={item} />
              <DecisionPanel
                item={item}
                onDecide={(action, rationale, edits) => onDecide(item.id, action, rationale, edits)}
                onRequestSecondReview={() => onRequestSecondReview(item)}
                isPending={isPending}
              />
            </>
          ) : (
            <div style={{ padding: "10px 12px", background: "var(--color-background-secondary)",
                          borderRadius: 8, marginBottom: 12, fontSize: 12,
                          color: "var(--color-text-tertiary)",
                          border: "1px dashed var(--color-border-tertiary)" }}>
              Compliance Lead role required to make decisions.
            </div>
          )}

          {/* Full details below decisions */}
          <div style={{ borderTop: "0.5px solid var(--color-border-tertiary)", paddingTop: 12, marginTop: 4 }}>
            {item.ISOClause        && <Field l="ISO clause"     v={item.ISOClause} />}
            {item.ProposedOwnerRole && <Field l="Proposed owner" v={item.ProposedOwnerRole} />}
            {item.SourceType       && <Field l="Source type"    v={item.SourceType} />}
            {item.DeficiencyReason && (
              <div style={{ padding: "6px 10px", background: "#FCEBEB", borderRadius: 6,
                            fontSize: 11, color: "#791F1F", marginTop: 6 }}>
                Deficiency: {item.DeficiencyReason}
              </div>
            )}
            <EvidencePanel item={item} />

            {/* Document viewer */}
            {item.SourceDocumentUrl && (
              <DocumentViewer url={item.SourceDocumentUrl} docCode={item.SourceDocumentCode} />
            )}
            {!item.SourceDocumentUrl && item.SourceDocumentCode && (
              <div style={{ marginTop: 10, padding: "7px 10px",
                            background: "var(--color-background-secondary)",
                            borderRadius: 7, fontSize: 11, color: "var(--color-text-tertiary)",
                            border: "0.5px solid var(--color-border-tertiary)" }}>
                Source: {item.SourceDocumentCode}
                {item.SourceClause ? ` · ${item.SourceClause}` : ""}
                {" — Document URL not stored. Add SourceDocumentUrl to this queue item to enable embedded viewing."}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Main component
// =============================================================================

export default function ExtractionReview() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("pending");
  const [actionState, setActionState] = useState({ pending: false, itemId: null });
  const [secondReviewModal, setSecondReviewModal] = useState({ open: false, item: null });

  const { isCompliance } = useUserRoles();
  const qc = useQueryClient();
  const { data: items = [], isLoading, error, refetch } = useZone1Items();

  const pendingCount = items.filter(
    i => !i.ReviewStatus || i.ReviewStatus === "Pending Review"
  ).length;

  const acceptedCount = items.filter(i => i.ReviewStatus === "Accepted").length;
  const rejectedCount = items.filter(i => i.ReviewStatus === "Rejected").length;
  const falsePositiveCount = items.filter(i => i.ReviewStatus === "False Positive").length;
  const secondReviewCount = items.filter(i => i.ReviewStatus === "Second Review Requested").length;

  const filtered = useMemo(() => {
    let list = filter === "pending"
      ? items.filter(i => !i.ReviewStatus || i.ReviewStatus === "Pending Review")
      : filter === "accepted"
        ? items.filter(i => i.ReviewStatus === "Accepted")
        : filter === "rejected"
          ? items.filter(i => i.ReviewStatus === "Rejected")
          : filter === "false_positive"
            ? items.filter(i => i.ReviewStatus === "False Positive")
            : filter === "second_review"
              ? items.filter(i => i.ReviewStatus === "Second Review Requested")
              : items;

    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(i =>
        (i.ControlStatement || "").toLowerCase().includes(q) ||
        (i.SourceDocumentCode || "").toLowerCase().includes(q) ||
        (i.ProposedOwnerRole || "").toLowerCase().includes(q) ||
        (i.ISOClause || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [items, search, filter]);

  const openSecondReviewModal = (item) => {
    setSecondReviewModal({ open: true, item });
  };

  const closeSecondReviewModal = () => {
    setSecondReviewModal({ open: false, item: null });
  };

  const handleSecondReviewSubmit = async ({ rationale, reviewer }) => {
    if (!secondReviewModal.item) return;
    setActionState({ pending: true, itemId: secondReviewModal.item.id });
    try {
      await zone1Api.requestSecondReview(secondReviewModal.item.id, {
        rationale,
        reviewer_oid: reviewer?.oid,
        reviewer_name: reviewer?.display_name,
        reviewer_email: reviewer?.email,
      });
      qc.invalidateQueries({ queryKey: ["zone1"] });
      closeSecondReviewModal();
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Request failed.");
    } finally {
      setActionState({ pending: false, itemId: null });
    }
  };

  const handleDecide = async (itemId, action, rationale, edits) => {
    setActionState({ pending: true, itemId });
    try {
      if (action === "accept") {
        await zone1Api.acceptControl(itemId, {
          rationale,
          ...Object.fromEntries(Object.entries(edits).filter(([, v]) => v)),
        });
      } else if (action === "reject") {
        await zone1Api.reject(itemId, rationale, "Reject");
      } else if (action === "false_positive") {
        await zone1Api.reject(itemId, rationale, "Mark False Positive");
      }
      qc.invalidateQueries({ queryKey: ["zone1"] });
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Decision failed.");
    } finally {
      setActionState({ pending: false, itemId: null });
    }
  };

  if (isLoading) return <LoadingState message="Loading extraction items..." />;
  if (error)     return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
              Extraction review
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Zone 1 — Controls and evidence extracted from policies and contracts.
              Accept creates permanent Control Register and Evidence Tracker entries.
            </div>
          </div>
          <div style={{ padding: "3px 10px", background: "#E6F1FB", borderRadius: 6,
                        fontSize: 11, color: "#0C447C", fontWeight: 600,
                        border: "0.5px solid #85B7EB", flexShrink: 0 }}>
            {pendingCount} pending
          </div>
        </div>
        {!isCompliance && (
          <div style={{ marginTop: 8, padding: "8px 12px", background: "#FAEEDA",
                        borderRadius: 8, fontSize: 12, color: "#633806",
                        border: "0.5px solid #FAC775" }}>
            View only — Compliance Lead role required to make decisions.
          </div>
        )}
      </div>

      <SecondReviewModal
        open={secondReviewModal.open}
        item={secondReviewModal.item}
        isPending={actionState.pending && secondReviewModal.item?.id === actionState.itemId}
        onClose={closeSecondReviewModal}
        onSubmit={handleSecondReviewSubmit}
      />

      {/* Filters */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {[
          { k: "all",           l: `All (${items.length})` },
          { k: "pending",       l: `Pending (${pendingCount})` },
          { k: "accepted",      l: `Accepted (${acceptedCount})` },
          { k: "rejected",      l: `Rejected (${rejectedCount})` },
          { k: "false_positive", l: `False positive (${falsePositiveCount})` },
          { k: "second_review", l: `2nd review (${secondReviewCount})` },
        ].map(f => (
          <button key={f.k} onClick={() => setFilter(f.k)}
            style={{ padding: "5px 12px", fontSize: 12, borderRadius: 6, cursor: "pointer",
                     fontWeight: filter === f.k ? 600 : 400,
                     border: filter === f.k ? "1px solid var(--color-border-info)" : "1.5px solid #C0C0C0",
                     background: filter === f.k ? "var(--color-background-info)" : "var(--color-background-primary)",
                     color: filter === f.k ? "var(--color-text-info)" : "var(--color-text-secondary)" }}>
            {f.l}
          </button>
        ))}
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search by control, document, owner, ISO clause..."
          style={{ flex: 1, minWidth: 200, fontSize: 12, padding: "6px 12px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {/* Items */}
      {filtered.length === 0 ? (
        <EmptyState message={
          pendingCount === 0
            ? "All items reviewed. Run the bulk extractor to process more documents."
            : "No items match your search."
        } />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map(item => (
            <ExtractionCard
              key={item.id}
              item={item}
              isCompliance={isCompliance}
              onDecide={handleDecide}
              onRequestSecondReview={openSecondReviewModal}
              isPending={actionState.pending && actionState.itemId === item.id}
            />
          ))}
        </div>
      )}

      {filtered.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 8 }}>
          {filtered.length} of {items.length}
        </div>
      )}
    </>
  );
}
