// =============================================================================
// pages/ControlRegister/index.jsx
// Control Register — wired to SharePoint, populated by Zone 1 cascade.
// Every entry here was confirmed by a human via the Extraction Review screen.
// =============================================================================

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { LoadingState, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import apiClient from "../../api/grcApi.js";

const controlApi = {
  list: () => apiClient.get("/api/v1/controls").then(r => r.data),
};

function useControls() {
  return useQuery({
    queryKey: ["controls"],
    queryFn:  controlApi.list,
    staleTime: 30_000,
  });
}

const TYPE_COLORS = {
  Preventive: { color: "#085041", bg: "#E1F5EE", bd: "#5DCAA5" },
  Detective:  { color: "#0C447C", bg: "#E6F1FB", bd: "#85B7EB" },
  Corrective: { color: "#712B13", bg: "#FAECE7", bd: "#F0997B" },
  Directive:  { color: "#3C3489", bg: "#EEEDFE", bd: "#AFA9EC" },
};

export default function ControlRegister() {
  const [search, setSearch]   = useState("");
  const [selected, setSelected] = useState(null);
  const [typeFilter, setTypeFilter] = useState("All");

  const { data: controls = [], isLoading, error, refetch } = useControls();

  const blockedCount = controls.filter(c => c.Status === "Blocked").length;

  const filtered = useMemo(() => {
    let list = controls;
    if (typeFilter !== "All") {
      if (typeFilter === "Blocked") {
        list = list.filter(c => c.Status === "Blocked");
      } else {
        list = list.filter(c => c.ControlType === typeFilter);
      }
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(c =>
        (c.ControlStatement || "").toLowerCase().includes(q) ||
        (c.ISOClause        || "").toLowerCase().includes(q) ||
        (c.OwnerRole        || "").toLowerCase().includes(q) ||
        (c.SourceDocument   || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [controls, search, typeFilter]);

  // ── Detail view ────────────────────────────────────────────────────────────
  if (selected) {
    const tc = TYPE_COLORS[selected.ControlType] || TYPE_COLORS.Directive;
    return (
      <div style={{ maxWidth: 560 }}>
        <button onClick={() => setSelected(null)}
          style={{ fontSize: 12, color: "var(--color-text-info)",
                   background: "none", border: "none", cursor: "pointer",
                   padding: 0, marginBottom: 12 }}>
          ← Back
        </button>

        <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
          <StatusBadge label={selected.ControlType} />
          <StatusBadge label={selected.Status || "Active"} />
          {selected.ISOClause && (
            <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3,
                           fontFamily: "var(--font-mono)",
                           background: "var(--color-background-secondary)",
                           color: "var(--color-text-tertiary)" }}>
              {selected.ISOClause}
            </span>
          )}
        </div>

        <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.4, marginBottom: 14 }}>
          {selected.ControlStatement || selected.Title}
        </div>

        <Field l="Control type"    v={selected.ControlType} />
        <Field l="ISO clause"      v={selected.ISOClause} />
        <Field l="Source document" v={selected.SourceDocument} />
        {selected.SourceClause && <Field l="Source clause"  v={selected.SourceClause} />}
        <Field l="Owner role"      v={selected.OwnerRole} />
        {selected.RiskImplication && <Field l="Risk if fails" v={selected.RiskImplication} color="#A32D2D" />}
        {selected.EscalationNote  && <Field l="Escalation"   v={selected.EscalationNote} />}
        <Field l="Status"          v={selected.Status || "Active"} />
        <Field l="Confidence"      v={selected.ConfidenceScore ? `${Math.round(selected.ConfidenceScore * 100)}%` : "—"} />
        <Field l="Created from"    v={selected.QueueItemId ? `Queue item ${selected.QueueItemId}` : "—"} />

        {selected.Status === "Blocked" && (
          <div style={{ marginTop: 14, padding: "10px 12px", background: "#FCEBEB",
                        borderRadius: 8, fontSize: 12, color: "#791F1F",
                        border: "1px solid #F09595" }}>
            This control is Blocked — the role "{selected.OwnerRole}" is unassigned in the Role Register. Assign someone to that role to activate this control.
          </div>
        )}
      </div>
    );
  }

  // ── List view ──────────────────────────────────────────────────────────────
  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Control register</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Every control confirmed by the compliance team from the Extraction Review queue.
          </div>
        </div>
        <div style={{ padding: "3px 10px", background: "#E1F5EE", borderRadius: 6,
                      fontSize: 11, color: "#085041", fontWeight: 600,
                      border: "0.5px solid #5DCAA5", flexShrink: 0 }}>
          {controls.length} controls
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {[
          { key: "All",       label: `All (${controls.length})` },
          { key: "Preventive", label: `Preventive (${controls.filter(c => c.ControlType === "Preventive").length})` },
          { key: "Detective",  label: `Detective (${controls.filter(c => c.ControlType === "Detective").length})` },
          { key: "Corrective", label: `Corrective (${controls.filter(c => c.ControlType === "Corrective").length})` },
          { key: "Directive",  label: `Directive (${controls.filter(c => c.ControlType === "Directive").length})` },
          { key: "Blocked",   label: `Blocked (${blockedCount})` },
        ].map(t => (
          <button key={t.key} onClick={() => setTypeFilter(t.key)}
            style={{ padding: "5px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                     fontWeight: typeFilter === t.key ? 600 : 400,
                     border: typeFilter === t.key ? `1.5px solid ${(TYPE_COLORS[t.key] || {}).bd || "#378ADD"}` : "1.5px solid #C0C0C0",
                     background: typeFilter === t.key ? (TYPE_COLORS[t.key] || {}).bg || "var(--color-background-info)" : "var(--color-background-primary)",
                     color: typeFilter === t.key ? (TYPE_COLORS[t.key] || {}).color || "var(--color-text-info)" : "var(--color-text-secondary)" }}>
            {t.label}
          </button>
        ))}
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search controls..."
          style={{ flex: 1, minWidth: 180, fontSize: 12, padding: "6px 12px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {isLoading && <LoadingState message="Loading controls..." />}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {!isLoading && !error && filtered.length === 0 && (
        <EmptyState message={
          controls.length === 0
            ? "No controls yet. Accept extraction items in the Extraction Review screen to create controls here."
            : "No controls match your search."
        } />
      )}

      {!isLoading && !error && filtered.length > 0 && (
        <>
          <div style={{ border: "1px solid #D0D0D0", borderRadius: 10, overflow: "hidden" }}>
            {filtered.map((c, i) => {
              const tc = TYPE_COLORS[c.ControlType] || TYPE_COLORS.Directive;
              const isBlocked = c.Status === "Blocked";
              return (
                <div
                  key={c.id}
                  role="button" tabIndex={0}
                  onClick={() => setSelected(c)}
                  onKeyDown={e => e.key === "Enter" && setSelected(c)}
                  style={{
                    padding: "10px 14px",
                    borderBottom: i < filtered.length - 1 ? "1px solid #E8E8E8" : "none",
                    cursor: "pointer",
                    background: isBlocked ? "#FFF8F8"
                      : i % 2 ? "var(--color-background-secondary)" : "transparent",
                    borderLeft: isBlocked ? "3px solid #F09595" : `3px solid ${tc.bd}`,
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = "var(--color-background-info)")}
                  onMouseLeave={e => (e.currentTarget.style.background = isBlocked ? "#FFF8F8"
                    : i % 2 ? "var(--color-background-secondary)" : "transparent")}
                >
                  <div style={{ display: "flex", justifyContent: "space-between",
                                alignItems: "flex-start", gap: 8 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", gap: 4, marginBottom: 4, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3,
                                       fontWeight: 500, background: tc.bg,
                                       color: tc.color, border: `0.5px solid ${tc.bd}` }}>
                          {c.ControlType || "Directive"}
                        </span>
                        {c.ISOClause && (
                          <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3,
                                         fontFamily: "var(--font-mono)",
                                         background: "var(--color-background-secondary)",
                                         color: "var(--color-text-tertiary)" }}>
                            {c.ISOClause}
                          </span>
                        )}
                        {isBlocked && <StatusBadge label="Blocked" />}
                      </div>
                      <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4, marginBottom: 3 }}>
                        {c.ControlStatement || c.Title}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
                        {c.OwnerRole || "No owner"} · {c.SourceDocument || "No source"}
                      </div>
                    </div>
                    <span style={{ fontSize: 12, color: "var(--color-text-tertiary)", flexShrink: 0 }}>›</span>
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
            {filtered.length} of {controls.length} controls
          </div>
        </>
      )}
    </>
  );
}