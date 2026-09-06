// =============================================================================
// FeedbackAmendPanel.jsx — AI-assisted, owner-driven amendments from feedback
//
// During Sensitisation the AI turns stakeholder feedback into concrete edits to
// the document (reword existing text OR add new text). The OWNER stays in
// control: accept / edit / decline each one. Confirmed edits are applied to the
// .docx by a deterministic engine (no AI in the apply path), a new version is
// saved, and CDI is re-checked. Same safety model as the CDI fix panel.
// =============================================================================

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import apiClient from "../../api/grcApi.js";

const C = {
  reword: { fg: "#1D4ED8", bg: "#E8EEFD", bd: "#A9C1F5", label: "Reword" },
  add:    { fg: "#085041", bg: "#E7F5F0", bd: "#9FD9C8", label: "Add" },
  manual: { fg: "#6B7280", bg: "#F2F3F5", bd: "#D3D7DE", label: "Manual" },
};
const kindOf = (a) => {
  if (!a.can_apply) return "manual";
  return a.action === "replace" ? "reword" : "add";
};
const isAdd = (a) => a.action === "insert_after" || a.action === "insert_before";

function Highlight({ text, find }) {
  if (!text) return null;
  if (!find) return <span>{text}</span>;
  const i = text.toLowerCase().indexOf(find.toLowerCase());
  if (i === -1) return <span>{text}</span>;
  return (
    <span>
      {text.slice(0, i)}
      <mark style={{ background: "#FDE9B8", color: "#5A4300", padding: "0 2px", borderRadius: 3 }}>
        {text.slice(i, i + find.length)}
      </mark>
      {text.slice(i + find.length)}
    </span>
  );
}

function AmendCard({ a, decision, onChange }) {
  const kind = kindOf(a);
  const c = C[kind];
  const applicable = kind !== "manual";
  const accepted = decision?.action === "accept";
  const text = decision?.text ?? a.text ?? "";
  const occ = decision?.occurrence_index ?? null;
  const ambiguous = a.locate_status === "ambiguous" && a.occurrences > 1;
  const set = (patch) => onChange({ action: "accept", text, occurrence_index: occ, ...decision, ...patch });

  return (
    <div style={{
      border: `1px solid ${accepted ? c.bd : "var(--color-border-tertiary)"}`,
      borderLeft: `4px solid ${c.fg}`, borderRadius: 12, padding: "14px 16px",
      background: accepted ? c.bg : "var(--color-background-primary)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: c.fg, background: c.bg,
          border: `1px solid ${c.bd}`, borderRadius: 20, padding: "2px 9px",
          textTransform: "uppercase", letterSpacing: "0.4px" }}>{c.label}</span>
        {a.based_on && (
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            from feedback · {a.based_on}
          </span>
        )}
      </div>

      {a.reason && (
        <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginTop: 7 }}>{a.reason}</div>
      )}

      {applicable ? (
        <>
          {/* anchor / current text */}
          <div style={{ marginTop: 10, fontSize: 11, fontWeight: 700, color: "var(--color-text-tertiary)",
            textTransform: "uppercase", letterSpacing: "0.4px" }}>
            {isAdd(a) ? "Insert near" : "Current text"}
          </div>
          <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--color-text-primary)",
            background: "var(--color-background-secondary)", borderRadius: 8, padding: "8px 10px", marginTop: 4 }}>
            <Highlight text={a.find} find={isAdd(a) ? "" : a.find} />
          </div>

          {ambiguous && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: "#8A5A00", fontWeight: 600, marginBottom: 4 }}>
                This anchor appears {a.occurrences} times — choose which one:
              </div>
              {a.contexts.map((ctx, idx) => (
                <label key={idx} style={{ display: "flex", gap: 6, alignItems: "flex-start",
                  fontSize: 11.5, cursor: "pointer", color: "var(--color-text-secondary)", marginBottom: 3 }}>
                  <input type="radio" checked={occ === idx} onChange={() => set({ occurrence_index: idx })}
                    style={{ marginTop: 2 }} />
                  <span>{ctx.replace("⟦", "").replace("⟧", "")}</span>
                </label>
              ))}
            </div>
          )}

          <div style={{ marginTop: 10, fontSize: 11, fontWeight: 700, color: "var(--color-text-tertiary)",
            textTransform: "uppercase", letterSpacing: "0.4px" }}>
            {isAdd(a) ? "New text to add" : "Reword to"}
          </div>
          <textarea value={text} onChange={(e) => set({ text: e.target.value })} rows={isAdd(a) ? 3 : 2}
            style={{ marginTop: 4, width: "100%", padding: "8px 10px", fontSize: 12.5, borderRadius: 8,
              border: "1.5px solid var(--color-border-tertiary)", resize: "vertical", fontFamily: "inherit",
              background: "var(--color-background-primary)", color: "var(--color-text-primary)" }} />

          {/* before → after preview for reword */}
          {!isAdd(a) && text.trim() && a.find && (
            <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.5,
              background: "var(--color-background-secondary)", borderRadius: 8, padding: "8px 10px" }}>
              <span style={{ color: "#A32D2D", textDecoration: "line-through" }}>{a.find}</span>
              <span style={{ margin: "0 6px", color: "var(--color-text-tertiary)" }}>→</span>
              <span style={{ color: "#085041", fontWeight: 600 }}>{text}</span>
            </div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button onClick={() => set({ action: "accept" })} disabled={!text.trim()}
              style={{ flex: 1, padding: "8px", fontSize: 12, fontWeight: 600, borderRadius: 8,
                border: `1.5px solid ${accepted ? c.fg : c.bd}`,
                background: accepted ? c.fg : c.bg, color: accepted ? "#fff" : c.fg,
                cursor: text.trim() ? "pointer" : "not-allowed", opacity: text.trim() ? 1 : 0.5 }}>
              {accepted ? "✓ Accepted" : "Accept"}
            </button>
            <button onClick={() => onChange({ action: "decline" })}
              style={{ padding: "8px 14px", fontSize: 12, borderRadius: 8,
                border: `1.5px solid ${decision?.action === "decline" ? "#C0C0C0" : "var(--color-border-tertiary)"}`,
                background: decision?.action === "decline" ? "#EDEDED" : "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer" }}>
              Decline
            </button>
          </div>
        </>
      ) : (
        <div style={{ marginTop: 10, fontSize: 12, lineHeight: 1.5,
          background: C.manual.bg, border: `1px solid ${C.manual.bd}`, borderRadius: 8,
          padding: "9px 11px", color: "var(--color-text-secondary)" }}>
          <div style={{ fontWeight: 600, marginBottom: 2, color: C.manual.fg }}>Apply manually</div>
          {a.text || a.reason}
          {a.find && <div style={{ marginTop: 6, fontStyle: "italic" }}>Near: “{a.find}”</div>}
        </div>
      )}
    </div>
  );
}

