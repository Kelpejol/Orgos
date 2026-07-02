// =============================================================================
// components/shared/CascadeImpactModal.jsx
// Global cascade-impact confirmation, per DRG-QI-REF-DINT-01-26.
// Before any decision/approval that cascades, shows what WILL be created,
// updated, and flagged — fetched from a read-only backend impact endpoint —
// plus the mandatory rationale, then confirms.
//
// Exports:
//   CascadeImpactPreview — fetch + render an impact payload (embeddable in
//                          any existing modal, e.g. Zone 2's action modal)
//   CascadeImpactModal   — full overlay: preview + rationale + confirm
//
// Impact payload shape (all endpoints share it):
//   { summary, creates:[{register,detail}], updates:[...], flags:[...],
//     warnings:[string], blocked:bool, blocked_reason:string|null }
// =============================================================================

import { useEffect, useState } from "react";
import apiClient from "../../api/grcApi.js";

const SECTION_STYLES = {
  creates:  { label: "Will create",  color: "#085041", bg: "#E1F5EE", border: "#5DCAA5", bullet: "＋" },
  updates:  { label: "Will update",  color: "#0C447C", bg: "#E6F1FB", border: "#85B7EB", bullet: "↻" },
  flags:    { label: "Will flag",    color: "#3C3489", bg: "#EEEDFE", border: "#AFA9EC", bullet: "⚑" },
};

