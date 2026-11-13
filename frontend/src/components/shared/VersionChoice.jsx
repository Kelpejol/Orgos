// =============================================================================
// components/shared/VersionChoice.jsx
// How approval treats the document's version (CDI Procedure §14):
//   first issue          becomes version 01 — says what the document is and why
//   new version          a real change — needs a change summary
//   correction           a typo / cross-reference / formatting: the version stays, it is logged
//   annual review        no change: the version stays, the review date moves on
// Compliance sets it on the card (VersionPlanPanel) or when sending the document for
// approval; the approver only reads it. The Register holds the version; approval stamps
// the cover from it. Nobody types a version into a file.
// =============================================================================

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "../../api/grcApi.js";

const CHOICES = (cur, next) => ({
  new: { title: `New version (${cur} → ${next})`,
         hint: "A real change to the document. Needs a change summary: what changed and why.",
         label: "What changed and why", required: true },
  correction: { title: "Correction — no new version",
                hint: `A typo, a broken cross-reference or formatting. The version stays ${cur}; the correction is logged.`,
                label: "What was corrected", required: true },
  review: { title: "Annual review — no change",
            hint: `Reviewed and still right. The version stays ${cur}; only the next review date moves on.`,
            label: "Note (optional)", required: false },
});

const WEAK = new Set(["issued for use", "issued", "approved for use", "approved", "initial issue", "first issue",
  "new document", "n/a", "na", "none", "update", "updated", "no change", "changes", "minor changes", "various"]);

// Mirrors lifecycle/versioning.py so the button waits for something the server will accept.
// The server is the authority; this only saves a round trip.
export function versionProblem(decision, summary, options) {
  if (!options) return "Loading…";
  if (!decision) return "Choose how approval treats the version.";
  if (decision === "review") return "";
  const text = (summary || "").trim();
  const min = decision === "new" ? options.min_new_summary : options.min_correction_summary;
  if (WEAK.has(text.toLowerCase().replace(/[^a-z ]+/g, "").trim())) return "That does not say what changed.";
  if (text.length < min) return `Say ${decision === "new" ? "what changed and why" : "what was corrected"} (at least ${min} characters).`;
  return "";
}

export default function VersionChoice({ docId, value, onChange, onReady }) {
  const { data: options, error } = useQuery({
    queryKey: ["version-options", docId],
    queryFn: () => apiClient.get(`/api/v1/lifecycle/documents/${docId}/version-options`).then((r) => r.data),
    staleTime: 0,
  });

  // Preselect once we know what applies (a scheduled review defaults to "annual review").
  useEffect(() => {
    if (options && !value.decision) onChange({ ...value, decision: options.default_decision });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options]);

  const problem = versionProblem(value.decision, value.summary, options);
  useEffect(() => { onReady?.(!problem); }, [problem]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <div style={{ fontSize: 12, color: "#791F1F", marginBottom: 12 }}>Could not load the version options: {error.message}</div>;
  if (!options) return <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginBottom: 12 }}>Loading version options…</div>;

  const choices = CHOICES(options.current_version, options.next_version);
  const current = value.decision ? choices[value.decision] : null;

  return (
    <div style={{ marginBottom: 14, padding: "12px 14px", background: "var(--color-background-secondary)",
                  border: "1px solid var(--color-border-tertiary, #E0E0E0)", borderRadius: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Version</div>

      {!options.has_issued_version ? (
        <div style={{ fontSize: 12, lineHeight: 1.5, marginBottom: 8 }}>
          This is the first issue, so it becomes <strong>version {options.next_version}</strong>. A draft has no version
          until it is issued.
        </div>
      ) : (
        <div style={{ display: "grid", gap: 6, marginBottom: 10 }}>
          {options.decisions.map((d) => (
            <label key={d} style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer",
                                    padding: "7px 9px", borderRadius: 7, fontSize: 12, lineHeight: 1.45,
                                    border: `1.5px solid ${value.decision === d ? "#0C447C" : "#D0D0D0"}`,
                                    background: value.decision === d ? "#E6F1FB" : "transparent" }}>
              <input type="radio" name={`version-${docId}`} checked={value.decision === d}
                onChange={() => onChange({ ...value, decision: d })} style={{ marginTop: 2 }} />
              <span><strong>{choices[d].title}</strong><br /><span style={{ color: "var(--color-text-secondary)" }}>{choices[d].hint}</span></span>
            </label>
          ))}
        </div>
      )}

      {(current || !options.has_issued_version) && (
        <>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: 4 }}>
            {options.has_issued_version ? current.label : "Change summary: what this document is and why it is being issued"}
            {(!options.has_issued_version || current.required) && " (required)"}
          </label>
          <textarea value={value.summary} rows={3} onChange={(e) => onChange({ ...value, summary: e.target.value })}
            placeholder={value.decision === "review" ? "Optional note for the record…"
              : "Say what changed and why. “Issued for use” is not enough — this is the document's history."}
            style={{ width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 8, border: "1.5px solid #C0C0C0",
                     background: "var(--color-background-primary)", color: "var(--color-text-primary)",
                     resize: "vertical", fontFamily: "var(--font-sans)", outline: "none", boxSizing: "border-box" }} />
          {problem && value.summary.trim() && (
            <div style={{ fontSize: 11, color: "#791F1F", marginTop: 4 }}>{problem}</div>
          )}
        </>
      )}
    </div>
  );
}

