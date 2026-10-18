// =============================================================================
// CdiFixPanel.jsx — Guided CDI auto-fix
//
// Shows every CDI failure with its exact suggested fix, lets the reviewer
// confirm / edit / choose / skip each one, then applies the confirmed fixes to
// the document. The AI never edits the file: the backend does a deterministic,
// located, verified find-and-replace and saves a new version. This panel is the
// human-in-the-loop surface for that.
// =============================================================================

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import apiClient from "../../api/grcApi.js";

// ── palette ─────────────────────────────────────────────────────────────────
const C = {
  auto:    { fg: "#085041", bg: "#E7F5F0", bd: "#9FD9C8", label: "Auto-fix" },
  choice:  { fg: "#8A5A00", bg: "#FDF3E2", bd: "#F0CE94", label: "Needs a choice" },
  insert:  { fg: "#3C3489", bg: "#EEEDFE", bd: "#AFA9EC", label: "Add missing section" },
  structural: { fg: "#3C3489", bg: "#EEEDFE", bd: "#AFA9EC", label: "Control block" },
  manual:  { fg: "#6B7280", bg: "#F2F3F5", bd: "#D3D7DE", label: "Manual" },
  none:    { fg: "#6B7280", bg: "#F2F3F5", bd: "#D3D7DE", label: "—" },
};
const kindOf = (f) => {
  if (!f.can_apply && (f.fixable === "auto" || f.fixable === "choice")) {
    return f.locate_status === "not_found" ? "manual" : f.fixable;
  }
  return f.fixable || "manual";
};

// Insert fixes ship a template with [bracketed] gaps. They must be filled in
// before the fix can be confirmed — placeholders never go into a controlled doc.
const hasPlaceholder = (t) => /\[[^\]]+\]/.test(t || "");
const insertText = (f, d) => d?.insert_text ?? f.insert?.text ?? "";

// Escape + highlight the `find` fragment inside a sentence for display.
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

// Local before→after preview (display only — the server does the real edit).
function previewAfter(anchor, find, replace) {
  if (!anchor || !find) return replace || anchor;
  const i = anchor.toLowerCase().indexOf(find.toLowerCase());
  if (i === -1) return anchor;
  return anchor.slice(0, i) + (replace ?? "") + anchor.slice(i + find.length);
}

const badge = (kind) => {
  const c = C[kind] || C.manual;
  return (
    <span style={{ fontSize: 10, fontWeight: 700, color: c.fg, background: c.bg,
      border: `1px solid ${c.bd}`, borderRadius: 20, padding: "2px 9px",
      textTransform: "uppercase", letterSpacing: "0.4px" }}>{c.label}</span>
  );
};

// ── the rule behind a check — collapsed by default, one click to read ───────
function RuleHint({ rule }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 6 }}>
      <button onClick={() => setOpen((v) => !v)} title={rule}
        style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: 0,
          border: "none", background: "transparent", cursor: "pointer",
          fontSize: 11, fontWeight: 600, color: "var(--color-text-tertiary)" }}>
        <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 13, height: 13, borderRadius: "50%", fontSize: 9, fontWeight: 800,
          border: "1.2px solid currentColor" }}>i</span>
        What this check requires
      </button>
      {open && (
        <div style={{ marginTop: 5, fontSize: 11.5, lineHeight: 1.5, padding: "7px 10px",
          borderRadius: 8, background: "var(--color-background-secondary)",
          color: "var(--color-text-secondary)" }}>{rule}</div>
      )}
    </div>
  );
}

