// =============================================================================
// components/shared/VersionChoice.jsx
// How this approval treats the document's version (CDI Procedure §14):
//   first issue          becomes version 01 — says what the document is and why
//   new version          a real change — needs a change summary
//   correction           a typo / cross-reference / formatting: the version stays, it is logged
//   annual review        no change: the version stays, the review date moves on
// The Register holds the version; approval stamps the cover from it. Nobody
// types a version into a file.
// =============================================================================

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
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
  if (!decision) return "Choose how this approval treats the version.";
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
            {options.has_issued_version ? current.label : "What is this document, and why is it being issued?"}
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
