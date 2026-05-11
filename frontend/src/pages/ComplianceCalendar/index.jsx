// =============================================================================
// pages/ComplianceCalendar/index.jsx — Compliance Calendar, wired to API
// Status is calculated server-side on every read. Never manually set.
// =============================================================================

import { useState, useMemo } from "react";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { TableSkeleton, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import { useObligations } from "../../hooks/useGrc.js";
import CalendarForm from "./CalendarForm.jsx";

const COLS = [
  { key: "obligation_name", label: "Obligation" },
  { key: "type",            label: "Type" },
  { key: "authority",       label: "Authority" },
  { key: "due_date",        label: "Due" },
  { key: "recurrence",      label: "Recurrence" },
  { key: "owner",           label: "Owner" },
  { key: "status",          label: "Status" },
];

const getOwnerName = (o) => (o ? o.display_name || o.email || "—" : "—");

export default function ComplianceCalendar() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [showForm, setShowForm] = useState(false);

  const { data: obligations = [], isLoading, error, refetch } = useObligations();

  const filtered = useMemo(() => {
    if (!search.trim()) return obligations;
    const q = search.toLowerCase();
    return obligations.filter(
      (o) =>
        o.obligation_name?.toLowerCase().includes(q) ||
        o.authority?.toLowerCase().includes(q) ||
        getOwnerName(o.owner).toLowerCase().includes(q)
    );
  }, [obligations, search]);

  // Sort by urgency: Overdue first, then Due Soon, then Upcoming
  const urgencyOrder = { Overdue: 0, "Due Soon": 1, "Due soon": 1, Upcoming: 2, Completed: 3 };
  const sorted = [...filtered].sort((a, b) => (urgencyOrder[a.status] ?? 4) - (urgencyOrder[b.status] ?? 4));

  if (selected) {
    return (
      <div style={{ maxWidth: 480 }}>
        <button onClick={() => setSelected(null)}
          style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}>
          ← Back
        </button>
        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          <StatusBadge label={selected.status} />
          <StatusBadge label={selected.type} />
        </div>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>{selected.obligation_name}</div>
        <Field l="Authority"   v={selected.authority} />
        <Field l="Due date"    v={selected.due_date} color={selected.status === "Overdue" ? "#A32D2D" : undefined} />
        <Field l="Recurrence"  v={selected.recurrence} />
        <Field l="Owner"       v={getOwnerName(selected.owner)} />
        <Field l="Status"      v={<StatusBadge label={selected.status} />} />
        <div style={{ padding: "10px 14px", background: "var(--color-background-secondary)", borderRadius: 8, marginTop: 14, fontSize: 12, color: "var(--color-text-secondary)" }}>
          Status is calculated automatically from the due date. It cannot be manually set.
        </div>
      </div>
    );
  }

  if (showForm) {
    return <CalendarForm onSuccess={() => { setShowForm(false); refetch(); }} onCancel={() => setShowForm(false)} />;
  }

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Compliance calendar</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Statutory, licensing, certification and regulatory obligations.
          </div>
        </div>
        <button onClick={() => setShowForm(true)}
          style={{ padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "none", background: "#378ADD", color: "#fff", cursor: "pointer", fontWeight: 500 }}>
          + Add obligation
        </button>
      </div>

      <input type="text" value={search} onChange={(e) => setSearch(e.target.value)}
        placeholder="Search obligations..."
        style={{ width: "100%", fontSize: 13, padding: "10px 14px", borderRadius: 8, border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)", color: "var(--color-text-primary)", marginBottom: 10, boxSizing: "border-box", outline: "none" }} />

      {isLoading && <TableSkeleton rows={7} cols={COLS.length} />}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {!isLoading && !error && sorted.length === 0 && (
        <EmptyState message={search ? "No obligations match your search." : "No obligations added yet."} />
      )}

      {!isLoading && !error && sorted.length > 0 && (
        <>
          <div style={{ border: "1px solid #D0D0D0", borderRadius: 10, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "var(--color-background-secondary)" }}>
                  {COLS.map((c) => (
                    <th key={c.key} style={{ padding: "7px 8px", textAlign: "left", fontWeight: 500, fontSize: 11, color: "var(--color-text-secondary)", whiteSpace: "nowrap" }}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((ob, i) => (
                  <tr key={ob.id} onClick={() => setSelected(ob)} role="button" tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && setSelected(ob)}
                    style={{ borderBottom: "1px solid #E8E8E8", cursor: "pointer", background: i % 2 ? "var(--color-background-secondary)" : "transparent" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-background-info)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = i % 2 ? "var(--color-background-secondary)" : "transparent")}>
                    {COLS.map((col) => {
                      const v = col.key === "owner" ? getOwnerName(ob.owner) : ob[col.key];
                      const isSt = col.key === "status" || col.key === "type";
                      return (
                        <td key={col.key} style={{ padding: "6px 8px", whiteSpace: "nowrap" }}>
                          {isSt && v ? <StatusBadge label={v} /> : (v ?? "—")}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
            {sorted.length} obligations
          </div>
        </>
      )}
    </>
  );
}
