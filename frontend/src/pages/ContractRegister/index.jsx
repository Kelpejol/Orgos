// =============================================================================
// pages/ContractRegister/index.jsx — Contract Register
// Status calculated server-side. Features: lifecycle transitions,
// renewal warnings, add-obligation cascade, delete.
// =============================================================================

import { useState, useMemo } from "react";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import { useAlert } from "../../components/shared/AlertModal.jsx";
import ReadOnlyBanner from "../../components/shared/ReadOnlyBanner.jsx";
import {
  useContracts,
  useUpdateContractLifecycle,
  useAddContractObligation,
  useSoftDeleteContract,
} from "../../hooks/useGrc.js";
import apiClient from "../../api/grcApi.js";
import ContractForm from "./ContractForm.jsx";
import OwnerField from "../../components/shared/OwnerField.jsx";

// =============================================================================
//  Helpers
// =============================================================================

const getOwnerName = (o) => (o ? o.display_name || o.email || "—" : "—");

const STATUS_BORDER = {
  Active:          "#27AE60",
  "Expiring Soon": "#E67E22",
  Expired:         "#C0392B",
  "Under Review":  "#2980B9",
  Terminated:      "#7F8C8D",
  Superseded:      "#8E44AD",
  Withdrawn:       "#7F8C8D",
};

const STATUS_BG = {
  Active:          "rgba(39,174,96,0.05)",
  "Expiring Soon": "rgba(230,126,34,0.06)",
  Expired:         "rgba(192,57,43,0.06)",
  "Under Review":  "rgba(41,128,185,0.06)",
  Terminated:      "rgba(127,140,141,0.07)",
  Superseded:      "rgba(142,68,173,0.06)",
  Withdrawn:       "rgba(127,140,141,0.07)",
};

const TYPE_ICONS = {
  Client:     "🤝",
  Vendor:     "📦",
  Partner:    "🔗",
  Employment: "👤",
  NDA:        "🔒",
  Other:      "📄",
};

const LIFECYCLE_TRANSITIONS = {
  Active:          ["Under Review", "Terminated", "Superseded"],
  "Expiring Soon": ["Under Review", "Terminated", "Superseded"],
  "Under Review":  ["Active", "Terminated", "Superseded"],
  Expired:         ["Terminated", "Superseded"],
  Terminated:      [],
  Superseded:      [],
  Withdrawn:       [],
};

// =============================================================================
//  Skeleton
// =============================================================================

function CardSkeleton() {
  const pulse = {
    background: "linear-gradient(90deg, #e8e8e8 25%, #f5f5f5 50%, #e8e8e8 75%)",
    backgroundSize: "200% 100%",
    animation: "pulse 1.4s infinite",
    borderRadius: 6,
    height: 14,
  };
  return (
    <div style={{ borderRadius: 10, border: "1px solid #E0E0E0", padding: 16, marginBottom: 10 }}>
      <style>{`@keyframes pulse { 0%{background-position:200% 0} 100%{background-position:-200% 0} }`}</style>
      <div style={{ ...pulse, width: "55%", marginBottom: 10 }} />
      <div style={{ ...pulse, width: "40%", marginBottom: 8 }} />
      <div style={{ ...pulse, width: "25%" }} />
    </div>
  );
}

// =============================================================================
//  Add obligation modal
// =============================================================================

