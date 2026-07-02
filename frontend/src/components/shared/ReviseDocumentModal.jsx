// =============================================================================
// components/shared/ReviseDocumentModal.jsx
// DINT §5.3.2 — put an ACTIVE Document Register document back into the
// Document Lifecycle for amendment.
//
// Two entry points share this modal:
//   Document Register detail  → pass `document` (the selected register doc)
//   Document Lifecycle screen → omit `document`; a picker of Active documents
//                               is shown first ("+ Revise existing")
//
// On submit: POST /api/v1/lifecycle/documents/revise. The active version stays
// live in the register (status → Under Review) until the revision is approved;
// approval updates the register entry in place with a version bump (R01 → R02).
// =============================================================================

import { useEffect, useMemo, useState } from "react";
import apiClient from "../../api/grcApi.js";

const REASONS = [
  "Scheduled Review",
  "NC Corrective Action",
  "Business Initiative",
  "Gap Remediation",
  "Sphere of Influence Review",
  "Other",
];

const CONDITIONAL_FIELD = {
  "NC Corrective Action":       { key: "nc_reference",        label: "NC reference",        placeholder: "Incident / NC register reference" },
  "Gap Remediation":            { key: "gap_reference",       label: "Gap reference",       placeholder: "Gap Analysis id, e.g. GAP-ISO27001-26-001" },
  "Sphere of Influence Review": { key: "triggering_document", label: "Triggering document", placeholder: "Document code of the revised document that triggered this" },
};

const inputStyle = (ok) => ({
  width: "100%", fontSize: 13, padding: "9px 11px", borderRadius: 9,
  border: `1.5px solid ${ok ? "#5DCAA5" : "#C0C0C0"}`,
  background: "var(--color-background-primary)",
  color: "var(--color-text-primary)", boxSizing: "border-box", outline: "none",
});

const labelStyle = {
  display: "block", fontSize: 10, fontWeight: 600,
  color: "var(--color-text-secondary)", marginBottom: 5,
  textTransform: "uppercase", letterSpacing: "0.4px",
};

