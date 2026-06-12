// =============================================================================
// pages/StandardsMap/index.jsx
// Standards Map — Audit Readiness View
// Shows every clause in every standard Dragnet is certified against.
// Traffic lights calculated from live Control Register + Evidence Tracker data.
// Drill-down shows the full audit chain: control → evidence → owner → link.
// =============================================================================

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { LoadingState, ErrorState } from "../../components/shared/LoadingState.jsx";
import apiClient from "../../api/grcApi.js";

function fmtDate(str) {
  if (!str) return "—";
  try {
    const d = new Date(str);
    if (isNaN(d.getTime())) return str;
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  } catch { return str; }
}

// =============================================================================
//  API
// =============================================================================

const standardsApi = {
  map:    (standard) =>
    apiClient.get("/api/v1/standards/map",
      standard ? { params: { standard } } : {}).then(r => r.data),

  clause: (clauseCode) =>
    apiClient.get(`/api/v1/standards/map/${encodeURIComponent(clauseCode)}`)
      .then(r => r.data),
};

// =============================================================================
//  Traffic light component
// =============================================================================

const TrafficLight = ({ status, size = 10 }) => {
  const colors = { Green: "#1D9E75", Amber: "#BA7517", Red: "#A32D2D" };
  const color  = colors[status] || "#B4B2A9";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <div style={{
        width: size, height: size, borderRadius: "50%",
        background: color, flexShrink: 0,
        boxShadow: `0 0 ${size / 2}px ${color}60`,
      }} />
      <span style={{ fontSize: 10, fontWeight: 600, color }}>{status || "Not assessed"}</span>
    </div>
  );
};

// =============================================================================
//  Clause detail view — the full audit chain
// =============================================================================

