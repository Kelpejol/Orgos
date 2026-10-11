// =============================================================================
// CdtCoverPanel.jsx — edit a document's CDT v06 cover facts + live PDF preview
//
// Every cover field is editable at any time (confirmed by the compliance
// officer — nothing on the cover is "set once and locked"). The Owner /
// First Pass Approval / Final Approval fields are ROLE or GROUP labels (e.g.
// "Compliance Team"), never a specific person — reuses JobTitleInput, which
// already suggests both real job titles and OrgOS groups.
//
// Blank fields are filled automatically from .../cover/suggest when the panel
// opens, each one labelled with where the value came from and how much to
// trust it. A value already on the document is never overwritten — a
// differing proposal is offered beside it instead. Nothing is saved until
// the person clicks "Save cover facts": CDI-014 reserves approving and
// changing a document's status to people, and a field the platform cannot
// resolve is left blank with the reason, rather than filled plausibly.
//
// Domain is a controlled list (CDI Annex B, served by /cdi/domains) rather
// than a text box, because V05 blocks approval unless the domain comes from
// Annex B — and picking one fills the approval route it implies.
//
// "Preview PDF" merges the document's CURRENT cover facts into its source
// .docx server-side and returns a PDF (Microsoft Graph's native conversion —
// no local converter). The source file itself is never modified.
//
// Depends on: GET/PATCH /api/v1/lifecycle/documents/{id}/cover,
//             GET /api/v1/lifecycle/documents/{id}/cover/suggest,
//             GET /api/v1/lifecycle/cdi/domains,
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

const FIELD_LABELS = {
  domain: "Domain", type_layer: "Document Type / Layer", parent_document: "Parent Document",
  classification: "Classification", distribution: "Distribution", owner: "Owner",
  first_pass_approval: "First Pass Approval", final_approval: "Final Approval",
  effective_date: "Effective Date", next_review_due: "Next Review Due",
};
const fieldLabel = (key) => FIELD_LABELS[key] || key;

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

// Confidence tells the reviewer how hard to look at a proposed value. The
// backend never proposes a value it can't justify, so "unresolved" means an
// empty field with a reason attached — not a bad guess.
const CONFIDENCE_TONE = {
  high:   { bg: "#E7F5F0", fg: "#085041", bd: "#9FD9C8" },
  medium: { bg: "#FDF4E3", fg: "#8A5A00", bd: "#EBCF8F" },
  low:    { bg: "#FBEEE6", fg: "#8A3D12", bd: "#EEC0A4" },
};

function Provenance({ suggestion, applied }) {
  if (!suggestion) return null;
  const { source, confidence, note } = suggestion;

  if (confidence === "unresolved") {
    return (
      <div style={{ fontSize: 10.5, color: "var(--color-text-tertiary)", marginTop: 3, lineHeight: 1.4 }}>
        {note || source}
      </div>
    );
  }
  if (!applied) return null;

  const tone = CONFIDENCE_TONE[confidence] || CONFIDENCE_TONE.low;
  return (
    <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <span style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.3px",
        padding: "2px 6px", borderRadius: 5, background: tone.bg, color: tone.fg, border: `1px solid ${tone.bd}` }}>
        {confidence} confidence
      </span>
      <span style={{ fontSize: 10.5, color: "var(--color-text-tertiary)" }}>{source}</span>
    </div>
  );
}

function Field({ label, value, onChange, roleInput, suggestion, applied, onAccept }) {
  // A proposal that differs from what's already there is offered, never
  // applied — the stored value was put there by a person.
  const differs =
    suggestion && suggestion.value && value && suggestion.value !== value && !applied;

  return (
    <div>
      <label style={labelStyle}>{label}</label>
      {roleInput ? (
        <JobTitleInput value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle} />
      ) : (
        <input value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle} />
      )}
      <Provenance suggestion={suggestion} applied={applied} />
      {differs && (
        <div style={{ fontSize: 10.5, color: "var(--color-text-tertiary)", marginTop: 3 }}>
          Suggests “{suggestion.value}”{" "}
          <button onClick={() => onAccept(suggestion.value)} style={{
            border: "none", background: "transparent", padding: 0, cursor: "pointer",
            color: "#3C3489", fontWeight: 700, fontSize: 10.5 }}>Use this</button>
        </div>
      )}
    </div>
  );
}