function Results({ result, onDone }) {
  const applied = result.outcomes.filter((o) => o.status === "applied");
  const other   = result.outcomes.filter((o) => o.status !== "applied");
  return (
    <div style={{ padding: 4 }}>
      <div style={{ padding: "14px 16px", borderRadius: 12, marginBottom: 14,
        background: C.add.bg, border: `1px solid ${C.add.bd}` }}>
        <div style={{ fontSize: 15, fontWeight: 800, color: C.add.fg }}>
          {applied.length} amendment{applied.length === 1 ? "" : "s"} applied
        </div>
        <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginTop: 4 }}>
          A new version was saved. CDI re-check: <b>{result.cdi_status}</b>.
        </div>
      </div>
      {other.map((o, i) => (
        <div key={i} style={{ fontSize: 12, padding: "8px 10px", marginBottom: 6, borderRadius: 8,
          background: C.manual.bg, border: `1px solid ${C.manual.bd}`, color: "var(--color-text-secondary)" }}>
          {o.detail}
        </div>
      ))}
      <button onClick={onDone} style={{ marginTop: 12, width: "100%", padding: "10px", fontSize: 13,
        fontWeight: 600, borderRadius: 9, border: "none", background: "var(--color-text-primary)",
        color: "var(--color-background-primary)", cursor: "pointer" }}>Done</button>
    </div>
  );
}