const ClauseDetail = ({ clauseCode, onBack }) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ["clause", clauseCode],
    queryFn:  () => standardsApi.clause(clauseCode),
    staleTime: 30_000,
  });

  if (isLoading) return <LoadingState message={`Loading ${clauseCode}...`} />;
  if (error) return (
    <div>
      <button onClick={onBack}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none",
                 border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}>
        ← Back
      </button>
      <div style={{ color: "#A32D2D", fontSize: 12 }}>
        Could not load clause detail: {error.message}
      </div>
    </div>
  );

  const { standard, clause, title, traffic_light, controls = [], evidence = [] } = data;

  const tlColors = { Green: "#1D9E75", Amber: "#BA7517", Red: "#A32D2D" };
  const tlColor  = tlColors[traffic_light] || "#B4B2A9";
  const tlBg     = { Green: "#E1F5EE", Amber: "#FAEEDA", Red: "#FCEBEB" }[traffic_light] || "#F1EFE8";
  const tlBd     = { Green: "#5DCAA5", Amber: "#FAC775", Red: "#F09595" }[traffic_light] || "#B4B2A9";

  return (
    <div>
      <button onClick={onBack}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none",
                 border: "none", cursor: "pointer", padding: 0, marginBottom: 14 }}>
        ← Back to standards map
      </button>

      {/* Clause header */}
      <div style={{
        padding: "16px 18px", borderRadius: 12, marginBottom: 20,
        background: tlBg, border: `1.5px solid ${tlBd}`,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-start", marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: tlColor,
                          textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 4 }}>
              {standard}
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--color-text-primary)",
                          marginBottom: 2 }}>
              {clause}
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{title}</div>
          </div>
          <div>
            <TrafficLight status={traffic_light} size={14} />
          </div>
        </div>
        <div style={{ display: "flex", gap: 16, fontSize: 11, color: tlColor }}>
          <span>{controls.length} control{controls.length !== 1 ? "s" : ""}</span>
          <span>{evidence.filter(e => e.Status === "Accepted").length} evidence accepted</span>
          {traffic_light === "Red" && (
            <span style={{ fontWeight: 600 }}>⚠ This clause will fail audit</span>
          )}
          {traffic_light === "Amber" && (
            <span style={{ fontWeight: 600 }}>⚠ Action needed before audit</span>
          )}
          {traffic_light === "Green" && (
            <span style={{ fontWeight: 600 }}>✓ Ready for audit</span>
          )}
        </div>
      </div>

      {/* No controls */}
      {controls.length === 0 && (
        <div style={{ padding: "24px", textAlign: "center",
                      border: "1px dashed #F09595", borderRadius: 12,
                      background: "#FFF8F8", marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: "#A32D2D", marginBottom: 4 }}>
            No controls mapped to this clause
          </div>
          <div style={{ fontSize: 12, color: "#A32D2D", opacity: 0.8 }}>
            This clause has a Red traffic light because no controls cover it.
            Extract and confirm controls from the relevant policies in the Extraction Review screen.
          </div>
        </div>
      )}

      {/* Controls with linked evidence */}
      <div style={{ maxHeight: 520, overflowY: "auto" }}>
      {controls.map((control, ci) => {
        const linkedEvidence = evidence.filter(e => e.LinkedControlId === control.id);
        const isBlocked = control.Status === "Blocked";

        return (
          <div key={control.id} style={{
            border: `1px solid ${isBlocked ? "#F09595" : "#D0D0D0"}`,
            borderLeft: `4px solid ${isBlocked ? "#A32D2D" : "#378ADD"}`,
            borderRadius: 12, marginBottom: 12, overflow: "hidden",
          }}>
            {/* Control row */}
            <div style={{ padding: "12px 14px",
                          background: isBlocked ? "#FFF8F8" : "var(--color-background-primary)" }}>
              <div style={{ display: "flex", gap: 4, marginBottom: 6, flexWrap: "wrap" }}>
                {control.ControlType && <StatusBadge label={control.ControlType} />}
                {isBlocked && <StatusBadge label="Blocked" />}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 6 }}>
                {control.ControlStatement}
              </div>
              <div>
                <Field l="Owner role"       v={control.OwnerRole || "—"} />
                <Field l="Source document"  v={control.SourceDocument || "—"} />
                {control.RiskImplication && (
                  <Field l="Risk if fails"  v={control.RiskImplication} color="#A32D2D" />
                )}
                {control.EscalationNote && (
                  <Field l="Escalation"     v={control.EscalationNote} />
                )}
              </div>
              {isBlocked && (
                <div style={{ marginTop: 8, padding: "6px 10px", background: "#FCEBEB",
                              borderRadius: 6, fontSize: 11, color: "#791F1F" }}>
                  Blocked — role "{control.OwnerRole}" is unassigned in the Role Register.
                  Assign someone to activate this control.
                </div>
              )}
            </div>

            {/* Evidence items */}
            {linkedEvidence.length === 0 ? (
              <div style={{ padding: "10px 14px",
                            background: "var(--color-background-secondary)",
                            borderTop: "0.5px solid var(--color-border-tertiary)",
                            fontSize: 11, color: "var(--color-text-tertiary)" }}>
                No evidence requirement defined — this control is not yet collectable.
              </div>
            ) : (
              linkedEvidence.map((evd, ei) => {
                const evdColors = {
                  Accepted: { color: "#085041", bg: "#E1F5EE", bd: "#5DCAA5" },
                  Submitted:{ color: "#0C447C", bg: "#E6F1FB", bd: "#85B7EB" },
                  Overdue:  { color: "#791F1F", bg: "#FCEBEB", bd: "#F09595" },
                  Pending:  { color: "#595952", bg: "#F1EFE8", bd: "#B4B2A9" },
                  Rejected: { color: "#791F1F", bg: "#FCEBEB", bd: "#F09595" },
                };
                const ec = evdColors[evd.Status] || evdColors.Pending;

                return (
                  <div key={evd.id} style={{
                    padding: "10px 14px",
                    background: ec.bg,
                    borderTop: "0.5px solid var(--color-border-tertiary)",
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between",
                                  alignItems: "flex-start", marginBottom: 4 }}>
                      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                        <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3,
                                       fontWeight: 700, fontFamily: "var(--font-mono)",
                                       background: ec.bd + "40", color: ec.color,
                                       border: `0.5px solid ${ec.bd}` }}>
                          {evd.EvidenceType || "?"}
                        </span>
                        <span style={{ fontSize: 10, fontWeight: 600, color: ec.color }}>
                          {evd.Status}
                        </span>
                      </div>
                      {evd.EvidenceLink && (
                        <a href={evd.EvidenceLink} target="_blank" rel="noreferrer"
                          style={{ fontSize: 10, color: ec.color, textDecoration: "underline",
                                   fontWeight: 500 }}>
                          View evidence ↗
                        </a>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: ec.color, lineHeight: 1.4, marginBottom: 4 }}>
                      {evd.EvidenceDescription}
                    </div>
                    <div style={{ fontSize: 10, color: ec.color, opacity: 0.8 }}>
                      {evd.OwnerRole} · {evd.Frequency}
                      {evd.LastCollected ? ` · Last: ${fmtDate(evd.LastCollected)}` : ""}
                      {evd.ValidationCriteria
                        ? ` · Accept if: ${evd.ValidationCriteria.slice(0, 60)}${evd.ValidationCriteria.length > 60 ? "..." : ""}`
                        : ""}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        );
      })}
      </div>
    </div>
  );
};