function DomainField({ value, onChange, options, suggestion, applied, onAccept }) {
  // Annex B's table is exhaustive and V05 blocks approval on anything not in
  // it — so this is a list, not a text box. An existing value that isn't in
  // the list is kept as an option so a legacy document still opens, visibly
  // flagged rather than silently dropped.
  const known = options.some((o) => o.domain === value);

  // If the domain list couldn't be fetched, fall back to a text box: an empty
  // dropdown would be a field nobody can fill.
  if (options.length === 0) {
    return (
      <Field label="Domain" value={value} onChange={onChange}
        suggestion={suggestion} applied={applied} onAccept={onAccept} />
    );
  }

  return (
    <div>
      <label style={labelStyle}>Domain</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle}>
        <option value="">— Select a domain —</option>
        {options.map((o) => <option key={o.domain} value={o.domain}>{o.domain}</option>)}
        {value && !known && <option value={value}>{value} (not in Annex B)</option>}
      </select>
      {value && !known && (
        <div style={{ fontSize: 10.5, color: "#8A3D12", marginTop: 3 }}>
          Not an Annex B domain — approval is blocked until this is one of the listed domains.
        </div>
      )}
      <Provenance suggestion={suggestion} applied={applied} />
      {suggestion?.value && value && suggestion.value !== value && !applied && (
        <div style={{ fontSize: 10.5, color: "var(--color-text-tertiary)", marginTop: 3 }}>
          Suggests “{suggestion.value}”{" "}
          <button onClick={() => onAccept(suggestion.value)} style={{
            border: "none", background: "transparent", padding: 0, cursor: "pointer",
            color: "#3C3489", fontWeight: 700, fontSize: 10.5 }}>Use this</button>
        </div>
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
  const [suggestions, setSuggestions] = useState({});
  const [applied, setApplied] = useState([]);   // fields filled from a suggestion, not yet edited
  const [domains, setDomains] = useState([]);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const data = await lifecycleApi.getCover(docId);
        if (!live) return;
        const loaded = { ...EMPTY_COVER, ...(data.cover || {}) };
        setCover(loaded);
        setStandards(data.cover?.standards || []);
        setHistory(data.revision_history || []);
        setLoading(false);

        // Fill the blanks from the platform's own records. Deliberately after
        // the cover has loaded and rendered: the panel must open even if this
        // fails, because a proposal is a convenience, not a prerequisite.
        if (lifecycleApi.cdiDomains) {
          lifecycleApi.cdiDomains()
            .then((rows) => { if (live) setDomains(rows || []); })
            .catch(() => { /* fall back to a free-text domain */ });
        }
        if (lifecycleApi.suggestCover) {
          try {
            const proposed = (await lifecycleApi.suggestCover(docId)).suggestions || {};
            if (!live) return;
            setSuggestions(proposed);
            const filled = [];
            const next = { ...loaded };
            for (const [key, s] of Object.entries(proposed)) {
              if (!s?.value) continue;
              if (String(next[key] ?? "").trim()) continue;  // never overwrite a stored value
              next[key] = s.value;
              filled.push(key);
            }
            setCover(next);
            setApplied(filled);
          } catch {
            /* No proposal is fine — every field is still editable by hand. */
          }
        }
      } catch (e) {
        if (live) {
          setError(e?.response?.data?.detail || e.message || "Could not load cover facts.");
          setLoading(false);
        }
      }
    })();
    return () => { live = false; };
  }, [docId]);

  // Editing a field makes it the person's value, so its "suggested" label goes.
  const set = (key) => (val) => {
    setCover((c) => ({ ...c, [key]: val }));
    setApplied((a) => a.filter((k) => k !== key));
  };

  const accept = (key) => (val) => {
    setCover((c) => ({ ...c, [key]: val }));
    setApplied((a) => (a.includes(key) ? a : [...a, key]));
  };

  // CDI Annex B fixes the approval route per domain (V05/V06), so choosing a
  // domain fills the route rather than asking for the same decision twice.
  // Roles a person has already typed are left alone.
  const setDomain = (val) => {
    const route = domains.find((d) => d.domain === val);
    setCover((c) => {
      const next = { ...c, domain: val };
      if (route) {
        next.first_pass_approval = route.first_pass_approval;
        next.final_approval = route.final_approval;
      }
      return next;
    });
    setApplied((a) => {
      const without = a.filter((k) => k !== "domain");
      return route ? [...new Set([...without, "first_pass_approval", "final_approval"])] : without;
    });
    if (route) {
      // Re-label the two roles so their provenance names the domain actually
      // chosen, not the one that was proposed.
      const from = { source: `CDI Annex B route for ${val}`, confidence: "high", note: "" };
      setSuggestions((s) => ({
        ...s,
        first_pass_approval: { ...from, value: route.first_pass_approval },
        final_approval:      { ...from, value: route.final_approval },
      }));
    }
  };

  const suggestedCount = applied.length;
  const unresolved = Object.entries(suggestions)
    .filter(([, s]) => s?.confidence === "unresolved")
    .map(([key]) => key);

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
              {suggestedCount > 0 && (
                <div style={{ fontSize: 11.5, color: "#085041", background: "#E7F5F0",
                  border: "1px solid #9FD9C8", borderRadius: 8, padding: "9px 12px", lineHeight: 1.5 }}>
                  <strong>{suggestedCount} field{suggestedCount === 1 ? "" : "s"} filled</strong> from this
                  document&rsquo;s code, its parent document and the library. Each is labelled with where it
                  came from — check them, then save. Nothing is stored until you do.
                  {unresolved.length > 0 && (
                    <div style={{ marginTop: 4, color: "var(--color-text-secondary)" }}>
                      Left blank because they couldn&rsquo;t be worked out: {unresolved.map(fieldLabel).join(", ")}.
                    </div>
                  )}
                </div>
              )}

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <DomainField value={cover.domain} onChange={setDomain} options={domains}
                  suggestion={suggestions.domain} applied={applied.includes("domain")}
                  onAccept={setDomain} />
                <Field label="Document Type / Layer" value={cover.type_layer} onChange={set("type_layer")}
                  suggestion={suggestions.type_layer} applied={applied.includes("type_layer")}
                  onAccept={accept("type_layer")} />
                <Field label="Parent Document" value={cover.parent_document} onChange={set("parent_document")}
                  suggestion={suggestions.parent_document} applied={applied.includes("parent_document")}
                  onAccept={accept("parent_document")} />
                <Field label="Classification" value={cover.classification} onChange={set("classification")}
                  suggestion={suggestions.classification} applied={applied.includes("classification")}
                  onAccept={accept("classification")} />
                <Field label="Distribution" value={cover.distribution} onChange={set("distribution")}
                  suggestion={suggestions.distribution} applied={applied.includes("distribution")}
                  onAccept={accept("distribution")} />
                <Field label="Version" value={cover.version} onChange={set("version")} />
                <Field label="Owner (role or group)" value={cover.owner} onChange={set("owner")} roleInput
                  suggestion={suggestions.owner} applied={applied.includes("owner")}
                  onAccept={accept("owner")} />
                <div />
                <Field label="First Pass Approval" value={cover.first_pass_approval} onChange={set("first_pass_approval")} roleInput
                  suggestion={suggestions.first_pass_approval} applied={applied.includes("first_pass_approval")}
                  onAccept={accept("first_pass_approval")} />
                <Field label="Final Approval" value={cover.final_approval} onChange={set("final_approval")} roleInput
                  suggestion={suggestions.final_approval} applied={applied.includes("final_approval")}
                  onAccept={accept("final_approval")} />
                <Field label="Effective Date" value={cover.effective_date} onChange={set("effective_date")}
                  suggestion={suggestions.effective_date} applied={applied.includes("effective_date")}
                  onAccept={accept("effective_date")} />
                <Field label="Next Review Due" value={cover.next_review_due} onChange={set("next_review_due")}
                  suggestion={suggestions.next_review_due} applied={applied.includes("next_review_due")}
                  onAccept={accept("next_review_due")} />
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
