// =============================================================================
// components/shared/StandardCheckPanel.jsx
// "Document standard" on a Lifecycle Review card: the CDI checks (V01–V24) on
// this document's file, where each problem is, and — for Compliance — decisions
// on flagged checks. Runs when asked (opening twenty cards must not run twenty
// checks). In advisory mode it says what WOULD stop the document; in enforce
// mode it says what DOES.
// =============================================================================

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import apiClient from "../../api/grcApi.js";
import { GROUPS, Pill, ResultCard, STATUS, groupResults } from "./StandardResults.jsx";

const MODE_NOTE = {
  advisory: "Advisory: these results do not stop the document yet. They show what would, once the standard is enforced.",
  enforce: "Enforced: a blocking problem, or a flag Compliance has not decided, stops this document moving on.",
  off: "The standard is not being shown at the gate.",
};

export default function StandardCheckPanel({ docId, isCompliance }) {
  const qc = useQueryClient();
  const key = ["standard-check", docId];
  const [data, setData] = useState(() => qc.getQueryData(key) || null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const run = async () => {
    setBusy("checking"); setError("");
    try {
      const r = await apiClient.get(`/api/v1/lifecycle/documents/${docId}/standard-check`);
      qc.setQueryData(key, r.data); setData(r.data);
    } catch (e) { setError(e.message); }
    finally { setBusy(""); }
  };

  const decide = async (checkId, accept, reason) => {
    setBusy("deciding"); setError("");
    try {
      const r = await apiClient.post(`/api/v1/lifecycle/documents/${docId}/standard-decision`,
        { check_id: checkId, accept, reason });
      qc.setQueryData(key, r.data); setData(r.data);
    } catch (e) { setError(e.message); }
    finally { setBusy(""); }
  };

  // The roles that exist, for the "choose another role" list.
  const { data: roleNames = [] } = useQuery({
    queryKey: ["role-names-for-check"],
    queryFn: () => apiClient.get("/api/v1/groups").then((r) => (r.data || []).map((g) => g.name).filter(Boolean).sort()),
    staleTime: 60_000,
  });

  // After any role change the checks are run again: the finding either goes or says why not.
  const roleAction = {
    use: async (fromRole, toRole) => {
      setBusy("fixing"); setError("");
      try {
        await apiClient.post(`/api/v1/lifecycle/documents/${docId}/role-fix`, { from_role: fromRole, to_role: toRole });
        qc.invalidateQueries({ queryKey: ["lifecycle"] });
        await run();
      } catch (e) { setError(e.response?.data?.detail || e.message); setBusy(""); }
    },
    alias: async (groupId, alias) => {
      setBusy("fixing"); setError("");
      try {
        await apiClient.post("/api/v1/doc-standards/role-alias", { group_id: groupId, alias });
        qc.invalidateQueries({ queryKey: ["groups"] });
        await run();
      } catch (e) { setError(e.response?.data?.detail || e.message); setBusy(""); }
    },
  };

  const grouped = useMemo(() => groupResults(data?.report?.results), [data]);
  const gate = data?.gate;
  const stops = gate && !gate.ready;
  const tone = !gate ? STATUS.not_applicable : stops ? (gate.enforced ? STATUS.fail : STATUS.flag) : STATUS.pass;

  return (
    <div style={{ marginTop: 8, border: "1px solid var(--color-border-tertiary, #E0E0E0)", borderRadius: 8,
                  padding: "8px 10px", background: "var(--color-background-primary)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 11 }}>Document standard</strong>
        {data?.mode && <Pill tone={STATUS.not_applicable}>{data.mode}</Pill>}
        {gate && (
          <Pill tone={tone}>
            {gate.ready ? "No blocking problems"
              : `${gate.blocking.length} blocking${gate.undecided_flags.length ? ` · ${gate.undecided_flags.length} to decide` : ""}`}
          </Pill>
        )}
        <button onClick={run} disabled={!!busy}
          style={{ marginLeft: "auto", padding: "4px 10px", fontSize: 11, borderRadius: 6, cursor: busy ? "not-allowed" : "pointer",
                   border: "1.5px solid #C0C0C0", background: "transparent", color: "var(--color-text-primary)" }}>
          {busy === "checking" ? "Checking..." : data ? "Check again" : "Check against the standard"}
        </button>
      </div>

      {error && <div style={{ marginTop: 6, fontSize: 11, color: "#791F1F" }}>{error}</div>}

      {data && !data.available && (
        <div style={{ marginTop: 6, fontSize: 11, color: "var(--color-text-secondary)" }}>{data.reason}</div>
      )}

      {data?.available && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
            {MODE_NOTE[data.mode]} {gate.checks_run} of {gate.checks_total} checks ran
            {gate.could_not_check.length > 0 && `; ${gate.could_not_check.length} could not run`}
            {gate.not_built.length > 0 && `; ${gate.not_built.length} are not built yet`}.
          </div>
          {data.context_notes?.length > 0 && (
            <div style={{ marginTop: 6, padding: "6px 8px", background: "#FAEEDA", border: "0.5px solid #FAC775",
                          borderRadius: 6, fontSize: 11, color: "#633806" }}>
              {data.context_notes.map((n, i) => <div key={i}>{n}</div>)}
            </div>
          )}
          <div style={{ marginTop: 8 }}>
            {GROUPS.filter((g) => grouped[g.key]?.length).map((g) => (
              <details key={g.key} open={g.open} style={{ marginBottom: 6 }}>
                <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 600, margin: "4px 0" }}>
                  <Pill tone={STATUS[g.key]}>{grouped[g.key].length}</Pill> {g.title}
                </summary>
                {grouped[g.key].map((r) => (
                  <ResultCard key={r.id} r={r} canDecide={isCompliance} onDecide={decide} busy={!!busy}
                    roles={roleNames} onRole={roleAction} />
                ))}
              </details>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
