// =============================================================================
// components/shared/StandardResults.jsx
// How the CDI checks are shown — the same on the Document Standards page and on
// a Lifecycle Review card: colours, the seven answers, one result, and (for a
// flagged check) Compliance's decision.
// =============================================================================

import { useState } from "react";

export const ENFORCEMENT = {
  BLOCK: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595", label: "Blocks approval" },
  FLAG: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775", label: "Needs a decision" },
  REPORT: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB", label: "Reported" },
};

export const STATUS = {
  pass: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5", label: "Passed" },
  fail: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595", label: "Blocking problem" },
  flag: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775", label: "Needs a decision" },
  report: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB", label: "For your attention" },
  could_not_check: { bg: "#F1EFE8", tx: "#444441", bd: "#B4B2A9", label: "Could not check" },
  not_applicable: { bg: "#F7F6F2", tx: "#6B6A63", bd: "#D8D6CC", label: "Not applicable" },
  not_built: { bg: "#F7F6F2", tx: "#6B6A63", bd: "#D8D6CC", label: "Not built yet" },
};

export const GROUPS = [
  { key: "fail", title: "Must be fixed before approval", open: true },
  { key: "flag", title: "Needs a decision", open: true },
  { key: "report", title: "For your attention", open: true },
  { key: "could_not_check", title: "Could not be checked", open: true },
  { key: "pass", title: "Passed", open: false },
  { key: "not_applicable", title: "Does not apply to this document", open: false },
  { key: "not_built", title: "Not built into OrgOS yet", open: false },
];

export const Pill = ({ tone, children, title }) => (
  <span
    title={title}
    style={{
      fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4, whiteSpace: "nowrap",
      background: tone.bg, color: tone.tx, border: `0.5px solid ${tone.bd}`,
    }}
  >
    {children}
  </span>
);

export const card = {
  border: "1px solid var(--color-border-tertiary, #E0E0E0)",
  borderRadius: 10, padding: "14px 16px", background: "var(--color-background-primary)",
};

export function groupResults(results = []) {
  const g = {};
  results.forEach((r) => (g[r.status] ||= []).push(r));
  return g;
}

// Compliance's decision on a flagged check: accepted with a reason, remembered
// against the exact findings (so a different problem reopens it).
function FlagDecision({ r, canDecide, onDecide, busy }) {
  const [reason, setReason] = useState("");
  if (r.decision) {
    return (
      <div style={{ marginTop: 8, padding: "7px 10px", background: "#E1F5EE", border: "0.5px solid #5DCAA5",
                    borderRadius: 7, fontSize: 11, color: "#085041", lineHeight: 1.5 }}>
        <strong>Accepted</strong> by {r.decision.by}: “{r.decision.reason}”
        {canDecide && (
          <button disabled={busy} onClick={() => onDecide(r.id, false, "")}
            style={{ marginLeft: 10, fontSize: 11, cursor: "pointer", background: "none", border: "none",
                     color: "#0C447C", textDecoration: "underline" }}>
            Withdraw
          </button>
        )}
      </div>
    );
  }
  return (
    <div style={{ marginTop: 8, fontSize: 11 }}>
      {r.decision_stale && (
        <div style={{ color: "#633806", marginBottom: 5 }}>
          An earlier decision no longer applies: what this check found has changed.
        </div>
      )}
      {canDecide ? (
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexWrap: "wrap" }}>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
            placeholder="Why is this acceptable? (at least 10 characters — this is the audit trail)"
            style={{ flex: 1, minWidth: 220, fontSize: 11, padding: "5px 8px", borderRadius: 6,
                     border: "1.5px solid #C0C0C0", fontFamily: "inherit" }} />
          <button disabled={busy || reason.trim().length < 10}
            onClick={() => onDecide(r.id, true, reason.trim())}
            style={{ padding: "6px 12px", fontSize: 11, fontWeight: 600, borderRadius: 6, border: "none",
                     cursor: busy || reason.trim().length < 10 ? "not-allowed" : "pointer",
                     background: busy || reason.trim().length < 10 ? "#E8E8E8" : "#1D9E75",
                     color: busy || reason.trim().length < 10 ? "#999" : "#fff" }}>
            Accept this flag
          </button>
        </div>
      ) : (
        <div style={{ color: "var(--color-text-secondary)" }}>Compliance decides flagged checks.</div>
      )}
    </div>
  );
}

