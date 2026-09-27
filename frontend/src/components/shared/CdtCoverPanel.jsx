// =============================================================================
// CdtCoverPanel.jsx — edit a document's CDT v06 cover facts + live PDF preview
//
// Every cover field is editable at any time (confirmed by the compliance
// officer — nothing on the cover is "set once and locked"). The Owner /
// First Pass Approval / Final Approval fields are ROLE or GROUP labels (e.g.
// "Compliance Team"), never a specific person — reuses JobTitleInput, which
// already suggests both real job titles and OrgOS groups.
//
// "Preview PDF" merges the document's CURRENT cover facts into its source
// .docx server-side and returns a PDF (Microsoft Graph's native conversion —
// no local converter). The source file itself is never modified.
//
// Depends on: GET/PATCH /api/v1/lifecycle/documents/{id}/cover,
//             GET /api/v1/lifecycle/documents/{id}/preview.pdf
// =============================================================================

import { useEffect, useState } from "react";
import JobTitleInput from "./JobTitleInput.jsx";
import { useAlert } from "./AlertModal.jsx";

const EMPTY_COVER = {
  domain: "", parent_document: "", type_layer: "", classification: "",
  distribution: "", owner: "", first_pass_approval: "", final_approval: "",
  version: "", effective_date: "", next_review_due: "",
};

const inputStyle = {
  width: "100%", padding: "8px 10px", fontSize: 12.5, borderRadius: 8,
  border: "1.5px solid var(--color-border-tertiary)", boxSizing: "border-box",
  background: "var(--color-background-primary)", color: "var(--color-text-primary)",
};
const labelStyle = {
  fontSize: 10.5, fontWeight: 700, color: "var(--color-text-tertiary)",
  textTransform: "uppercase", letterSpacing: "0.4px", marginBottom: 4, display: "block",
};
const btn = (bg, fg = "#fff", bd = "none") => ({
  padding: "9px 16px", fontSize: 12.5, fontWeight: 600, borderRadius: 9,
  border: bd, background: bg, color: fg, cursor: "pointer",
});

function Field({ label, value, onChange, roleInput }) {
  return (
    <div>
      <label style={labelStyle}>{label}</label>
      {roleInput ? (
        <JobTitleInput value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle} />
      ) : (
        <input value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle} />
      )}
    </div>
  );
}

function StandardsEditor({ standards, setStandards }) {
  const update = (i, key, val) => {
    const next = [...standards];
    next[i] = { ...next[i], [key]: val };
    setStandards(next);
  };
  const remove = (i) => setStandards(standards.filter((_, idx) => idx !== i));
  const add = () => setStandards([...standards, { name: "", reference: "" }]);

  return (
    <div>
      <label style={labelStyle}>Standards (grows as needed — ISO, NDPA, future certifications)</label>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {standards.map((s, i) => (
          <div key={i} style={{ display: "flex", gap: 6 }}>
            <input value={s.name} onChange={(e) => update(i, "name", e.target.value)}
              placeholder="e.g. ISO 9001:2015" style={{ ...inputStyle, flex: 1 }} />
            <input value={s.reference} onChange={(e) => update(i, "reference", e.target.value)}
              placeholder="e.g. Clause 7.5" style={{ ...inputStyle, flex: 1 }} />
            <button onClick={() => remove(i)} title="Remove" style={{
              border: "1.5px solid var(--color-border-tertiary)", background: "transparent",
              borderRadius: 8, color: "var(--color-text-tertiary)", cursor: "pointer", padding: "0 10px" }}>×</button>
          </div>
        ))}
        {standards.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>No standards listed yet.</div>
        )}
      </div>
      <button onClick={add} style={{ marginTop: 6, fontSize: 11.5, fontWeight: 600,
        color: "#085041", background: "#E7F5F0", border: "1px solid #9FD9C8",
        borderRadius: 8, padding: "5px 11px", cursor: "pointer" }}>+ Add standard</button>
    </div>
  );
}

function HistoryEditor({ history, setHistory }) {
  const update = (i, key, val) => {
    const next = [...history];
    next[i] = { ...next[i], [key]: val };
    setHistory(next);
  };
  const remove = (i) => setHistory(history.filter((_, idx) => idx !== i));
  const add = () => setHistory([...history, { version: "", date: "", purpose: "", approved_by: "" }]);

  return (
    <div>
      <label style={labelStyle}>Revision history</label>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {history.map((h, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "0.6fr 0.8fr 1.6fr 1fr auto", gap: 6 }}>
            <input value={h.version} onChange={(e) => update(i, "version", e.target.value)}
              placeholder="Version" style={inputStyle} />
            <input value={h.date} onChange={(e) => update(i, "date", e.target.value)}
              placeholder="Date" style={inputStyle} />
            <input value={h.purpose} onChange={(e) => update(i, "purpose", e.target.value)}
              placeholder="Purpose of change" style={inputStyle} />
            <input value={h.approved_by} onChange={(e) => update(i, "approved_by", e.target.value)}
              placeholder="Approved by" style={inputStyle} />
            <button onClick={() => remove(i)} title="Remove" style={{
              border: "1.5px solid var(--color-border-tertiary)", background: "transparent",
              borderRadius: 8, color: "var(--color-text-tertiary)", cursor: "pointer" }}>×</button>
          </div>
        ))}
        {history.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>No revision history yet.</div>
        )}
      </div>
      <button onClick={add} style={{ marginTop: 6, fontSize: 11.5, fontWeight: 600,
        color: "#085041", background: "#E7F5F0", border: "1px solid #9FD9C8",
        borderRadius: 8, padding: "5px 11px", cursor: "pointer" }}>+ Add row</button>
    </div>
  );
}