// What a decision saved on the card reads as, without asking the server.
export const DECISION_LABEL = {
  new: "New version",
  correction: "Correction — no new version",
  review: "Annual review — no change",
};

// The card's "Version on approval": what Compliance has set, and a way to set or change it.
// The approver is never asked; approval uses what is saved here.
export function VersionPlanPanel({ doc, canEdit }) {
  const qc = useQueryClient();
  const saved = { decision: doc.VersionDecision || "", summary: doc.ChangeSummary || "" };
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(saved);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true); setError("");
    try {
      await apiClient.put(`/api/v1/lifecycle/documents/${doc.id}/version-plan`, {
        version_decision: value.decision || undefined, change_summary: value.summary.trim(),
      });
      await qc.invalidateQueries({ queryKey: ["lifecycle"] });
      setEditing(false);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Could not save the version.");
    } finally {
      setBusy(false);
    }
  };

  const box = { marginTop: 8, padding: "8px 12px", borderRadius: 8, fontSize: 11.5, lineHeight: 1.45 };
  if (editing) {
    return (
      <div style={{ ...box, padding: 0 }}>
        <VersionChoice docId={doc.id} value={value} onChange={setValue} onReady={setReady} />
        {error && <div style={{ fontSize: 11, color: "#791F1F", marginBottom: 6 }}>{error}</div>}
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => { setEditing(false); setValue(saved); setError(""); }} disabled={busy}
            style={{ flex: 1, padding: "6px", fontSize: 11, borderRadius: 7, cursor: "pointer",
                     border: "1.5px solid #C0C0C0", background: "transparent", color: "var(--color-text-secondary)" }}>
            Cancel
          </button>
          <button onClick={save} disabled={busy || !ready}
            style={{ flex: 2, padding: "6px", fontSize: 11, borderRadius: 7, fontWeight: 600, border: "none",
                     background: busy || !ready ? "#E8E8E8" : "#0C447C", color: busy || !ready ? "#999" : "#fff",
                     cursor: busy || !ready ? "not-allowed" : "pointer" }}>
            {busy ? "Saving…" : "Save version"}
          </button>
        </div>
      </div>
    );
  }

  const isSet = !!saved.decision;
  return (
    <div style={{ ...box, background: isSet ? "var(--color-background-secondary)" : "#FAEEDA",
                  border: `0.5px solid ${isSet ? "var(--color-border-tertiary, #E0E0E0)" : "#FAC775"}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-secondary)" }}>Version on approval</span>
        {canEdit && (
          <button onClick={() => { setValue(saved); setEditing(true); }}
            style={{ background: "none", border: "none", padding: 0, fontSize: 11, color: "#0C447C",
                     cursor: "pointer", fontWeight: 600 }}>
            {isSet ? "Change" : "Set"}
          </button>
        )}
      </div>
      {isSet ? (
        <>
          <div style={{ fontWeight: 600, marginTop: 2 }}>{DECISION_LABEL[saved.decision] || saved.decision}</div>
          {saved.summary && <div style={{ color: "var(--color-text-secondary)", marginTop: 2 }}>{saved.summary}</div>}
        </>
      ) : (
        <div style={{ color: "#633806", marginTop: 2 }}>
          Not set yet. Set it before sending the document for approval; the approver is not asked.
        </div>
      )}
    </div>
  );
}
