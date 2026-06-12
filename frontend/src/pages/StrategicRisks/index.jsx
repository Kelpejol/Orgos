// =============================================================================
// pages/StrategicRisks/index.jsx
// Strategic Risk Register — ExCo-curated business-level risks.
// Three entry paths: direct ExCo input, gap acceptance, incident escalation.
// No AI. Human judgment only. Per Bobby's Strategic Risk Register spec.
// =============================================================================

import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { LoadingState, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import ReadOnlyBanner from "../../components/shared/ReadOnlyBanner.jsx";
import apiClient from "../../api/grcApi.js";

// =============================================================================
//  API
// =============================================================================

const riskApi = {
  list:   (status) =>
    apiClient.get("/api/v1/risks",
      status ? { params: { status_filter: status } } : {}).then(r => r.data),
  create: (body) =>
    apiClient.post("/api/v1/risks", body).then(r => r.data),
  update: (id, body) =>
    apiClient.patch(`/api/v1/risks/${id}`, body).then(r => r.data),
};

// =============================================================================
//  Date helper — strips time component from ISO strings
// =============================================================================

function fmtDate(str) {
  if (!str) return "—";
  try {
    const d = new Date(str);
    if (isNaN(d.getTime())) return str;
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return str;
  }
}

// =============================================================================
//  Score helpers — bands: 1-3 Low, 4-6 Medium, 7-9 High, 10-12 Critical
// =============================================================================

const LIKELIHOOD_VALUES = { Low: 1, Medium: 2, High: 3 };
const IMPACT_VALUES      = { Low: 1, Medium: 2, High: 3, Critical: 4 };

function calcScore(likelihood, impact) {
  return (LIKELIHOOD_VALUES[likelihood] || 1) * (IMPACT_VALUES[impact] || 1);
}

function scoreLabel(score) {
  if (score <= 3)  return "Low";
  if (score <= 6)  return "Medium";
  if (score <= 9)  return "High";
  return "Critical";
}

function scoreColor(score) {
  if (score <= 3)  return "#1D9E75";
  if (score <= 6)  return "#BA7517";
  if (score <= 9)  return "#D85A30";
  return "#A32D2D";
}

// =============================================================================
//  Score badge
// =============================================================================

const ScoreBadge = ({ score, label, color }) => (
  <div style={{
    display: "inline-flex", alignItems: "center", gap: 6,
    padding: "3px 10px", borderRadius: 6,
    background: color + "18", border: `1px solid ${color}40`,
  }}>
    <span style={{ fontSize: 16, fontWeight: 700, color, lineHeight: 1 }}>{score}</span>
    <span style={{ fontSize: 10, fontWeight: 600, color, textTransform: "uppercase",
                   letterSpacing: "0.5px" }}>{label}</span>
  </div>
);

// =============================================================================
//  Add risk form
// =============================================================================

const CATEGORIES = [
  "SWOT — Strength", "SWOT — Weakness", "SWOT — Opportunity", "SWOT — Threat",
  "PESTLE — Political", "PESTLE — Economic", "PESTLE — Social",
  "PESTLE — Technology", "PESTLE — Legal", "PESTLE — Environmental",
];

const AddRiskForm = ({ onSuccess, onCancel, prePopulated = {} }) => {
  const [form, setForm] = useState({
    description:       prePopulated.description || "",
    category:          prePopulated.category    || "SWOT — Threat",
    source:            prePopulated.source      || "ExCo assessment",
    likelihood:        "Medium",
    impact:            "Medium",
    treatment:         "Mitigate",
    treatment_actions: "",
    escalation_note:   "",
    notes:             prePopulated.notes       || "",
  });
  const [saving, setSaving] = useState(false);
  const [error,  setError]  = useState("");

  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }));

  const score = calcScore(form.likelihood, form.impact);
  const sColor = scoreColor(score);
  const sLabel = scoreLabel(score);

  const handleCreate = async () => {
    if (!form.description.trim()) { setError("Risk description is required."); return; }
    if (!form.category)           { setError("Category is required."); return; }
    if (["Mitigate", "Transfer"].includes(form.treatment) && !form.treatment_actions.trim()) {
      setError("Treatment actions are required for Mitigate and Transfer treatments.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await riskApi.create({
        description:       form.description.trim(),
        category:          form.category,
        source:            form.source,
        likelihood:        form.likelihood,
        impact:            form.impact,
        treatment:         form.treatment,
        treatment_actions: form.treatment_actions.trim() || undefined,
        escalation_note:   form.escalation_note.trim()   || undefined,
        notes:             form.notes.trim()             || undefined,
        related_gap_id:    form.related_gap_id.trim()    || undefined,
      });
      onSuccess();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to create risk.");
    } finally {
      setSaving(false);
    }
  };

  const inp = {
    width: "100%", fontSize: 12, padding: "9px 11px", borderRadius: 8,
    border: "1.5px solid #D0D0D0", background: "var(--color-background-primary)",
    color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box",
  };
  const lbl = {
    display: "block", fontSize: 11, fontWeight: 600,
    color: "var(--color-text-secondary)", marginBottom: 5,
    textTransform: "uppercase", letterSpacing: "0.5px",
  };
  const focus = e => (e.target.style.borderColor = "#378ADD");
  const blur  = e => (e.target.style.borderColor = "#D0D0D0");

  return (
    <div style={{ padding: "20px", background: "var(--color-background-primary)",
                  borderRadius: 14, border: "1.5px solid #A32D2D",
                  boxShadow: "0 4px 20px rgba(163,45,45,0.1)", marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 18 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 3 }}>Add strategic risk</div>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
            ExCo-level risk. Human judgment only — no AI extraction touches this register.
          </div>
        </div>
        <button onClick={onCancel}
          style={{ background: "none", border: "none", cursor: "pointer",
                   fontSize: 18, color: "var(--color-text-tertiary)" }}>×</button>
      </div>

      {error && (
        <div style={{ padding: "9px 12px", background: "#FCEBEB", borderRadius: 8,
                      fontSize: 12, color: "#791F1F", marginBottom: 14,
                      border: "1px solid #F09595" }}>
          {error}
        </div>
      )}

      {prePopulated.source && prePopulated.source !== "ExCo assessment" && (
        <div style={{ padding: "8px 12px", background: "#EEEDFE", borderRadius: 8,
                      fontSize: 11, color: "#3C3489", marginBottom: 14,
                      border: "0.5px solid #AFA9EC" }}>
          Source: {prePopulated.source}
          {prePopulated.related_gap_id && ` · Gap: ${prePopulated.related_gap_id}`}
        </div>
      )}

      {/* Description */}
      <div style={{ marginBottom: 14 }}>
        <label style={lbl}>Risk description <span style={{ color: "#A32D2D" }}>*</span></label>
        <textarea value={form.description} onChange={set("description")} rows={3}
          placeholder="What could happen? Be specific about the business risk, not a technical control gap."
          style={{ ...inp, resize: "vertical", fontFamily: "var(--font-sans)" }}
          onFocus={focus} onBlur={blur} />
      </div>

      {/* Category and source */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
        <div>
          <label style={lbl}>Category <span style={{ color: "#A32D2D" }}>*</span></label>
          <select value={form.category} onChange={set("category")} style={inp}>
            {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label style={lbl}>Source</label>
          <select value={form.source} onChange={set("source")} style={inp}>
            <option value="ExCo assessment">ExCo assessment</option>
            <option value="Gap acceptance">Gap acceptance</option>
            <option value="Incident escalation">Incident escalation</option>
          </select>
        </div>
      </div>

      {/* Likelihood and Impact with live score */}
      <div style={{ marginBottom: 14 }}>
        <label style={lbl}>Risk assessment</label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 120px", gap: 12, alignItems: "end" }}>
          <div>
            <label style={{ ...lbl, fontSize: 10 }}>Likelihood</label>
            <select value={form.likelihood} onChange={set("likelihood")} style={inp}>
              {["Low", "Medium", "High"].map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <div>
            <label style={{ ...lbl, fontSize: 10 }}>Impact</label>
            <select value={form.impact} onChange={set("impact")} style={inp}>
              {["Low", "Medium", "High", "Critical"].map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <div style={{ textAlign: "center", paddingBottom: 2 }}>
            <ScoreBadge score={score} label={sLabel} color={sColor} />
          </div>
        </div>
      </div>

      {/* Treatment */}
      <div style={{ marginBottom: 14 }}>
        <label style={lbl}>Treatment</label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {["Mitigate", "Accept", "Transfer", "Avoid"].map(t => (
            <button key={t} onClick={() => setForm(f => ({ ...f, treatment: t }))}
              style={{ padding: "8px", fontSize: 12, borderRadius: 8, cursor: "pointer",
                       fontWeight: form.treatment === t ? 600 : 400,
                       border: form.treatment === t ? "none" : "1.5px solid #D0D0D0",
                       background: form.treatment === t ? "#1F4E79" : "var(--color-background-primary)",
                       color: form.treatment === t ? "#fff" : "var(--color-text-primary)" }}>
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Treatment actions — required for Mitigate and Transfer */}
      {["Mitigate", "Transfer"].includes(form.treatment) && (
        <div style={{ marginBottom: 14 }}>
          <label style={lbl}>
            Treatment actions <span style={{ color: "#A32D2D" }}>*</span>
          </label>
          <textarea value={form.treatment_actions} onChange={set("treatment_actions")} rows={2}
            placeholder="What is being done to mitigate or transfer this risk? Be specific."
            style={{ ...inp, resize: "vertical", fontFamily: "var(--font-sans)" }}
            onFocus={focus} onBlur={blur} />
        </div>
      )}

      {/* Escalation note and notes */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
        <div>
          <label style={lbl}>Escalation note</label>
          <input type="text" value={form.escalation_note} onChange={set("escalation_note")}
            placeholder="e.g. Notify CCO within 24 hours if risk materialises"
            style={inp} onFocus={focus} onBlur={blur} />
        </div>
        <div>
          <label style={lbl}>Notes</label>
          <input type="text" value={form.notes} onChange={set("notes")}
            placeholder="ExCo discussion points, context..."
            style={inp} onFocus={focus} onBlur={blur} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 10 }}>
        <button onClick={handleCreate} disabled={saving || !form.description.trim()}
          style={{ flex: 1, padding: "11px", fontSize: 13, borderRadius: 9,
                   border: "none", fontWeight: 600,
                   background: saving || !form.description.trim() ? "#E8E8E8" : "#A32D2D",
                   color: saving || !form.description.trim() ? "#999" : "#fff",
                   cursor: saving || !form.description.trim() ? "not-allowed" : "pointer" }}>
          {saving ? "Adding..." : "Add to Strategic Risk Register →"}
        </button>
        <button onClick={onCancel}
          style={{ padding: "11px 18px", fontSize: 13, borderRadius: 9,
                   border: "1.5px solid #D0D0D0", background: "transparent",
                   color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Cancel
        </button>
      </div>
    </div>
  );
};

// =============================================================================
//  Risk card
// =============================================================================

const STATUS_TRANSITIONS = {
  Open:             ["Under treatment", "Accepted", "Transferred", "Avoided"],
  "Under treatment": ["Accepted", "Transferred", "Avoided", "Closed"],
  Accepted:         ["Closed"],
  Transferred:      ["Closed"],
  Avoided:          ["Closed"],
  Closed:           [],
};

const STATUS_BTN_LABELS = {
  "Under treatment": "Mark under treatment",
  Accepted:          "Accept risk",
  Transferred:       "Mark transferred",
  Avoided:           "Mark avoided",
  Closed:            "Close — treatment complete",
};

const STATUS_BTN_STYLES = {
  "Under treatment": { background: "#1D9E75", color: "#fff", border: "none" },
  Accepted:          { background: "transparent", color: "var(--color-text-secondary)", border: "1.5px solid #C0C0C0" },
  Transferred:       { background: "transparent", color: "#0C447C", border: "1.5px solid #85B7EB" },
  Avoided:           { background: "transparent", color: "#595952", border: "1.5px solid #B4B2A9" },
  Closed:            { background: "#0C447C", color: "#fff", border: "none" },
};

const RiskCard = ({ risk, onUpdate, isAdmin }) => {
  const [expanded, setExpanded] = useState(false);
  const [updating, setUpdating] = useState(false);

  const handleStatusChange = async (newStatus) => {
    setUpdating(true);
    try {
      await onUpdate(risk.id, { status: newStatus });
    } finally {
      setUpdating(false);
    }
  };

  const transitions = STATUS_TRANSITIONS[risk.Status] || [];

  return (
    <div style={{
      border: `1px solid ${risk.RiskScoreColor}40`,
      borderLeft: `4px solid ${risk.RiskScoreColor}`,
      borderRadius: 12,
      background: risk.Status === "Closed"
        ? "var(--color-background-secondary)"
        : "var(--color-background-primary)",
      opacity: risk.Status === "Closed" ? 0.75 : 1,
      transition: "box-shadow 0.15s",
    }}
      onMouseEnter={e => risk.Status !== "Closed" && (e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)")}
      onMouseLeave={e => (e.currentTarget.style.boxShadow = "none")}
    >
      {/* Header */}
      <div
        role="button" tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={e => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "12px 14px", cursor: "pointer" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-start", marginBottom: 6 }}>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <ScoreBadge
              score={risk.RiskScore}
              label={risk.RiskScoreLabel}
              color={risk.RiskScoreColor}
            />
            <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 3,
                           background: "var(--color-background-secondary)",
                           color: "var(--color-text-secondary)",
                           border: "0.5px solid var(--color-border-tertiary)", fontWeight: 500 }}>
              {risk.Category}
            </span>
            <StatusBadge label={risk.Status} />
            {risk.ReviewOverdue && (
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3,
                             background: "#FCEBEB", color: "#791F1F",
                             border: "0.5px solid #F09595", fontWeight: 700 }}>
                REVIEW OVERDUE
              </span>
            )}
            {risk.RiskId && (
              <span style={{ fontSize: 9, fontFamily: "var(--font-mono)",
                             color: "var(--color-text-tertiary)" }}>
                {risk.RiskId}
              </span>
            )}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 4 }}>
          {risk.Description}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between",
                      fontSize: 11, color: "var(--color-text-secondary)" }}>
          <span>{risk.Treatment} · {risk.OwnerName || "Owner TBC"}</span>
          <span style={{ color: risk.ReviewOverdue ? "#A32D2D" : "var(--color-text-tertiary)" }}>
            Review: {risk.ReviewDate ? fmtDate(risk.ReviewDate) : "Not set"}
          </span>
        </div>
      </div>

      {/* Expanded */}
      {expanded && (
        <div style={{
          borderTop: `1px solid ${risk.RiskScoreColor}30`,
          padding: "12px 14px",
          maxHeight: 340,
          overflowY: "auto",
        }}>
          <div style={{ marginBottom: 10 }}>
            <Field l="Likelihood"    v={risk.Likelihood} />
            <Field l="Impact"        v={risk.Impact} />
            <Field l="Treatment"     v={risk.Treatment} />
            <Field l="Source"        v={risk.Source} />
            <Field l="Identified"    v={fmtDate(risk.DateIdentified)} />
            <Field l="Last reviewed" v={risk.LastReviewed ? fmtDate(risk.LastReviewed) : "Not reviewed"} />
            {risk.AcceptedBy && (
              <Field l="Accepted by" v={`${risk.AcceptedBy}${risk.AcceptedDate ? ` on ${fmtDate(risk.AcceptedDate)}` : ""}`} />
            )}
          </div>

          {risk.TreatmentActions && (
            <div style={{ padding: "8px 10px", background: "#E1F5EE", borderRadius: 7,
                          fontSize: 11, color: "#085041", marginBottom: 8,
                          border: "0.5px solid #5DCAA5" }}>
              <strong>Treatment actions:</strong> {risk.TreatmentActions}
            </div>
          )}
          {risk.EscalationNote && (
            <Field l="Escalation" v={risk.EscalationNote} color="#A32D2D" />
          )}
          {risk.RelatedGapId && (
            <Field l="Related gap" v={risk.RelatedGapId} />
          )}
          {risk.Notes && <Field l="Notes" v={risk.Notes} />}

          {/* Status transition buttons — Admin only */}
          {isAdmin && transitions.length > 0 && (
            <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
              {transitions.map(nextStatus => (
                <button
                  key={nextStatus}
                  onClick={() => handleStatusChange(nextStatus)}
                  disabled={updating}
                  style={{
                    padding: "6px 12px", fontSize: 11, borderRadius: 7, cursor: "pointer",
                    fontWeight: 500, opacity: updating ? 0.6 : 1,
                    ...(STATUS_BTN_STYLES[nextStatus] || {}),
                  }}>
                  {STATUS_BTN_LABELS[nextStatus] || nextStatus}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Main component
// =============================================================================

const STATUS_FILTERS = ["All", "Open", "Under treatment", "Accepted", "Transferred", "Avoided", "Closed"];

export default function StrategicRisks() {
  const [showForm,      setShowForm]      = useState(false);
  const [statusFilter,  setStatusFilter]  = useState("All");
  const [search,        setSearch]        = useState("");

  const { isAdmin } = useCurrentUserRole();
  const qc = useQueryClient();
  const { data: risks = [], isLoading, error, refetch } = useQuery({
    queryKey: ["risks"],
    queryFn:  () => riskApi.list(),
    staleTime: 60_000,
  });

  const filtered = useMemo(() => {
    let list = risks;
    if (statusFilter !== "All") list = list.filter(r => r.Status === statusFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(r =>
        (r.Description || "").toLowerCase().includes(q) ||
        (r.Category    || "").toLowerCase().includes(q) ||
        (r.RiskId      || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [risks, statusFilter, search]);

  // Critical = score >= 10 (bands: 1-3 Low, 4-6 Medium, 7-9 High, 10-12 Critical)
  const counts = useMemo(() => ({
    critical: risks.filter(r => r.RiskScore >= 10).length,
    open:     risks.filter(r => r.Status === "Open").length,
    overdue:  risks.filter(r => r.ReviewOverdue).length,
  }), [risks]);

  const handleUpdate = async (id, body) => {
    await riskApi.update(id, body);
    qc.invalidateQueries({ queryKey: ["risks"] });
  };

  if (isLoading) return <LoadingState message="Loading strategic risks..." />;
  if (error)     return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      {!isAdmin && (
        <ReadOnlyBanner message="Strategic risks are curated by OrgOS Admins (ExCo). You have read-only access to this register." />
      )}
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Strategic risks</div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              ExCo-curated business risks from SWOT/PESTLE analysis, market conditions, and
              regulatory shifts. No AI extraction — human judgment only.
            </div>
          </div>
          {isAdmin && (
            <button
              onClick={() => setShowForm(!showForm)}
              style={{ padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "none",
                       background: "#A32D2D", color: "#fff", cursor: "pointer",
                       fontWeight: 500, flexShrink: 0 }}
            >
              + Add risk
            </button>
          )}
        </div>

        {/* Summary stats */}
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          {[
            { l: `${risks.length} total`,           color: "#595952", bg: "#F1EFE8", bd: "#B4B2A9" },
            { l: `${counts.critical} critical`,     color: "#791F1F", bg: "#FCEBEB", bd: "#F09595" },
            { l: `${counts.open} open`,              color: "#A32D2D", bg: "#FFF8F8", bd: "#F09595" },
            { l: `${counts.overdue} review overdue`, color: "#633806", bg: "#FAEEDA", bd: "#FAC775" },
          ].map(s => (
            <div key={s.l} style={{ padding: "3px 10px", borderRadius: 6, fontSize: 11,
                                    fontWeight: 500, background: s.bg, color: s.color,
                                    border: `0.5px solid ${s.bd}` }}>
              {s.l}
            </div>
          ))}
        </div>
      </div>

      {/* Add risk form */}
      {showForm && (
        <AddRiskForm
          onSuccess={() => { setShowForm(false); qc.invalidateQueries({ queryKey: ["risks"] }); }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* Filters */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {STATUS_FILTERS.map(s => (
          <button key={s} onClick={() => setStatusFilter(s)}
            style={{ padding: "5px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                     fontWeight: statusFilter === s ? 600 : 400,
                     border: statusFilter === s ? "1.5px solid #A32D2D" : "1.5px solid #C0C0C0",
                     background: statusFilter === s ? "#FCEBEB" : "var(--color-background-primary)",
                     color: statusFilter === s ? "#A32D2D" : "var(--color-text-secondary)" }}>
            {s}
          </button>
        ))}
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search risks, category, risk ID..."
          style={{ flex: 1, minWidth: 180, fontSize: 12, padding: "6px 12px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {/* Risk list */}
      {filtered.length === 0 ? (
        <EmptyState message={
          risks.length === 0
            ? "No strategic risks recorded. Click + Add risk to record the first one from your SWOT or PESTLE analysis."
            : "No risks match your filter."
        } />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map(risk => (
            <RiskCard key={risk.id} risk={risk} onUpdate={handleUpdate} isAdmin={isAdmin} />
          ))}
        </div>
      )}

      {filtered.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 8 }}>
          {filtered.length} of {risks.length} risks
        </div>
      )}
    </>
  );
}