// ── one finding card ──────────────────────────────────────────────────────────
function FixCard({ f, decision, onChange }) {
  const kind = kindOf(f);
  const c = C[kind] || C.manual;
  const isInsert = kind === "insert";
  const applicable = kind === "auto" || kind === "choice";
  const confirmed = decision?.action === "confirm";
  const itext = isInsert ? insertText(f, decision) : "";
  const insertUnfilled = isInsert && (!itext.trim() || hasPlaceholder(itext));
  const replace = decision?.replace ?? f.replace ?? "";
  const occ = decision?.occurrence_index ?? null;
  const ambiguous = f.locate_status === "ambiguous" && f.occurrences > 1;
  const choiceUnset = kind === "choice" && !replace.trim();

  const set = (patch) => onChange({ action: "confirm", replace, occurrence_index: occ, ...decision, ...patch });

  return (
    <div style={{
      border: `1px solid ${confirmed ? c.bd : "var(--color-border-tertiary)"}`,
      borderLeft: `4px solid ${c.fg}`, borderRadius: 12, padding: "14px 16px",
      background: confirmed ? c.bg : "var(--color-background-primary)",
      transition: "background .15s, border-color .15s",
    }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: "var(--color-text-primary)" }}>{f.check_id}</span>
        {f.severity === "warning" && (
          <span style={{ fontSize: 10, fontWeight: 700, color: "#8A5A00", background: "#FDF3E2",
            border: "1px solid #F0CE94", borderRadius: 20, padding: "2px 9px", textTransform: "uppercase" }}>
            Warning · optional
          </span>
        )}
        <span style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>{f.check_name}</span>
        {badge(kind)}
        {typeof f.confidence === "number" && f.confidence > 0 && (
          <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>{f.confidence}% conf.</span>
        )}
      </div>

      {/* The rule, in the reviewer's own words — so the accepted form is never
          a guess (a cover reading "Draft" failed the version check with nothing
          on screen to say a first issue is v1.0). */}
      {f.rule && <RuleHint rule={f.rule} />}

      {/* finding */}
      <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 6 }}>{f.finding}</div>

      {isInsert ? (
        <>
          <div style={{ marginTop: 10, fontSize: 11, fontWeight: 700, color: "var(--color-text-tertiary)",
            textTransform: "uppercase", letterSpacing: "0.4px" }}>
            {f.insert.heading ? `Will add a “${f.insert.heading}” ${f.insert.kind === "table" ? "table" : "section"}`
                              : "Will add this line"}
            {f.insert.position === "top" ? " at the top" : f.insert.position === "before_first_heading" ? " before the first section" : " at the end"}
          </div>
          <textarea value={itext} rows={f.insert.kind === "table" ? 3 : 2}
            onChange={(e) => onChange({ action: "confirm", insert_text: e.target.value })}
            style={{ marginTop: 4, width: "100%", padding: "8px 10px", fontSize: 12.5, borderRadius: 8,
              fontFamily: "inherit", resize: "vertical",
              border: `1.5px solid ${insertUnfilled ? C.choice.bd : "var(--color-border-tertiary)"}`,
              background: "var(--color-background-primary)", color: "var(--color-text-primary)" }} />
          <div style={{ fontSize: 11, marginTop: 4, color: insertUnfilled ? C.choice.fg : "var(--color-text-tertiary)" }}>
            {f.insert.kind === "table" ? "One row per line, columns separated by “|”. " : ""}
            {insertUnfilled ? "Replace the [bracketed] parts with real content to enable this fix."
                            : "Edit if needed, then confirm."}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button onClick={() => onChange({ action: "confirm", insert_text: itext })} disabled={insertUnfilled}
              style={{ flex: 1, padding: "8px", fontSize: 12, fontWeight: 600, borderRadius: 8,
                border: `1.5px solid ${confirmed ? c.fg : c.bd}`,
                background: confirmed ? c.fg : c.bg, color: confirmed ? "#fff" : c.fg,
                cursor: insertUnfilled ? "not-allowed" : "pointer", opacity: insertUnfilled ? 0.5 : 1 }}>
              {confirmed && !insertUnfilled ? "✓ Will add" : "Confirm & add"}
            </button>
            <button onClick={() => onChange({ action: "skip" })}
              style={{ padding: "8px 14px", fontSize: 12, borderRadius: 8,
                border: `1.5px solid ${decision?.action === "skip" ? "#C0C0C0" : "var(--color-border-tertiary)"}`,
                background: decision?.action === "skip" ? "#EDEDED" : "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer" }}>Skip</button>
          </div>
        </>
      ) : applicable ? (
        <>
          <div style={{ marginTop: 10, fontSize: 11, fontWeight: 700, color: "var(--color-text-tertiary)",
            textTransform: "uppercase", letterSpacing: "0.4px" }}>In the document</div>
          <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--color-text-primary)",
            background: "var(--color-background-secondary)", borderRadius: 8, padding: "8px 10px", marginTop: 4 }}>
            <Highlight text={f.anchor} find={f.find} />
          </div>

          {/* occurrence picker when ambiguous */}
          {ambiguous && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: C.choice.fg, fontWeight: 600, marginBottom: 4 }}>
                This text appears {f.occurrences} times — choose which one:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {f.contexts.map((ctx, idx) => (
                  <label key={idx} style={{ display: "flex", gap: 6, alignItems: "flex-start",
                    fontSize: 11.5, cursor: "pointer", color: "var(--color-text-secondary)" }}>
                    <input type="radio" checked={occ === idx}
                      onChange={() => set({ occurrence_index: idx })} style={{ marginTop: 2 }} />
                    <span>{ctx.replace("⟦", "").replace("⟧", "")}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* choice dropdown */}
          {kind === "choice" && f.choices?.length > 0 && (
            <select value={replace} onChange={(e) => set({ replace: e.target.value })}
              style={{ marginTop: 10, width: "100%", padding: "8px 10px", fontSize: 12.5,
                borderRadius: 8, border: `1.5px solid ${choiceUnset ? C.choice.bd : "var(--color-border-tertiary)"}`,
                background: "var(--color-background-primary)", color: "var(--color-text-primary)" }}>
              <option value="">— choose the replacement —</option>
              {f.choices.map((ch) => <option key={ch} value={ch}>{ch}</option>)}
            </select>
          )}

          {/* editable replacement */}
          <div style={{ marginTop: 10, fontSize: 11, fontWeight: 700, color: "var(--color-text-tertiary)",
            textTransform: "uppercase", letterSpacing: "0.4px" }}>Replace with</div>
          <input value={replace} onChange={(e) => set({ replace: e.target.value })}
            placeholder={kind === "choice" ? "Pick above or type the exact replacement" : "Exact replacement text"}
            style={{ marginTop: 4, width: "100%", padding: "8px 10px", fontSize: 12.5, borderRadius: 8,
              border: `1.5px solid ${choiceUnset ? C.choice.bd : "var(--color-border-tertiary)"}`,
              background: "var(--color-background-primary)", color: "var(--color-text-primary)" }} />

          {/* before → after preview */}
          {replace.trim() && f.find && (
            <div style={{ marginTop: 10, fontSize: 12, lineHeight: 1.5,
              background: "var(--color-background-secondary)", borderRadius: 8, padding: "8px 10px" }}>
              <span style={{ color: "#A32D2D", textDecoration: "line-through" }}>{f.find}</span>
              <span style={{ margin: "0 6px", color: "var(--color-text-tertiary)" }}>→</span>
              <span style={{ color: "#085041", fontWeight: 600 }}>{replace}</span>
              <div style={{ marginTop: 6, color: "var(--color-text-secondary)", fontStyle: "italic" }}>
                “{previewAfter(f.anchor, f.find, replace)}”
              </div>
            </div>
          )}

          {/* confirm / skip */}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button onClick={() => set({ action: "confirm" })} disabled={choiceUnset}
              style={{ flex: 1, padding: "8px", fontSize: 12, fontWeight: 600, borderRadius: 8,
                border: `1.5px solid ${confirmed ? c.fg : c.bd}`,
                background: confirmed ? c.fg : c.bg, color: confirmed ? "#fff" : c.fg,
                cursor: choiceUnset ? "not-allowed" : "pointer", opacity: choiceUnset ? 0.5 : 1 }}>
              {confirmed ? "✓ Will apply" : "Confirm fix"}
            </button>
            <button onClick={() => onChange({ action: "skip" })}
              style={{ padding: "8px 14px", fontSize: 12, borderRadius: 8,
                border: `1.5px solid ${decision?.action === "skip" ? "#C0C0C0" : "var(--color-border-tertiary)"}`,
                background: decision?.action === "skip" ? "#EDEDED" : "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer" }}>
              Skip
            </button>
          </div>
          {choiceUnset && (
            <div style={{ fontSize: 11, color: C.choice.fg, marginTop: 6 }}>
              Choose or type a replacement to enable this fix.
            </div>
          )}
        </>
      ) : (
        // structural / manual: guidance only
        <div style={{ marginTop: 10, fontSize: 12, lineHeight: 1.5,
          background: c.bg, border: `1px solid ${c.bd}`, borderRadius: 8, padding: "9px 11px", color: c.fg }}>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>
            {kind === "structural" ? "Fix in the control block / metadata:" : "Apply manually:"}
          </div>
          {f.proposed_fix || f.finding}
          {kind === "manual" && f.anchor && (
            <div style={{ marginTop: 6, color: "var(--color-text-secondary)", fontStyle: "italic" }}>
              Text to change: “{f.anchor}”
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── document preview — the fixed document, changes highlighted ───────────────
// Reading the result in place beats trusting a count: the reviewer sees what
// the document now says, and can step through each change in document order.
function ChangePreview({ blocks }) {
  const [at, setAt] = useState(0);
  const scrollRef = useRef(null);
  const marks = useRef([]);

  const changedIdx = useMemo(
    () => blocks.map((b, i) => (b.changed ? i : -1)).filter((i) => i >= 0),
    [blocks],
  );

  const jump = (delta) => {
    if (!changedIdx.length) return;
    const next = (at + delta + changedIdx.length) % changedIdx.length;
    setAt(next);
    const el = marks.current[changedIdx[next]];
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  };

  // Land on the first change rather than the top of the document.
  useEffect(() => {
    if (!changedIdx.length) return;
    const el = marks.current[changedIdx[0]];
    if (el && scrollRef.current) {
      scrollRef.current.scrollTop = Math.max(0, el.offsetTop - scrollRef.current.offsetTop - 60);
    }
  }, [changedIdx]);

  if (!blocks.length) return null;

  const navBtn = (disabled) => ({
    padding: "3px 9px", fontSize: 13, lineHeight: 1.2, borderRadius: 7,
    border: "1.5px solid var(--color-border-tertiary)", background: "var(--color-background-primary)",
    color: disabled ? "var(--color-text-tertiary)" : "var(--color-text-primary)",
    cursor: disabled ? "not-allowed" : "pointer",
  });

  return (
    <div style={{ marginBottom: 14, border: "1px solid var(--color-border-tertiary)",
      borderRadius: 12, overflow: "hidden" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "8px 12px", borderBottom: "1px solid var(--color-border-tertiary)",
        background: "var(--color-background-secondary)" }}>
        <div style={{ fontSize: 11.5, fontWeight: 700, color: "var(--color-text-secondary)" }}>
          The document now reads
        </div>
        {changedIdx.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
              change {at + 1} of {changedIdx.length}
            </span>
            <button onClick={() => jump(-1)} title="Previous change"
              disabled={changedIdx.length < 2} style={navBtn(changedIdx.length < 2)}>↑</button>
            <button onClick={() => jump(1)} title="Next change"
              disabled={changedIdx.length < 2} style={navBtn(changedIdx.length < 2)}>↓</button>
          </div>
        )}
      </div>
      <div ref={scrollRef} style={{ maxHeight: 260, overflowY: "auto", padding: "10px 12px",
        background: "var(--color-background-primary)" }}>
        {blocks.map((b, i) => (
          <div key={i} ref={(el) => { marks.current[i] = el; }}
            style={{
              fontSize: b.heading ? 12.5 : 12, lineHeight: 1.55,
              fontWeight: b.heading ? 700 : 400,
              marginBottom: b.heading ? 4 : 6, padding: b.changed ? "4px 8px" : "0 8px",
              borderRadius: 6,
              background: b.changed ? C.auto.bg : "transparent",
              borderLeft: b.changed ? `3px solid ${C.auto.fg}` : "3px solid transparent",
              color: b.changed ? C.auto.fg : "var(--color-text-primary)",
            }}>
            {b.text}
            {b.changed && b.check_id && (
              <span style={{ marginLeft: 8, fontSize: 9.5, fontWeight: 700, opacity: 0.75,
                textTransform: "uppercase", letterSpacing: "0.4px" }}>{b.check_id}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── results screen ────────────────────────────────────────────────────────────
function Results({ result, onDone }) {
  const applied = result.outcomes.filter((o) => o.status === "applied");
  const other   = result.outcomes.filter((o) => o.status !== "applied");
  const passed  = result.cdi_status === "Passed";
  return (
    <div style={{ padding: 4 }}>
      <div style={{ padding: "14px 16px", borderRadius: 12, marginBottom: 14,
        background: passed ? C.auto.bg : C.choice.bg, border: `1px solid ${passed ? C.auto.bd : C.choice.bd}` }}>
        <div style={{ fontSize: 15, fontWeight: 800, color: passed ? C.auto.fg : C.choice.fg }}>
          {applied.length} fix{applied.length === 1 ? "" : "es"} applied
        </div>
        <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginTop: 4 }}>
          CDI re-check: <b style={{ color: passed ? C.auto.fg : C.choice.fg }}>{result.cdi_status}</b>
          {!passed && result.remaining_failures > 0 &&
            ` — ${result.remaining_failures} issue${result.remaining_failures === 1 ? "" : "s"} remaining.`}
          {passed && " — the document now passes. A new version was saved."}
        </div>
      </div>

      <ChangePreview blocks={result.preview || []} />

      {applied.map((o, i) => (
        <div key={i} style={{ fontSize: 12, padding: "8px 10px", marginBottom: 6, borderRadius: 8,
          background: C.auto.bg, border: `1px solid ${C.auto.bd}` }}>
          <b style={{ color: C.auto.fg }}>{o.check_id}</b> applied
        </div>
      ))}
      {other.map((o, i) => (
        <div key={i} style={{ fontSize: 12, padding: "8px 10px", marginBottom: 6, borderRadius: 8,
          background: C.manual.bg, border: `1px solid ${C.manual.bd}`, color: "var(--color-text-secondary)" }}>
          <b>{o.check_id}</b> — {o.detail}
        </div>
      ))}

      <button onClick={onDone} style={{ marginTop: 12, width: "100%", padding: "10px", fontSize: 13,
        fontWeight: 600, borderRadius: 9, border: "none", background: "var(--color-text-primary)",
        color: "var(--color-background-primary)", cursor: "pointer" }}>Done</button>
    </div>
  );
}

// ── main panel ────────────────────────────────────────────────────────────────
export default function CdiFixPanel({ docId, docCode, onClose }) {
  const qc = useQueryClient();
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [decisions, setDecisions] = useState({});   // fix_id -> {action, replace, occurrence_index}
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const { data } = await apiClient.get(`/api/v1/lifecycle/documents/${docId}/cdi-fix/plan`);
        if (!live) return;
        setPlan(data);
        // Pre-confirm high-confidence one-click (auto) fixes; pre-fill occurrence 0.
        const init = {};
        (data.findings || []).forEach((f) => {
          const kind = kindOf(f);
          if (kind === "auto") {
            init[f.fix_id] = {
              action: "confirm", replace: f.replace ?? "",
              occurrence_index: f.locate_status === "ambiguous" ? null : 0,
            };
          }
        });
        setDecisions(init);
      } catch (e) {
        if (live) setError(e?.response?.data?.detail || e.message || "Could not load the fix plan.");
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => { live = false; };
  }, [docId]);

  const findings = plan?.findings || [];
  const counts = useMemo(() => {
    const c = { auto: 0, choice: 0, insert: 0, structural: 0, manual: 0 };
    findings.forEach((f) => { c[kindOf(f)] = (c[kindOf(f)] || 0) + 1; });
    return c;
  }, [findings]);

  // A fix is ready to send if confirmed, applicable, and (for ambiguous) has a chosen occurrence + non-empty replace.
  const readyFixes = useMemo(() => {
    return findings
      .map((f) => ({ f, d: decisions[f.fix_id] }))
      .filter(({ f, d }) => {
        if (!d || d.action !== "confirm") return false;
        const kind = kindOf(f);
        if (kind === "insert") {
          const t = insertText(f, d);
          return !!t.trim() && !hasPlaceholder(t);
        }
        if (kind !== "auto" && kind !== "choice") return false;
        const replace = d.replace ?? f.replace ?? "";
        if (!replace.trim() && kind === "choice") return false;
        if (f.locate_status === "ambiguous" && d.occurrence_index == null) return false;
        return true;
      })
      .map(({ f, d }) => kindOf(f) === "insert" ? ({
        fix_id: f.fix_id, check_id: f.check_id, action: "insert",
        insert: { ...f.insert, text: insertText(f, d) },
      }) : ({
        fix_id: f.fix_id, check_id: f.check_id, find: f.find,
        replace: d.replace ?? f.replace ?? "",
        occurrence_index: d.occurrence_index ?? null,
      }));
  }, [findings, decisions]);

  const confirmAllAuto = () => {
    const next = { ...decisions };
    findings.forEach((f) => {
      if (kindOf(f) === "auto") {
        next[f.fix_id] = { action: "confirm", replace: f.replace ?? "",
          occurrence_index: f.locate_status === "ambiguous" ? (next[f.fix_id]?.occurrence_index ?? null) : 0 };
      }
    });
    setDecisions(next);
  };

  const apply = async () => {
    setApplying(true); setError("");
    try {
      const { data } = await apiClient.post(
        `/api/v1/lifecycle/documents/${docId}/cdi-fix/apply`, { fixes: readyFixes });
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
        {/* header */}
        <div style={{ padding: "18px 22px", borderBottom: "1px solid var(--color-border-tertiary)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 800, color: "var(--color-text-primary)" }}>Fix CDI issues</div>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>
                {docCode || plan?.title || "Document"} — review each fix, then apply.
              </div>
            </div>
            <button onClick={onClose} style={{ fontSize: 20, lineHeight: 1, border: "none",
              background: "transparent", color: "var(--color-text-tertiary)", cursor: "pointer" }}>×</button>
          </div>

          {plan && !result && (
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", fontSize: 11 }}>
              {counts.auto > 0 && <Pill c={C.auto}>{counts.auto} one-click</Pill>}
              {counts.choice > 0 && <Pill c={C.choice}>{counts.choice} need a choice</Pill>}
              {counts.insert > 0 && <Pill c={C.insert}>{counts.insert} missing section{counts.insert === 1 ? "" : "s"} to add</Pill>}
              {counts.structural > 0 && <Pill c={C.structural}>{counts.structural} control block</Pill>}
              {counts.manual > 0 && <Pill c={C.manual}>{counts.manual} manual</Pill>}
            </div>
          )}
          {plan && !result && plan.stored_count != null && plan.stored_count !== plan.live_count && (
            <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--color-text-secondary)" }}>
              The document card shows {plan.stored_count} from the last upload. This list is a fresh
              check of the current file ({plan.live_count}); the card updates after you apply.
            </div>
          )}
          {plan?.editable === false && !result && (
            <div style={{ marginTop: 10, fontSize: 12, color: C.choice.fg, background: C.choice.bg,
              border: `1px solid ${C.choice.bd}`, borderRadius: 8, padding: "8px 10px" }}>
              {plan.editable_note}
            </div>
          )}
        </div>

        {/* body */}
        <div style={{ padding: "16px 22px", overflowY: "auto", flex: 1 }}>
          {loading && <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Loading fix plan…</div>}
          {error && !result && (
            <div style={{ fontSize: 12.5, color: "#A32D2D", background: "#FCEBEB",
              border: "1px solid #F09595", borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>{error}</div>
          )}

          {result ? (
            <Results result={result} onDone={onClose} />
          ) : (
            !loading && (
              findings.length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
                  {plan?.message || "No CDI issues to fix."}
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {counts.auto > 1 && (
                    <button onClick={confirmAllAuto} style={{ alignSelf: "flex-start", fontSize: 11.5,
                      fontWeight: 600, color: C.auto.fg, background: C.auto.bg, border: `1px solid ${C.auto.bd}`,
                      borderRadius: 8, padding: "6px 12px", cursor: "pointer" }}>
                      ✓ Confirm all {counts.auto} one-click fixes
                    </button>
                  )}
                  {findings.map((f) => (
                    <FixCard key={f.fix_id} f={f} decision={decisions[f.fix_id]}
                      onChange={(d) => setDecisions((p) => ({ ...p, [f.fix_id]: d }))} />
                  ))}
                </div>
              )
            )
          )}
        </div>

        {/* footer */}
        {!result && plan?.editable !== false && findings.length > 0 && (
          <div style={{ padding: "14px 22px", borderTop: "1px solid var(--color-border-tertiary)",
            display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              {readyFixes.length} fix{readyFixes.length === 1 ? "" : "es"} ready to apply
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={onClose} style={{ padding: "9px 16px", fontSize: 12.5, borderRadius: 9,
                border: "1.5px solid var(--color-border-tertiary)", background: "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer" }}>Cancel</button>
              <button onClick={apply} disabled={applying || readyFixes.length === 0}
                style={{ padding: "9px 20px", fontSize: 12.5, fontWeight: 700, borderRadius: 9, border: "none",
                  background: readyFixes.length === 0 ? "#C9CCD1" : "#085041", color: "#fff",
                  cursor: applying || readyFixes.length === 0 ? "not-allowed" : "pointer" }}>
                {applying ? "Applying…" : `Apply ${readyFixes.length} fix${readyFixes.length === 1 ? "" : "es"}`}
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