// A role the document names that Org Roles does not have (V07): the roles that ARE there and
// might be meant, a free choice from all of them, and — when the role is really new — Create role.
// `onRole` is given only where the document can be changed (a Lifecycle Review card).
function RoleActions({ f, roles = [], canCreate, canAlias, onRole, busy }) {
  const d = f.data;
  const [choice, setChoice] = useState("");
  const from = d.role;
  const row = { display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginTop: 4 };
  const btn = (primary, off) => ({
    padding: "3px 9px", fontSize: 11, fontWeight: 600, borderRadius: 6, cursor: off ? "not-allowed" : "pointer",
    border: primary ? "none" : "1.5px solid #C0C0C0", background: off ? "#E8E8E8" : primary ? "#1D9E75" : "transparent",
    color: off ? "#999" : primary ? "#fff" : "var(--color-text-primary)",
  });
  const createRole = () => {
    try { sessionStorage.setItem("orgos.newRoleName", d.placeholder ? "" : from); } catch { /* the form just opens empty */ }
    window.dispatchEvent(new CustomEvent("orgos:navigate", { detail: { to: "org-roles" } }));
  };
  return (
    <div style={{ marginTop: 4, marginBottom: 6, padding: "6px 8px", background: "#F7F6F2", borderRadius: 6, fontSize: 11 }}>
      {d.suggestions?.length > 0 ? (
        <div>Do you mean:</div>
      ) : (
        <div style={{ color: "var(--color-text-secondary)" }}>No existing role is close to this.</div>
      )}
      {(d.suggestions || []).map((s) => (
        <div key={s.group_id} style={row}>
          <strong>{s.name}</strong>
          <span style={{ color: "var(--color-text-secondary)" }}>{s.reason}</span>
          {onRole && (
            <button disabled={busy} style={btn(true, busy)} onClick={() => onRole.use(from, s.name)}>Use this role</button>
          )}
          {onRole && canAlias && !d.placeholder && (
            <button disabled={busy} style={btn(false, busy)} title="Agree that this spelling means this role. The document is not changed."
              onClick={() => onRole.alias(s.group_id, from)}>Keep my wording as an alias</button>
          )}
        </div>
      ))}
      {onRole && roles.length > 0 && (
        <div style={row}>
          <select value={choice} onChange={(e) => setChoice(e.target.value)}
            style={{ fontSize: 11, padding: "3px 6px", borderRadius: 6, border: "1.5px solid #C0C0C0", maxWidth: 260 }}>
            <option value="">Choose another role…</option>
            {roles.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <button disabled={busy || !choice} style={btn(true, busy || !choice)} onClick={() => onRole.use(from, choice)}>Use this role</button>
        </div>
      )}
      <div style={row}>
        {canCreate ? (
          <button disabled={busy} style={btn(false, busy)} onClick={createRole}>Create role{d.placeholder ? "" : ` “${from}”`}</button>
        ) : (
          <span style={{ color: "var(--color-text-secondary)" }}>Only Compliance can create a role. Ask them to add “{from}”.</span>
        )}
      </div>
    </div>
  );
}

export function ResultCard({ r, canDecide = false, onDecide, busy = false, roles, onRole }) {
  return (
    <div style={{ ...card, padding: "10px 14px", marginBottom: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 12 }}>{r.id}</strong>
        <span style={{ fontSize: 12 }}>{r.name}</span>
        <Pill tone={ENFORCEMENT[r.enforcement]}>{r.enforcement}</Pill>
      </div>
      {r.summary && <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 5, lineHeight: 1.5 }}>{r.summary}</div>}
      {r.findings.length > 0 && (
        <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12, lineHeight: 1.55 }}>
          {r.findings.slice(0, 25).map((f, i) => (
            <li key={i}>
              {f.where && <code style={{ fontSize: 11, background: "#F1EFE8", padding: "0 4px", borderRadius: 3 }}>{f.where}</code>}{" "}
              {f.message}
              {f.fix && <div style={{ color: "#0C447C", fontSize: 11 }}>→ {f.fix}</div>}
              {f.data?.kind === "role" && (
                <RoleActions f={f} roles={roles} canCreate={canDecide} canAlias={canDecide} onRole={onRole} busy={busy} />
              )}
            </li>
          ))}
          {r.findings.length > 25 && <li style={{ color: "var(--color-text-tertiary)" }}>…and {r.findings.length - 25} more</li>}
        </ul>
      )}
      {r.note && <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>{r.note}</div>}
      {r.status === "flag" && onDecide && (
        <FlagDecision r={r} canDecide={canDecide} onDecide={onDecide} busy={busy} />
      )}
    </div>
  );
}