export default function CdtCoverPanel({ docId, docCode, lifecycleApi, onClose }) {
  const { notify } = useAlert();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [cover, setCover] = useState(EMPTY_COVER);
  const [standards, setStandards] = useState([]);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const data = await lifecycleApi.getCover(docId);
        if (!live) return;
        setCover({ ...EMPTY_COVER, ...(data.cover || {}) });
        setStandards(data.cover?.standards || []);
        setHistory(data.revision_history || []);
      } catch (e) {
        if (live) setError(e?.response?.data?.detail || e.message || "Could not load cover facts.");
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => { live = false; };
  }, [docId]);

  const set = (key) => (val) => setCover((c) => ({ ...c, [key]: val }));

  const save = async () => {
    setSaving(true); setError("");
    try {
      await lifecycleApi.updateCover(docId, {
        ...cover,
        standards: standards.filter((s) => s.name.trim() || s.reference.trim()),
        revision_history: history.filter((h) => h.version.trim() || h.date.trim() || h.purpose.trim() || h.approved_by.trim()),
      });
      notify({ tone: "success", title: "Cover facts saved", message: docCode || "" });
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message || "Save failed.";
      setError(msg);
      notify({ tone: "danger", title: "Save failed", message: msg });
    } finally {
      setSaving(false);
    }
  };

  const preview = async () => {
    setPreviewing(true); setError("");
    try {
      const blob = await lifecycleApi.previewPdf(docId);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noreferrer");
      // Object URLs are per-tab; release ours after a delay so the new tab has time to load it.
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) {
      const msg = e.message || "Preview failed.";
      setError(msg);
      notify({ tone: "danger", title: "Preview failed", message: msg });
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 1000, background: "rgba(17,20,24,0.55)",
      display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "5vh 16px", overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "100%", maxWidth: 720, background: "var(--color-background-primary)",
        borderRadius: 16, boxShadow: "0 24px 60px rgba(0,0,0,0.3)", overflow: "hidden",
        display: "flex", flexDirection: "column", maxHeight: "90vh",
      }}>
        <div style={{ padding: "18px 22px", borderBottom: "1px solid var(--color-border-tertiary)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 800, color: "var(--color-text-primary)" }}>Cover & control facts</div>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>
                {docCode || "Document"} — these fill the document's cover page. Editable at any time.
              </div>
            </div>
            <button onClick={onClose} style={{ fontSize: 20, lineHeight: 1, border: "none",
              background: "transparent", color: "var(--color-text-tertiary)", cursor: "pointer" }}>×</button>
          </div>
        </div>

        <div style={{ padding: "16px 22px", overflowY: "auto", flex: 1 }}>
          {loading && <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Loading cover facts…</div>}
          {error && (
            <div style={{ fontSize: 12.5, color: "#A32D2D", background: "#FCEBEB",
              border: "1px solid #F09595", borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>
              {error}
              {error.toLowerCase().includes("cdtcoverfacts") && (
                <div style={{ marginTop: 4, fontStyle: "italic" }}>
                  An admin needs to add the "CDTCoverFacts" and "RevisionHistory" columns
                  (Multiple lines of text) to the Document Lifecycle list once.
                </div>
              )}
            </div>
          )}

          {!loading && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <Field label="Domain" value={cover.domain} onChange={set("domain")} />
                <Field label="Document Type / Layer" value={cover.type_layer} onChange={set("type_layer")} />
                <Field label="Parent Document" value={cover.parent_document} onChange={set("parent_document")} />
                <Field label="Classification" value={cover.classification} onChange={set("classification")} />
                <Field label="Distribution" value={cover.distribution} onChange={set("distribution")} />
                <Field label="Version" value={cover.version} onChange={set("version")} />
                <Field label="Owner (role or group)" value={cover.owner} onChange={set("owner")} roleInput />
                <div />
                <Field label="First Pass Approval" value={cover.first_pass_approval} onChange={set("first_pass_approval")} roleInput />
                <Field label="Final Approval" value={cover.final_approval} onChange={set("final_approval")} roleInput />
                <Field label="Effective Date" value={cover.effective_date} onChange={set("effective_date")} />
                <Field label="Next Review Due" value={cover.next_review_due} onChange={set("next_review_due")} />
              </div>

              <StandardsEditor standards={standards} setStandards={setStandards} />
              <HistoryEditor history={history} setHistory={setHistory} />
            </div>
          )}
        </div>

        {!loading && (
          <div style={{ padding: "14px 22px", borderTop: "1px solid var(--color-border-tertiary)",
            display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <button onClick={preview} disabled={previewing} style={btn("transparent", "#3C3489", "1.5px solid #AFA9EC")}>
              {previewing ? "Generating preview…" : "Preview PDF"}
            </button>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={onClose} style={btn("transparent", "var(--color-text-secondary)", "1.5px solid var(--color-border-tertiary)")}>
                Close
              </button>
              <button onClick={save} disabled={saving} style={btn(saving ? "#C9CCD1" : "#085041")}>
                {saving ? "Saving…" : "Save cover facts"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