export default function FeedbackAmendPanel({ docId, docCode, onClose }) {
  const qc = useQueryClient();
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [decisions, setDecisions] = useState({});
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const { data } = await apiClient.post(`/api/v1/lifecycle/documents/${docId}/amend/plan`);
        if (!live) return;
        setPlan(data);
        const init = {};
        (data.amendments || []).forEach((a) => {
          if (a.can_apply) init[a.amend_id] = {
            action: "accept", text: a.text ?? "",
            occurrence_index: a.locate_status === "ambiguous" ? null : 0,
          };
        });
        setDecisions(init);
      } catch (e) {
        if (live) setError(e?.response?.data?.detail || e.message || "Could not load amendments.");
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => { live = false; };
  }, [docId]);

  const amendments = plan?.amendments || [];
  const counts = useMemo(() => {
    const c = { reword: 0, add: 0, manual: 0 };
    amendments.forEach((a) => { c[kindOf(a)] += 1; });
    return c;
  }, [amendments]);

  const ready = useMemo(() => amendments
    .map((a) => ({ a, d: decisions[a.amend_id] }))
    .filter(({ a, d }) => {
      if (!d || d.action !== "accept" || !a.can_apply) return false;
      if (!(d.text ?? a.text ?? "").trim()) return false;
      if (a.locate_status === "ambiguous" && d.occurrence_index == null) return false;
      return true;
    })
    .map(({ a, d }) => ({
      amend_id: a.amend_id, action: a.action, find: a.find,
      text: d.text ?? a.text ?? "", occurrence_index: d.occurrence_index ?? null,
      summary: a.reason || "",
    })), [amendments, decisions]);

  const acceptAll = () => {
    const next = { ...decisions };
    amendments.forEach((a) => {
      if (a.can_apply) next[a.amend_id] = { action: "accept", text: a.text ?? "",
        occurrence_index: a.locate_status === "ambiguous" ? (next[a.amend_id]?.occurrence_index ?? null) : 0 };
    });
    setDecisions(next);
  };

  const apply = async () => {
    setApplying(true); setError("");
    try {
      const { data } = await apiClient.post(
        `/api/v1/lifecycle/documents/${docId}/amend/apply`, { amendments: ready });
      setResult(data);
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "Apply failed.");
    } finally {
      setApplying(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 1000, background: "rgba(17,20,24,0.55)",
      display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "5vh 16px", overflowY: "auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "100%", maxWidth: 680, background: "var(--color-background-primary)",
        borderRadius: 16, boxShadow: "0 24px 60px rgba(0,0,0,0.3)", overflow: "hidden",
        display: "flex", flexDirection: "column", maxHeight: "90vh",
      }}>
        <div style={{ padding: "18px 22px", borderBottom: "1px solid var(--color-border-tertiary)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 800, color: "var(--color-text-primary)" }}>
                Amend from feedback
              </div>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>
                {docCode || plan?.title || "Document"} — the AI drafted these from stakeholder feedback. You decide.
              </div>
            </div>
            <button onClick={onClose} style={{ fontSize: 20, lineHeight: 1, border: "none",
              background: "transparent", color: "var(--color-text-tertiary)", cursor: "pointer" }}>×</button>
          </div>
          {plan && !result && (
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", fontSize: 11 }}>
              {counts.reword > 0 && <Pill c={C.reword}>{counts.reword} reword</Pill>}
              {counts.add > 0 && <Pill c={C.add}>{counts.add} add</Pill>}
              {counts.manual > 0 && <Pill c={C.manual}>{counts.manual} manual</Pill>}
            </div>
          )}
          {plan?.editable === false && !result && (
            <div style={{ marginTop: 10, fontSize: 12, color: "#8A5A00", background: "#FDF3E2",
              border: "1px solid #F0CE94", borderRadius: 8, padding: "8px 10px" }}>
              {plan.editable_note || plan.message}
            </div>
          )}
        </div>

        <div style={{ padding: "16px 22px", overflowY: "auto", flex: 1 }}>
          {loading && <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
            Reading feedback and drafting amendments…</div>}
          {error && !result && (
            <div style={{ fontSize: 12.5, color: "#A32D2D", background: "#FCEBEB",
              border: "1px solid #F09595", borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>{error}</div>
          )}
          {result ? (
            <Results result={result} onDone={onClose} />
          ) : (
            !loading && (amendments.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
                {plan?.message || "The AI didn't find any concrete amendments from the feedback."}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {(counts.reword + counts.add) > 1 && (
                  <button onClick={acceptAll} style={{ alignSelf: "flex-start", fontSize: 11.5,
                    fontWeight: 600, color: C.add.fg, background: C.add.bg, border: `1px solid ${C.add.bd}`,
                    borderRadius: 8, padding: "6px 12px", cursor: "pointer" }}>
                    ✓ Accept all {counts.reword + counts.add} suggested edits
                  </button>
                )}
                {amendments.map((a) => (
                  <AmendCard key={a.amend_id} a={a} decision={decisions[a.amend_id]}
                    onChange={(d) => setDecisions((p) => ({ ...p, [a.amend_id]: d }))} />
                ))}
              </div>
            ))
          )}
        </div>

        {!result && plan?.editable !== false && amendments.length > 0 && (
          <div style={{ padding: "14px 22px", borderTop: "1px solid var(--color-border-tertiary)",
            display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              {ready.length} amendment{ready.length === 1 ? "" : "s"} ready
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={onClose} style={{ padding: "9px 16px", fontSize: 12.5, borderRadius: 9,
                border: "1.5px solid var(--color-border-tertiary)", background: "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer" }}>Cancel</button>
              <button onClick={apply} disabled={applying || ready.length === 0}
                style={{ padding: "9px 20px", fontSize: 12.5, fontWeight: 700, borderRadius: 9, border: "none",
                  background: ready.length === 0 ? "#C9CCD1" : "#085041", color: "#fff",
                  cursor: applying || ready.length === 0 ? "not-allowed" : "pointer" }}>
                {applying ? "Applying…" : `Apply ${ready.length} to document`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Pill({ c, children }) {
  return (
    <span style={{ fontWeight: 700, color: c.fg, background: c.bg, border: `1px solid ${c.bd}`,
      borderRadius: 20, padding: "3px 10px" }}>{children}</span>
  );
}
