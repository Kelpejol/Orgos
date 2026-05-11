// =============================================================================
// pages/ContractRegister/index.jsx — Contract Register, wired to API
// =============================================================================

import { useState, useMemo } from "react";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { TableSkeleton, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import { useContracts } from "../../hooks/useGrc.js";
import ContractForm from "./ContractForm.jsx";

const COLS = [
  { key: "title",            label: "Title" },
  { key: "counterparty",     label: "Counterparty" },
  { key: "contract_type",    label: "Type" },
  { key: "end_date",         label: "Expiry" },
  { key: "owner",            label: "Owner" },
  { key: "status",           label: "Status" },
];

const getOwnerName = (o) => (o ? o.display_name || o.email || "—" : "—");

export default function ContractRegister() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [showForm, setShowForm] = useState(false);

  const { data: contracts = [], isLoading, error, refetch } = useContracts();

  const filtered = useMemo(() => {
    if (!search.trim()) return contracts;
    const q = search.toLowerCase();
    return contracts.filter(
      (c) =>
        c.title?.toLowerCase().includes(q) ||
        c.counterparty?.toLowerCase().includes(q) ||
        c.contract_type?.toLowerCase().includes(q) ||
        getOwnerName(c.owner).toLowerCase().includes(q)
    );
  }, [contracts, search]);

  if (selected) {
    return (
      <div style={{ maxWidth: 480 }}>
        <button onClick={() => setSelected(null)}
          style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}>
          ← Back
        </button>
        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          <StatusBadge label={selected.status} />
          <StatusBadge label={selected.contract_type} />
        </div>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>{selected.title}</div>
        <Field l="Reference"    v={selected.contract_reference} />
        <Field l="Counterparty" v={selected.counterparty} />
        <Field l="Type"         v={selected.contract_type} />
        <Field l="Owner"        v={getOwnerName(selected.owner)} />
        <Field l="Start date"   v={selected.start_date || "—"} />
        <Field l="Expiry"       v={selected.end_date || "—"}
          color={selected.status === "Expired" ? "#A32D2D" : selected.status === "Expiring Soon" ? "#854F0B" : undefined} />
        <Field l="Review date"  v={selected.review_date || "—"} />
        <Field l="Standards"    v={(selected.applicable_standards || []).join(", ") || "—"} />
        <Field l="Status"       v={<StatusBadge label={selected.status} />} />
        <div style={{ padding: "10px 14px", background: "var(--color-background-secondary)", borderRadius: 8, marginTop: 14, fontSize: 12, color: "var(--color-text-secondary)" }}>
          Contract clauses feed into the Control Register. Source field = "Contract".
        </div>
      </div>
    );
  }

  if (showForm) {
    return <ContractForm onSuccess={() => { setShowForm(false); refetch(); }} onCancel={() => setShowForm(false)} />;
  }

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Contract register</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Parent contracts. Clauses feed Control Register.
          </div>
        </div>
        <button onClick={() => setShowForm(true)}
          style={{ padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "none", background: "#378ADD", color: "#fff", cursor: "pointer", fontWeight: 500 }}>
          + Add contract
        </button>
      </div>

      <input type="text" value={search} onChange={(e) => setSearch(e.target.value)}
        placeholder="Search contracts..."
        style={{ width: "100%", fontSize: 13, padding: "10px 14px", borderRadius: 8, border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)", color: "var(--color-text-primary)", marginBottom: 10, boxSizing: "border-box", outline: "none" }} />

      {isLoading && <TableSkeleton rows={5} cols={COLS.length} />}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {!isLoading && !error && filtered.length === 0 && (
        <EmptyState message={search ? "No contracts match your search." : "No contracts added yet."} />
      )}

      {!isLoading && !error && filtered.length > 0 && (
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
                {filtered.map((ct, i) => (
                  <tr key={ct.id} onClick={() => setSelected(ct)} role="button" tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && setSelected(ct)}
                    style={{ borderBottom: "1px solid #E8E8E8", cursor: "pointer", background: i % 2 ? "var(--color-background-secondary)" : "transparent" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-background-info)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = i % 2 ? "var(--color-background-secondary)" : "transparent")}>
                    {COLS.map((col) => {
                      const v = col.key === "owner" ? getOwnerName(ct.owner) : ct[col.key];
                      const isSt = col.key === "status" || col.key === "contract_type";
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
            {filtered.length} contracts
          </div>
        </>
      )}
    </>
  );
}