const ImpactSection = ({ kind, rows }) => {
  if (!rows || rows.length === 0) return null;
  const s = SECTION_STYLES[kind];
  return (
    <div style={{ padding: "10px 12px", background: s.bg, borderRadius: 8,
                  border: `0.5px solid ${s.border}`, marginBottom: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: s.color,
                    textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6 }}>
        {s.label}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {rows.map((row, i) => (
          <div key={i} style={{ display: "flex", gap: 7, fontSize: 11, color: s.color, lineHeight: 1.45 }}>
            <span style={{ flexShrink: 0 }}>{s.bullet}</span>
            <span>
              <strong>{row.register}</strong>
              {row.detail ? <> — {row.detail}</> : null}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export const CascadeImpactPreview = ({ impactUrl, impactParams, impact: impactProp, onImpact }) => {
  const [impact, setImpact]   = useState(impactProp || null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  useEffect(() => {
    if (impactProp) { setImpact(impactProp); return; }
    if (!impactUrl) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    // Debounced — impactParams can change per keystroke (doc code / role inputs)
    const timer = setTimeout(() => {
      apiClient.get(impactUrl, { params: impactParams })
        .then(r => {
          if (cancelled) return;
          setImpact(r.data);
          onImpact?.(r.data);
        })
        .catch(err => {
          if (cancelled) return;
          setError(err.response?.data?.detail || err.message || "Could not load the impact preview.");
          onImpact?.(null);
        })
        .finally(() => !cancelled && setLoading(false));
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [impactUrl, JSON.stringify(impactParams || {}), impactProp]);

  if (loading) {
    return (
      <div style={{ padding: "14px 12px", background: "var(--color-background-secondary)",
                    borderRadius: 8, fontSize: 12, color: "var(--color-text-tertiary)",
                    marginBottom: 8, textAlign: "center" }}>
        Calculating cascade impact…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: "10px 12px", background: "#FAEEDA", borderRadius: 8,
                    border: "0.5px solid #FAC775", fontSize: 11, color: "#633806", marginBottom: 8 }}>
        Impact preview unavailable ({error}). The decision will still cascade to the
        downstream registers — confirm only if you are sure.
      </div>
    );
  }

  if (!impact) return null;

  return (
    <div>
      {impact.blocked && (
        <div style={{ padding: "10px 12px", background: "#FCEBEB", borderRadius: 8,
                      border: "1px solid #F09595", fontSize: 12, color: "#791F1F",
                      fontWeight: 600, marginBottom: 8 }}>
          Blocked — {impact.blocked_reason}
        </div>
      )}

      {impact.summary && !impact.blocked && (
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 10 }}>
          {impact.summary}
        </div>
      )}

      <ImpactSection kind="creates" rows={impact.creates} />
      <ImpactSection kind="updates" rows={impact.updates} />
      <ImpactSection kind="flags"   rows={impact.flags} />

      {(impact.warnings || []).map((w, i) => (
        <div key={i} style={{ padding: "8px 12px", background: "#FAEEDA", borderRadius: 8,
                              border: "0.5px solid #FAC775", fontSize: 11, color: "#633806",
                              marginBottom: 6, display: "flex", gap: 7 }}>
          <span>⚠</span><span>{w}</span>
        </div>
      ))}
    </div>
  );
};

export const CascadeImpactModal = ({
  open,
  onClose,
  title = "Confirm decision",
  subtitle,
  impactUrl,
  impactParams,
  initialRationale = "",
  requireRationale = 10,      // min chars; pass false to hide the rationale field
  confirmLabel = "Confirm & apply cascade",
  danger = false,
  isPending = false,
  onConfirm,                  // (rationale) => void|Promise
}) => {
  const [rationale, setRationale] = useState(initialRationale);
  const [impact, setImpact]       = useState(null);

  useEffect(() => {
    if (open) {
      setRationale(initialRationale || "");
      setImpact(null);
    }
  }, [open, initialRationale]);

  if (!open) return null;

  const needsRationale = requireRationale !== false;
  const ratOk   = !needsRationale || rationale.trim().length >= requireRationale;
  const blocked = !!impact?.blocked;
  const canConfirm = ratOk && !blocked && !isPending;
  const confirmBg  = danger ? "#A32D2D" : "#1D9E75";

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1100,
               display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: 560, maxWidth: "100%", maxHeight: "88vh", overflowY: "auto",
                 background: "var(--color-background-primary)", borderRadius: 16,
                 boxShadow: "0 24px 60px rgba(0,0,0,0.18)", padding: 20 }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{title}</div>
            <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 4 }}>
              {subtitle || "Review the full downstream impact before confirming."}
            </div>
          </div>
          <button onClick={onClose}
            style={{ border: "none", background: "transparent", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>
            ×
          </button>
        </div>

        <CascadeImpactPreview
          impactUrl={impactUrl}
          impactParams={impactParams}
          onImpact={setImpact}
        />

        {needsRationale && !blocked && (
          <div style={{ marginTop: 10, marginBottom: 12 }}>
            <label style={{ display: "block", marginBottom: 6, fontSize: 10, fontWeight: 600,
                            color: "var(--color-text-secondary)", textTransform: "uppercase",
                            letterSpacing: "0.4px" }}>
              Decision rationale (min {requireRationale} characters)
            </label>
            <textarea
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              rows={3}
              placeholder="Explain why you are making this decision. This is your audit trail."
              style={{ width: "100%", fontSize: 12, padding: "9px 12px", borderRadius: 8,
                       border: `1.5px solid ${ratOk ? "#5DCAA5" : "#C0C0C0"}`,
                       background: "var(--color-background-primary)",
                       color: "var(--color-text-primary)", resize: "vertical",
                       fontFamily: "var(--font-sans)", boxSizing: "border-box", outline: "none" }}
              onFocus={e => (e.target.style.borderColor = "#378ADD")}
              onBlur={e => (e.target.style.borderColor = ratOk ? "#5DCAA5" : "#C0C0C0")}
            />
            {!ratOk && rationale.trim().length > 0 && (
              <div style={{ marginTop: 4, fontSize: 10, color: "#A32D2D" }}>
                Rationale must be at least {requireRationale} characters.
              </div>
            )}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button onClick={onClose}
            style={{ padding: "10px 14px", borderRadius: 10, background: "transparent",
                     color: "var(--color-text-secondary)", border: "1.5px solid #C0C0C0",
                     cursor: "pointer" }}>
            Cancel
          </button>
          {!blocked && (
            <button
              onClick={() => onConfirm?.(rationale.trim())}
              disabled={!canConfirm}
              style={{ padding: "10px 14px", borderRadius: 10, border: "none",
                       background: canConfirm ? confirmBg : "#E8E8E8",
                       color: canConfirm ? "#fff" : "#999",
                       cursor: canConfirm ? "pointer" : "not-allowed", fontWeight: 600 }}
            >
              {isPending ? "Applying…" : confirmLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default CascadeImpactModal;