function AddObligationModal({ contractId, contractTitle, onSuccess, onCancel }) {
  const addObligation = useAddContractObligation();
  const [form, setForm] = useState({
    obligation_name: "",
    type:            "",
    authority:       "",
    due_date:        "",
    recurrence:      "",
    owner_id:        "",
    notes:           "",
  });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await addObligation.mutateAsync({ contractId, obligation: form });
      onSuccess();
    } catch { /* shown via mutation.error */ }
  };

  const inp = {
    width: "100%", boxSizing: "border-box", padding: "9px 12px",
    fontSize: 13, borderRadius: 8, border: "1.5px solid #C0C0C0",
    background: "var(--color-background-secondary)", color: "var(--color-text-primary)",
    marginBottom: 12,
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        background: "var(--color-background-primary)", borderRadius: 14, padding: 28,
        width: "min(540px,92vw)", boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
        maxHeight: "90vh", overflowY: "auto",
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>
          Add calendar obligation
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 18 }}>
          Linked to: <strong>{contractTitle}</strong>
        </div>

        {addObligation.error && (
          <div style={{ padding: "8px 12px", background: "rgba(192,57,43,0.1)", borderRadius: 8, fontSize: 13, color: "#C0392B", marginBottom: 12 }}>
            {addObligation.error.message}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <input style={inp} placeholder="Obligation name *" value={form.obligation_name} onChange={set("obligation_name")} required />
          <select style={inp} value={form.type} onChange={set("type")} required>
            <option value="">Type *</option>
            {["Statutory","Licensing","Certification","Regulatory"].map(t => <option key={t}>{t}</option>)}
          </select>
          <input style={inp} placeholder="Authority *" value={form.authority} onChange={set("authority")} required />
          <input style={inp} type="date" value={form.due_date} onChange={set("due_date")} required />
          <select style={inp} value={form.recurrence} onChange={set("recurrence")} required>
            <option value="">Recurrence *</option>
            {["Monthly","Quarterly","Annual","Once"].map(r => <option key={r}>{r}</option>)}
          </select>

          <OwnerField
            onResolve={(oid) => setForm((f) => ({ ...f, owner_id: oid }))}
          />

          <textarea style={{ ...inp, resize: "vertical" }} placeholder="Notes (optional)" rows={2} value={form.notes} onChange={set("notes")} />

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" onClick={onCancel}
              style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "1px solid #C0C0C0", background: "none", cursor: "pointer" }}>
              Cancel
            </button>
            <button type="submit" disabled={addObligation.isPending || !form.owner_id}
              style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none", background: "#378ADD", color: "#fff", cursor: "pointer", fontWeight: 600, opacity: addObligation.isPending ? 0.6 : 1 }}>
              {addObligation.isPending ? "Adding…" : "Add obligation"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// =============================================================================
//  Lifecycle transition modal
// =============================================================================

function LifecycleModal({ contract, targetStatus, onConfirm, onCancel, isPending }) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        background: "var(--color-background-primary)", borderRadius: 14, padding: 28,
        width: "min(420px,90vw)", boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>
          Move to "{targetStatus}"?
        </div>
        <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 20, lineHeight: 1.5 }}>
          Contract: <strong>{contract.title}</strong>
          <br />
          This will update the lifecycle status from <strong>{contract.lifecycle_status}</strong> to{" "}
          <strong>{targetStatus}</strong>.
          {targetStatus === "Terminated" && (
            <span style={{ display: "block", marginTop: 8, color: "#C0392B" }}>
              Termination is final. The contract will no longer appear in active views.
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onCancel} disabled={isPending}
            style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "1px solid #C0C0C0", background: "none", cursor: "pointer" }}>
            Cancel
          </button>
          <button onClick={onConfirm} disabled={isPending}
            style={{
              padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none",
              background: targetStatus === "Terminated" ? "#C0392B" : "#378ADD",
              color: "#fff", cursor: "pointer", fontWeight: 600, opacity: isPending ? 0.6 : 1,
            }}>
            {isPending ? "Updating…" : `Set ${targetStatus}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
//  Detail panel
// =============================================================================

function ContractDetail({ contract, onBack, onEdit, onAddObligation, onLifecycle, onDelete, isCompliance, isAdmin }) {
  const borderColor = STATUS_BORDER[contract.status] || "#C0C0C0";
  const transitions = LIFECYCLE_TRANSITIONS[contract.status] || [];

  const Row = ({ label, value, highlight, isLink }) => (
    <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
      <span style={{ fontSize: 12, color: "var(--color-text-secondary)", minWidth: 160, flexShrink: 0 }}>
        {label}
      </span>
      {isLink && value ? (
        <a href={value} target="_blank" rel="noreferrer"
          style={{ fontSize: 12, color: "#378ADD", wordBreak: "break-all" }}>
          Open in SharePoint
        </a>
      ) : (
        <span style={{ fontSize: 12, color: highlight || "var(--color-text-primary)", fontWeight: highlight ? 600 : 400, wordBreak: "break-word" }}>
          {value ?? "—"}
        </span>
      )}
    </div>
  );

  const isFinalised = contract.status === "Terminated" || contract.status === "Superseded" || contract.status === "Withdrawn";

  return (
    <div style={{ maxWidth: 600 }}>
      <button onClick={onBack}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 16 }}>
        ← Back to contracts
      </button>

      <div style={{
        borderRadius: 12, border: `2px solid ${borderColor}`,
        background: STATUS_BG[contract.status] || "transparent",
        padding: "18px 20px", marginBottom: 20,
      }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 14 }}>
          <span style={{ fontSize: 22, lineHeight: 1 }}>{TYPE_ICONS[contract.contract_type] || "📄"}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 2 }}>{contract.title}</div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
              {contract.contract_reference} · {contract.counterparty}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
            <StatusBadge label={contract.status} />
            {contract.renewal_notice_overdue && (
              <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "rgba(230,126,34,0.15)", color: "#E67E22", fontWeight: 600 }}>
                RENEWAL NOTICE OVERDUE
              </span>
            )}
          </div>
        </div>

        <Row label="Type"               value={contract.contract_type} />
        <Row label="Owner"              value={getOwnerName(contract.owner)} />
        <Row label="Start date"         value={contract.start_date || "—"} />
        <Row label="Expiry date"        value={contract.end_date || "Open-ended"}
          highlight={contract.status === "Expired" ? "#C0392B" : contract.status === "Expiring Soon" ? "#E67E22" : undefined} />
        <Row label="Renewal notice by"  value={contract.renewal_notice_date || "—"}
          highlight={contract.renewal_notice_overdue ? "#E67E22" : undefined} />
        <Row label="Review date"        value={contract.review_date || "—"} />
        <Row label="Notice period"      value={contract.notice_period_days ? `${contract.notice_period_days} days` : "—"} />
        <Row label="Auto-renewal"       value={contract.auto_renewal ? "Yes" : "No"} />
        <Row label="Lifecycle status"   value={contract.lifecycle_status} />
        <Row label="Standards"          value={(contract.applicable_standards || []).join(", ") || "—"} />
        {contract.source_document_code && (
          <Row label="Source document"  value={contract.source_document_code} />
        )}
        {contract.sharepoint_url && (
          <Row label="Contract file"    value={contract.sharepoint_url} isLink />
        )}
        {contract.notes && (
          <div style={{
            marginTop: 12, padding: "10px 14px",
            background: "rgba(0,0,0,0.04)", borderRadius: 8,
            fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5,
          }}>
            {contract.notes}
          </div>
        )}
      </div>

      {/* Actions — Compliance and Admin only */}
      {isCompliance && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
          <button onClick={onEdit}
            style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "1px solid #378ADD", background: "none", color: "#378ADD", cursor: "pointer" }}>
            Edit
          </button>
          {!isFinalised && (
            <button onClick={onAddObligation}
              style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none", background: "#2ECC71", color: "#fff", cursor: "pointer", fontWeight: 600 }}>
              + Add calendar obligation
            </button>
          )}
        </div>
      )}

      {/* Lifecycle transitions — Admin only (Terminate/Supersede are irreversible) */}
      {isAdmin && transitions.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", marginBottom: 8 }}>
            Change lifecycle status:
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {transitions.map((t) => (
              <button key={t} onClick={() => onLifecycle(t)}
                style={{
                  padding: "7px 16px", fontSize: 12, borderRadius: 8, border: "none", cursor: "pointer", fontWeight: 600,
                  background: t === "Terminated" ? "#C0392B" : t === "Superseded" ? "#8E44AD" : "#2980B9",
                  color: "#fff",
                }}>
                {t === "Terminated" ? "Terminate" : t === "Superseded" ? "Supersede" : `→ ${t}`}
              </button>
            ))}
          </div>
        </div>
      )}

      {isCompliance && contract.status !== "Withdrawn" && (
        <button onClick={() => onDelete(contract.id)}
          style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "1px solid #E74C3C", background: "none", color: "#E74C3C", cursor: "pointer" }}>
          Withdraw
        </button>
      )}
    </div>
  );
}

// =============================================================================
//  Contract card
// =============================================================================

function ContractCard({ contract, onClick }) {
  const borderColor = STATUS_BORDER[contract.status] || "#C0C0C0";
  const bg          = STATUS_BG[contract.status]     || "transparent";
  const isUrgent    = contract.status === "Expiring Soon" || contract.status === "Expired";

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      style={{
        borderRadius: 10,
        border: `1px solid ${borderColor}`,
        borderLeft: `4px solid ${borderColor}`,
        background: bg,
        padding: "14px 16px",
        marginBottom: 10,
        cursor: "pointer",
        transition: "box-shadow 0.15s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.boxShadow = "0 2px 12px rgba(0,0,0,0.09)")}
      onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "none")}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <span style={{ fontSize: 18, lineHeight: 1, marginTop: 2 }}>
          {TYPE_ICONS[contract.contract_type] || "📄"}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>
              {contract.title}
            </span>
            <StatusBadge label={contract.status} />
            {contract.renewal_notice_overdue && (
              <span style={{
                fontSize: 10, padding: "2px 6px", borderRadius: 4,
                background: "rgba(230,126,34,0.15)", color: "#E67E22", fontWeight: 600,
              }}>
                RENEW NOW
              </span>
            )}
            {contract.auto_renewal && (
              <span style={{
                fontSize: 10, padding: "2px 6px", borderRadius: 4,
                background: "rgba(41,128,185,0.12)", color: "#2980B9",
              }}>
                AUTO-RENEW
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 6 }}>
            {contract.counterparty} · {contract.contract_type}
          </div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <span style={{
              fontSize: 12,
              color: isUrgent ? (contract.status === "Expired" ? "#C0392B" : "#E67E22") : "var(--color-text-secondary)",
              fontWeight: isUrgent ? 600 : 400,
            }}>
              {contract.end_date ? `Expires: ${contract.end_date}` : "No expiry"}
            </span>
            <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              {getOwnerName(contract.owner)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
//  Main page
// =============================================================================

const TABS = ["All", "Active", "Expiring Soon", "Expired", "Under Review", "Terminated", "Superseded", "Withdrawn"];

export default function ContractRegister() {
  const [activeTab,      setActiveTab]      = useState("All");
  const [search,         setSearch]         = useState("");
  const [typeFilter,     setTypeFilter]     = useState("");
  const [selected,       setSelected]       = useState(null);
  const [showForm,       setShowForm]       = useState(false);
  const [editTarget,     setEditTarget]     = useState(null);
  const [addObligTarget, setAddObligTarget] = useState(null);
  const [lifecycleModal, setLifecycleModal] = useState(null); // { contract, targetStatus }
  const [actionMsg,      setActionMsg]      = useState("");

  const { isCompliance, isAdmin } = useCurrentUserRole();
  const { confirm: showConfirm } = useAlert();
  const { data: contracts = [], isLoading, error, refetch } = useContracts();
  const lifecycleM = useUpdateContractLifecycle();
  const deleteM    = useSoftDeleteContract();

  const flash = (msg, ok = true) => {
    setActionMsg({ text: msg, ok });
    setTimeout(() => setActionMsg(""), 4000);
  };

  const displayed = useMemo(() => {
    let list = contracts;
    if (activeTab !== "All") {
      list = list.filter((c) => c.status === activeTab);
    }
    if (typeFilter) {
      list = list.filter((c) => c.contract_type === typeFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (c) =>
          c.title?.toLowerCase().includes(q) ||
          c.counterparty?.toLowerCase().includes(q) ||
          c.contract_reference?.toLowerCase().includes(q) ||
          getOwnerName(c.owner).toLowerCase().includes(q)
      );
    }
    return list;
  }, [contracts, activeTab, typeFilter, search]);

  const counts = useMemo(() => {
    const c = { All: contracts.length };
    TABS.slice(1).forEach((t) => {
      c[t] = contracts.filter((ct) => ct.status === t).length;
    });
    return c;
  }, [contracts]);

  const handleLifecycleConfirm = () => {
    const { contract, targetStatus } = lifecycleModal;
    lifecycleM.mutate(
      { id: contract.id, lifecycleStatus: targetStatus },
      {
        onSuccess: () => {
          setLifecycleModal(null);
          if (selected?.id === contract.id) setSelected(null);
          refetch();
          flash(`Contract moved to "${targetStatus}"`);
        },
        onError: (err) => flash(err.message || "Failed to update lifecycle", false),
      }
    );
  };

  const handleDelete = async (id) => {
    const ok = await showConfirm({
      title: "Withdraw contract?",
      message: "Withdraw this contract? It will be marked as Withdrawn and kept in the register for audit history.",
      confirmLabel: "Withdraw",
      cancelLabel: "Keep contract",
    });
    if (!ok) return;
    deleteM.mutate(id, {
      onSuccess: () => { setSelected(null); refetch(); flash("Contract withdrawn"); },
      onError:   (err) => flash(err.message || "Delete failed", false),
    });
  };

  if (showForm || editTarget) {
    return (
      <ContractForm
        initial={editTarget}
        onSuccess={() => { setShowForm(false); setEditTarget(null); refetch(); }}
        onCancel={() => { setShowForm(false); setEditTarget(null); }}
      />
    );
  }

  if (selected) {
    return (
      <>
        <ContractDetail
          contract={selected}
          onBack={() => setSelected(null)}
          onEdit={() => { setEditTarget(selected); setSelected(null); }}
          onAddObligation={() => setAddObligTarget(selected)}
          onLifecycle={(targetStatus) => setLifecycleModal({ contract: selected, targetStatus })}
          onDelete={handleDelete}
          isCompliance={isCompliance}
          isAdmin={isAdmin}
        />
        {addObligTarget && (
          <AddObligationModal
            contractId={addObligTarget.id}
            contractTitle={addObligTarget.title}
            onSuccess={() => { setAddObligTarget(null); flash("Obligation added to Compliance Calendar"); }}
            onCancel={() => setAddObligTarget(null)}
          />
        )}
        {lifecycleModal && (
          <LifecycleModal
            contract={lifecycleModal.contract}
            targetStatus={lifecycleModal.targetStatus}
            onConfirm={handleLifecycleConfirm}
            onCancel={() => setLifecycleModal(null)}
            isPending={lifecycleM.isPending}
          />
        )}
        {actionMsg && (
          <div style={{
            position: "fixed", bottom: 20, right: 20, padding: "10px 16px",
            background: actionMsg.ok ? "#27AE60" : "#C0392B",
            color: "#fff", borderRadius: 8, fontSize: 13, zIndex: 2000,
          }}>
            {actionMsg.text}
          </div>
        )}
      </>
    );
  }

  return (
    <>
      {!isCompliance && (
        <ReadOnlyBanner message="You have read-only access to the Contract Register. Contact the Compliance team to add or update contracts." />
      )}
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 3 }}>Contract register</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Vendor, client, employment and partner contracts. Clauses feed the Control Register.
          </div>
        </div>
        {isCompliance && (
          <button
            onClick={() => setShowForm(true)}
            style={{
              padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none",
              background: "#378ADD", color: "#fff", cursor: "pointer", fontWeight: 600,
            }}>
            + Add contract
          </button>
        )}
      </div>

      {/* Status tabs */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
        {TABS.map((tab) => {
          const active = activeTab === tab;
          const count  = counts[tab] ?? 0;
          const dot    = STATUS_BORDER[tab];
          return (
            <button key={tab} onClick={() => setActiveTab(tab)}
              style={{
                padding: "6px 14px", fontSize: 12, borderRadius: 20, border: "none",
                cursor: "pointer", fontWeight: active ? 700 : 400,
                background: active ? "#378ADD" : "var(--color-background-secondary)",
                color: active ? "#fff" : "var(--color-text-secondary)",
                display: "flex", alignItems: "center", gap: 5,
              }}>
              {dot && <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot, display: "inline-block" }} />}
              {tab}
              {count > 0 && (
                <span style={{
                  fontSize: 10, borderRadius: 10, padding: "1px 6px",
                  background: active ? "rgba(255,255,255,0.25)" : "#E0E0E0",
                  color: active ? "#fff" : "#555", fontWeight: 600, minWidth: 16, textAlign: "center",
                }}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search contracts…"
          style={{
            flex: 1, minWidth: 200, fontSize: 13, padding: "9px 14px",
            borderRadius: 8, border: "1.5px solid #C0C0C0",
            background: "var(--color-background-primary)",
            color: "var(--color-text-primary)", outline: "none",
          }}
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          style={{
            fontSize: 13, padding: "9px 14px", borderRadius: 8,
            border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
            color: "var(--color-text-secondary)", cursor: "pointer",
          }}>
          <option value="">All types</option>
          {["Client","Vendor","Partner","Employment","NDA","Other"].map(t => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* Flash message */}
      {actionMsg && (
        <div style={{
          padding: "10px 16px", marginBottom: 12,
          background: actionMsg.ok ? "rgba(39,174,96,0.1)" : "rgba(192,57,43,0.1)",
          border: `1px solid ${actionMsg.ok ? "rgba(39,174,96,0.3)" : "rgba(192,57,43,0.3)"}`,
          borderRadius: 8, fontSize: 13,
          color: actionMsg.ok ? "#27AE60" : "#C0392B",
        }}>
          {actionMsg.text}
        </div>
      )}

      {/* Content */}
      {isLoading && (
        <><CardSkeleton /><CardSkeleton /><CardSkeleton /></>
      )}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {!isLoading && !error && displayed.length === 0 && (
        <EmptyState
          message={
            search || typeFilter || activeTab !== "All"
              ? "No contracts match your filters."
              : "No contracts added yet."
          }
        />
      )}
      {!isLoading && !error && displayed.length > 0 && (
        <>
          {displayed.map((ct) => (
            <ContractCard key={ct.id} contract={ct} onClick={() => setSelected(ct)} />
          ))}
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 4 }}>
            {displayed.length} contract{displayed.length !== 1 ? "s" : ""}
            {activeTab !== "All" ? ` · ${activeTab}` : ""}
          </div>
        </>
      )}

      {/* Modals */}
      {lifecycleModal && (
        <LifecycleModal
          contract={lifecycleModal.contract}
          targetStatus={lifecycleModal.targetStatus}
          onConfirm={handleLifecycleConfirm}
          onCancel={() => setLifecycleModal(null)}
          isPending={lifecycleM.isPending}
        />
      )}
    </>
  );
}