export default function ReviseDocumentModal({ open, onClose, document: docProp, onRevised }) {
  const [pickedDoc, setPickedDoc]     = useState(null);
  const [activeDocs, setActiveDocs]   = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docSearch, setDocSearch]     = useState("");

  const [reason, setReason]           = useState("Scheduled Review");
  const [description, setDescription] = useState("");
  const [refValue, setRefValue]       = useState("");
  const [saving, setSaving]           = useState(false);
  const [error, setError]             = useState("");

  const doc = docProp || pickedDoc;

  useEffect(() => {
    if (!open) return;
    setPickedDoc(null);
    setDocSearch("");
    setReason("Scheduled Review");
    setDescription("");
    setRefValue("");
    setError("");
    setSaving(false);
    // Picker mode — load Active register documents
    if (!docProp) {
      setDocsLoading(true);
      apiClient.get("/api/v1/grc/documents", { params: { status: "Active" } })
        .then(r => setActiveDocs(r.data || []))
        .catch(err => setError(err.response?.data?.detail || err.message || "Could not load documents."))
        .finally(() => setDocsLoading(false));
    }
  }, [open, docProp]);

  const filteredDocs = useMemo(() => {
    const q = docSearch.trim().toLowerCase();
    if (!q) return activeDocs;
    return activeDocs.filter(d =>
      (d.document_code || "").toLowerCase().includes(q) ||
      (d.title || "").toLowerCase().includes(q) ||
      (d.department || "").toLowerCase().includes(q)
    );
  }, [activeDocs, docSearch]);

  if (!open) return null;

  const conditional = CONDITIONAL_FIELD[reason];
  const descOk = description.trim().length >= 10;
  const refOk  = !conditional || refValue.trim().length > 0;
  const canSubmit = doc && descOk && refOk && !saving;

  const submit = async () => {
    if (!canSubmit) return;
    setSaving(true);
    setError("");
    try {
      const body = {
        document_register_id: String(doc.id),
        reason,
        description: description.trim(),
      };
      if (conditional) body[conditional.key] = refValue.trim();
      const created = await apiClient.post("/api/v1/lifecycle/documents/revise", body).then(r => r.data);
      onRevised?.(created);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Could not start the revision.");
      setSaving(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1100,
               display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{ width: 520, maxWidth: "100%", maxHeight: "88vh", overflowY: "auto",
                 background: "var(--color-background-primary)", borderRadius: 16,
                 boxShadow: "0 24px 60px rgba(0,0,0,0.18)", padding: 20 }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Revise document</div>
            <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 4, lineHeight: 1.45 }}>
              {doc
                ? <>Re-open <strong>{doc.document_code}</strong> ({doc.current_version || "R01"}) for amendment.</>
                : "Select an active document to re-open for amendment."}
            </div>
          </div>
          <button onClick={onClose}
            style={{ border: "none", background: "transparent", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>
            ×
          </button>
        </div>

        {/* Picker mode */}
        {!docProp && !pickedDoc && (
          <div>
            <input
              autoFocus
              value={docSearch}
              onChange={e => setDocSearch(e.target.value)}
              placeholder="Search active documents by code, title, department..."
              style={{ ...inputStyle(false), marginBottom: 8 }}
            />
            {docsLoading ? (
              <div style={{ padding: 14, fontSize: 12, color: "var(--color-text-tertiary)", textAlign: "center" }}>
                Loading active documents…
              </div>
            ) : (
              <div style={{ maxHeight: 260, overflowY: "auto", border: "1px solid #D0D0D0",
                            borderRadius: 10, marginBottom: 8 }}>
                {filteredDocs.length === 0 ? (
                  <div style={{ padding: 14, fontSize: 12, color: "var(--color-text-tertiary)", textAlign: "center" }}>
                    No active documents{docSearch ? " match your search" : ""}.
                  </div>
                ) : filteredDocs.map(d => (
                  <div
                    key={d.id}
                    role="button" tabIndex={0}
                    onClick={() => setPickedDoc(d)}
                    onKeyDown={e => e.key === "Enter" && setPickedDoc(d)}
                    style={{ padding: "9px 12px", borderBottom: "1px solid #E8E8E8", cursor: "pointer" }}
                    onMouseEnter={e => (e.currentTarget.style.background = "var(--color-background-info)")}
                    onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                  >
                    <div style={{ fontSize: 12, fontWeight: 600 }}>{d.title}</div>
                    <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", fontFamily: "var(--font-mono)" }}>
                      {d.document_code} · {d.current_version || "R01"} · {d.department || "—"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Revision form */}
        {doc && (
          <>
            {!docProp && (
              <button
                onClick={() => setPickedDoc(null)}
                style={{ fontSize: 11, color: "var(--color-text-info)", background: "none",
                         border: "none", cursor: "pointer", padding: 0, marginBottom: 10 }}
              >
                ← Choose a different document
              </button>
            )}

            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>Reason for revision</label>
              <select
                value={reason}
                onChange={e => setReason(e.target.value)}
                style={{ ...inputStyle(true), appearance: "auto" }}
              >
                {REASONS.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>

            {conditional && (
              <div style={{ marginBottom: 12 }}>
                <label style={labelStyle}>
                  {conditional.label} <span style={{ color: "#A32D2D" }}>*</span>
                </label>
                <input
                  value={refValue}
                  onChange={e => setRefValue(e.target.value)}
                  placeholder={conditional.placeholder}
                  style={inputStyle(refValue.trim().length > 0)}
                />
              </div>
            )}

            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>
                What needs changing and why <span style={{ color: "#A32D2D" }}>*</span>
              </label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                rows={3}
                placeholder="Describe the amendment needed (min 10 characters). This appears on the lifecycle task."
                style={{ ...inputStyle(descOk), resize: "vertical", fontFamily: "var(--font-sans)" }}
              />
              {description.trim().length > 0 && !descOk && (
                <div style={{ marginTop: 4, fontSize: 10, color: "#A32D2D" }}>
                  Description must be at least 10 characters.
                </div>
              )}
            </div>

            {/* What happens next */}
            <div style={{ padding: "10px 12px", background: "#E6F1FB", borderRadius: 8,
                          border: "0.5px solid #85B7EB", marginBottom: 14 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#0C447C",
                            textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6 }}>
                What happens next
              </div>
              <div style={{ fontSize: 11, color: "#0C447C", lineHeight: 1.55 }}>
                ＋ <strong>Document Lifecycle</strong> — revision task enters at Review, assigned to the document owner, current approved file attached.<br />
                ↻ <strong>Document Register</strong> — {doc.document_code} is flagged Under Review; the current version stays live until the revision is approved.<br />
                ↻ On approval — the register entry updates in place ({doc.current_version || "R01"} → next revision), and the document is re-extracted into Extraction Review.
              </div>
            </div>

            {error && (
              <div style={{ padding: "9px 12px", background: "#FCEBEB", border: "1px solid #F09595",
                            borderRadius: 8, fontSize: 12, color: "#791F1F", marginBottom: 12 }}>
                {error}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button onClick={onClose}
                style={{ padding: "10px 14px", borderRadius: 10, background: "transparent",
                         color: "var(--color-text-secondary)", border: "1.5px solid #C0C0C0", cursor: "pointer" }}>
                Cancel
              </button>
              <button
                onClick={submit}
                disabled={!canSubmit}
                style={{ padding: "10px 14px", borderRadius: 10, border: "none",
                         background: canSubmit ? "#378ADD" : "#E8E8E8",
                         color: canSubmit ? "#fff" : "#999",
                         cursor: canSubmit ? "pointer" : "not-allowed", fontWeight: 600 }}
              >
                {saving ? "Starting revision…" : "Start revision →"}
              </button>
            </div>
          </>
        )}

        {error && !doc && (
          <div style={{ padding: "9px 12px", background: "#FCEBEB", border: "1px solid #F09595",
                        borderRadius: 8, fontSize: 12, color: "#791F1F", marginTop: 8 }}>
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