// =============================================================================
//  Main component — clause list with traffic lights
// =============================================================================

export default function StandardsMap() {
  const [selectedClause, setSelectedClause] = useState(null);
  const [standardFilter, setStandardFilter] = useState("All");
  const [tlFilter, setTlFilter]             = useState("All");
  const [search, setSearch]                 = useState("");

  const { data: clauses = [], isLoading, error, refetch } = useQuery({
    queryKey: ["standards-map", standardFilter === "All" ? undefined : standardFilter],
    queryFn:  () => standardsApi.map(standardFilter === "All" ? undefined : standardFilter),
    staleTime: 30_000,
  });

  const filtered = useMemo(() => {
    let list = clauses;
    if (tlFilter !== "All") list = list.filter(c => c.traffic_light === tlFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(c =>
        c.clause.toLowerCase().includes(q) ||
        c.title.toLowerCase().includes(q)
      );
    }
    return list;
  }, [clauses, tlFilter, search]);

  const counts = useMemo(() => ({
    Green: clauses.filter(c => c.traffic_light === "Green").length,
    Amber: clauses.filter(c => c.traffic_light === "Amber").length,
    Red:   clauses.filter(c => c.traffic_light === "Red").length,
  }), [clauses]);

  if (selectedClause) {
    return <ClauseDetail clauseCode={selectedClause} onBack={() => setSelectedClause(null)} />;
  }

  if (isLoading) return <LoadingState message="Calculating standards coverage..." />;
  if (error)     return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Standards map</div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Audit readiness view — live coverage across ISO 9001, ISO 27001, and NDPA.
              Click any clause to see the full audit chain.
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {[
              { l: `${counts.Green} Green`, bg: "#E1F5EE", color: "#085041", bd: "#5DCAA5" },
              { l: `${counts.Amber} Amber`, bg: "#FAEEDA", color: "#633806", bd: "#FAC775" },
              { l: `${counts.Red} Red`,     bg: "#FCEBEB", color: "#791F1F", bd: "#F09595" },
            ].map(s => (
              <div key={s.l} style={{ padding: "3px 8px", borderRadius: 6, fontSize: 11,
                                      fontWeight: 600, background: s.bg, color: s.color,
                                      border: `0.5px solid ${s.bd}` }}>
                {s.l}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {/* Standard filter */}
        {["All", "ISO 27001", "ISO 9001", "NDPA"].map(s => (
          <button key={s} onClick={() => setStandardFilter(s)}
            style={{ padding: "5px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                     fontWeight: standardFilter === s ? 600 : 400,
                     border: standardFilter === s ? "1px solid var(--color-border-info)" : "1.5px solid #C0C0C0",
                     background: standardFilter === s ? "var(--color-background-info)" : "var(--color-background-primary)",
                     color: standardFilter === s ? "var(--color-text-info)" : "var(--color-text-secondary)" }}>
            {s}
          </button>
        ))}
        <div style={{ width: 1, background: "#D0D0D0", alignSelf: "stretch" }} />
        {/* Traffic light filter */}
        {[
          { k: "All",   l: "All" },
          { k: "Red",   l: "Red only",   color: "#A32D2D" },
          { k: "Amber", l: "Amber only", color: "#BA7517" },
          { k: "Green", l: "Green only", color: "#1D9E75" },
        ].map(f => (
          <button key={f.k} onClick={() => setTlFilter(f.k)}
            style={{ padding: "5px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                     fontWeight: tlFilter === f.k ? 600 : 400,
                     border: tlFilter === f.k && f.color
                       ? `1.5px solid ${f.color}` : "1.5px solid #C0C0C0",
                     background: tlFilter === f.k && f.color
                       ? f.color + "18" : "var(--color-background-primary)",
                     color: tlFilter === f.k && f.color ? f.color : "var(--color-text-secondary)" }}>
            {f.l}
          </button>
        ))}
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search clause or title..."
          style={{ flex: 1, minWidth: 160, fontSize: 12, padding: "6px 12px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {/* Clauses table */}
      <div style={{ border: "1px solid #D0D0D0", borderRadius: 12, overflow: "hidden" }}>
        {/* Header */}
        <div style={{
          display: "grid", gridTemplateColumns: "80px 1fr 80px 60px 80px",
          padding: "7px 14px", background: "var(--color-background-secondary)",
          borderBottom: "1px solid #E8E8E8",
        }}>
          {["Standard", "Title", "Controls", "Evidence", "Status"].map(h => (
            <div key={h} style={{ fontSize: 11, fontWeight: 500,
                                  color: "var(--color-text-secondary)" }}>
              {h}
            </div>
          ))}
        </div>

        {filtered.length === 0 ? (
          <div style={{ padding: "32px", textAlign: "center",
                        fontSize: 12, color: "var(--color-text-tertiary)" }}>
            No clauses match your filter.
          </div>
        ) : (
          filtered.map((clause, i) => {
            const tlColors = { Green: "#1D9E75", Amber: "#BA7517", Red: "#A32D2D" };
            const tlColor  = tlColors[clause.traffic_light] || "#B4B2A9";
            const isRed    = clause.traffic_light === "Red";

            return (
              <div
                key={`${clause.standard}-${clause.clause}`}
                role="button" tabIndex={0}
                onClick={() => setSelectedClause(clause.clause)}
                onKeyDown={e => e.key === "Enter" && setSelectedClause(clause.clause)}
                style={{
                  display: "grid", gridTemplateColumns: "80px 1fr 80px 60px 80px",
                  padding: "10px 14px",
                  borderBottom: i < filtered.length - 1 ? "1px solid #E8E8E8" : "none",
                  cursor: "pointer",
                  background: isRed ? "#FFF8F8"
                    : i % 2 ? "var(--color-background-secondary)" : "transparent",
                  borderLeft: `3px solid ${tlColor}`,
                  transition: "background 0.1s",
                }}
                onMouseEnter={e => (e.currentTarget.style.background = "var(--color-background-info)")}
                onMouseLeave={e => (e.currentTarget.style.background = isRed ? "#FFF8F8"
                  : i % 2 ? "var(--color-background-secondary)" : "transparent")}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontSize: 9, fontWeight: 600, color: "var(--color-text-tertiary)",
                                 textTransform: "uppercase" }}>
                    {clause.standard}
                  </span>
                  <span style={{ fontSize: 11, fontFamily: "var(--font-mono)",
                                 fontWeight: 600, color: "var(--color-text-primary)" }}>
                    {clause.clause}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: "var(--color-text-primary)",
                               lineHeight: 1.4, paddingRight: 12 }}>
                  {clause.title}
                </div>
                <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                  {clause.controls_count}
                </div>
                <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                  {clause.evidence_accepted}
                </div>
                <div>
                  <TrafficLight status={clause.traffic_light} />
                </div>
              </div>
            );
          })
        )}
      </div>

      <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 8 }}>
        {filtered.length} of {clauses.length} clauses · Click any row to see the full audit chain
      </div>
    </>
  );
}