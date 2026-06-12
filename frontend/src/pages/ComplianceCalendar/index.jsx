// =============================================================================
// pages/ComplianceCalendar/index.jsx — Compliance Calendar
// Status calculated server-side on every read — never manually set.
// Features: urgency-coloured cards, filter tabs, complete + escalate actions.
// =============================================================================

import { useState, useMemo } from "react";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import {
  useObligations,
  useCompleteObligation,
  useEscalateObligation,
  useSoftDeleteObligation,
} from "../../hooks/useGrc.js";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import { useAlert } from "../../components/shared/AlertModal.jsx";
import ReadOnlyBanner from "../../components/shared/ReadOnlyBanner.jsx";
import CalendarForm from "./CalendarForm.jsx";

// =============================================================================
//  Helpers
// =============================================================================

const getOwnerName = (o) => (o ? o.display_name || o.email || "—" : "—");

const STATUS_ORDER = { Overdue: 0, "Due Soon": 1, Upcoming: 2, Completed: 3 };

const STATUS_BORDER = {
  Overdue:   "#C0392B",
  "Due Soon": "#E67E22",
  Upcoming:  "#27AE60",
  Completed: "#95A5A6",
};

const STATUS_BG = {
  Overdue:   "rgba(192,57,43,0.06)",
  "Due Soon": "rgba(230,126,34,0.06)",
  Upcoming:  "rgba(39,174,96,0.06)",
  Completed: "rgba(149,165,166,0.08)",
};

const TYPE_ICONS = {
  Statutory:     "⚖️",
  Licensing:     "📋",
  Certification: "🎓",
  Regulatory:    "🏛",
};

const RECURRENCE_LABELS = {
  Monthly:   "Every month",
  Quarterly: "Every quarter",
  Annual:    "Every year",
  Once:      "One-time",
};

// =============================================================================
//  Skeleton loader
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
      <div style={{ ...pulse, width: "60%", marginBottom: 10 }} />
      <div style={{ ...pulse, width: "40%", marginBottom: 8 }} />
      <div style={{ ...pulse, width: "30%" }} />
    </div>
  );
}

// =============================================================================
//  Complete modal
// =============================================================================

function CompleteModal({ obligation, onConfirm, onCancel, isPending }) {
  const [notes, setNotes] = useState("");
  const isRecurring = obligation.recurrence !== "Once";

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        background: "var(--color-background-primary)", borderRadius: 14, padding: 28,
        width: "min(480px,90vw)", boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>
          Mark as completed
        </div>
        <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 16, lineHeight: 1.5 }}>
          <strong>{obligation.obligation_name}</strong>
          {isRecurring ? (
            <>
              <br />
              This is a <strong>{obligation.recurrence.toLowerCase()}</strong> obligation.
              The due date will automatically roll forward to the next cycle.
            </>
          ) : (
            <>
              <br />
              This is a one-time obligation. It will be marked as <strong>Completed</strong>.
            </>
          )}
        </div>
        <label style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>
          Completion notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Reference number, confirmation, or evidence link..."
          rows={3}
          style={{
            width: "100%", boxSizing: "border-box", padding: "10px 12px", fontSize: 13,
            border: "1.5px solid #C0C0C0", borderRadius: 8, resize: "vertical",
            background: "var(--color-background-secondary)", color: "var(--color-text-primary)",
            marginBottom: 18,
          }}
        />
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onCancel} disabled={isPending}
            style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "1px solid #C0C0C0", background: "none", cursor: "pointer", color: "var(--color-text-primary)" }}>
            Cancel
          </button>
          <button onClick={() => onConfirm(notes)} disabled={isPending}
            style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none", background: "#27AE60", color: "#fff", cursor: "pointer", fontWeight: 600, opacity: isPending ? 0.6 : 1 }}>
            {isPending ? "Saving…" : isRecurring ? "Complete & roll forward" : "Mark completed"}
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
//  Escalate modal
// =============================================================================

function EscalateModal({ obligation, onConfirm, onCancel, isPending }) {
  const [notes, setNotes] = useState("");

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        background: "var(--color-background-primary)", borderRadius: 14, padding: 28,
        width: "min(480px,90vw)", boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6, color: "#C0392B" }}>
          Escalate to Gap Analysis
        </div>
        <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 16, lineHeight: 1.5 }}>
          This will create a <strong>Gap Analysis finding</strong> for the overdue{" "}
          <strong>{obligation.obligation_name}</strong> obligation.
          Severity will be{" "}
          <strong>
            {obligation.type === "Statutory" || obligation.type === "Regulatory" ? "Critical" : "Major"}
          </strong>.
          <br /><br />
          
        </div>
        <label style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>
          Escalation notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Impact, root cause, or remediation context..."
          rows={3}
          style={{
            width: "100%", boxSizing: "border-box", padding: "10px 12px", fontSize: 13,
            border: "1.5px solid #C0C0C0", borderRadius: 8, resize: "vertical",
            background: "var(--color-background-secondary)", color: "var(--color-text-primary)",
            marginBottom: 18,
          }}
        />
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onCancel} disabled={isPending}
            style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "1px solid #C0C0C0", background: "none", cursor: "pointer", color: "var(--color-text-primary)" }}>
            Cancel
          </button>
          <button onClick={() => onConfirm(notes)} disabled={isPending}
            style={{ padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none", background: "#C0392B", color: "#fff", cursor: "pointer", fontWeight: 600, opacity: isPending ? 0.6 : 1 }}>
            {isPending ? "Escalating…" : "Escalate to Gap Analysis"}
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
//  Detail panel
// =============================================================================

function ObligationDetail({ obligation, onBack, onEdit, onComplete, onEscalate, onDelete, isCompliance }) {
  const borderColor = STATUS_BORDER[obligation.status] || "#C0C0C0";
  const isOverdue   = obligation.status === "Overdue";
  const isCompleted = obligation.status === "Completed";

  const Row = ({ label, value, highlight }) => (
    <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
      <span style={{ fontSize: 12, color: "var(--color-text-secondary)", minWidth: 140, flexShrink: 0 }}>
        {label}
      </span>
      <span style={{ fontSize: 12, color: highlight || "var(--color-text-primary)", fontWeight: highlight ? 600 : 400 }}>
        {value ?? "—"}
      </span>
    </div>
  );

  return (
    <div style={{ maxWidth: 560 }}>
      <button onClick={onBack}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 16 }}>
        ← Back to calendar
      </button>

      <div style={{
        borderRadius: 12, border: `2px solid ${borderColor}`,
        background: STATUS_BG[obligation.status] || "transparent",
        padding: "18px 20px", marginBottom: 20,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <span style={{ fontSize: 20 }}>{TYPE_ICONS[obligation.type] || "📌"}</span>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700 }}>{obligation.obligation_name}</div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 2 }}>
              {obligation.authority} · {obligation.type}
            </div>
          </div>
          <StatusBadge label={obligation.status} style={{ marginLeft: "auto" }} />
        </div>

        <Row label="Due date"
          value={obligation.due_date}
          highlight={isOverdue ? "#C0392B" : undefined} />
        <Row label="Recurrence" value={RECURRENCE_LABELS[obligation.recurrence] || obligation.recurrence} />
        <Row label="Owner"      value={getOwnerName(obligation.owner)} />

        {obligation.source_document_code && (
          <Row label="Source document" value={obligation.source_document_code} />
        )}
        {obligation.linked_contract_id && (
          <Row label="Linked contract" value={`Contract ID: ${obligation.linked_contract_id}`} />
        )}
        {obligation.notes && (
          <div style={{
            marginTop: 12, padding: "10px 14px", background: "rgba(0,0,0,0.04)",
            borderRadius: 8, fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.5,
          }}>
            {obligation.notes}
          </div>
        )}

        {isCompleted && (
          <div style={{
            marginTop: 12, padding: "10px 14px", background: "rgba(39,174,96,0.1)",
            borderRadius: 8, borderLeft: "3px solid #27AE60",
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#27AE60", marginBottom: 4 }}>
              Completed {obligation.completed_date}
              {obligation.completed_by_name && ` · ${obligation.completed_by_name}`}
            </div>
            {obligation.completion_notes && (
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                {obligation.completion_notes}
              </div>
            )}
          </div>
        )}

        {obligation.escalated_gap_id && (
          <div style={{
            marginTop: 12, padding: "10px 14px", background: "rgba(192,57,43,0.08)",
            borderRadius: 8, borderLeft: "3px solid #C0392B", fontSize: 12,
          }}>
            Escalated to Gap Analysis: <strong>{obligation.escalated_gap_id}</strong>
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {isCompliance && (
          <button onClick={() => onEdit(obligation)}
            style={{
              padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "1px solid #378ADD",
              background: "none", color: "#378ADD", cursor: "pointer", fontWeight: 600,
            }}>
            Edit
          </button>
        )}
        {isCompliance && !isCompleted && (
          <button onClick={() => onComplete(obligation)}
            style={{
              padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none",
              background: "#27AE60", color: "#fff", cursor: "pointer", fontWeight: 600,
            }}>
            ✓ Mark completed
          </button>
        )}
        {isCompliance && isOverdue && !obligation.escalated_gap_id && (
          <button onClick={() => onEscalate(obligation)}
            style={{
              padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none",
              background: "#C0392B", color: "#fff", cursor: "pointer", fontWeight: 600,
            }}>
            ↑ Escalate to Gap Analysis
          </button>
        )}
        {obligation.escalated_gap_id && isOverdue && (
          <div style={{ fontSize: 12, color: "#C0392B", display: "flex", alignItems: "center" }}>
            Already escalated · {obligation.escalated_gap_id}
          </div>
        )}
        {isCompliance && (
          <button onClick={() => onDelete(obligation.id)}
            style={{
              padding: "9px 18px", fontSize: 13, borderRadius: 8,
              border: "1px solid #E74C3C", background: "none",
              color: "#E74C3C", cursor: "pointer", marginLeft: "auto",
            }}>
            Withdraw
          </button>
        )}
      </div>
    </div>
  );
}

// =============================================================================
//  Obligation card
// =============================================================================

function ObligationCard({ obligation, onClick, onComplete, onEscalate, isCompliance }) {
  const borderColor = STATUS_BORDER[obligation.status] || "#C0C0C0";
  const bg          = STATUS_BG[obligation.status]     || "transparent";
  const isOverdue   = obligation.status === "Overdue";
  const isCompleted = obligation.status === "Completed";

  const handleAction = (e, fn) => { e.stopPropagation(); fn(obligation); };

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
        <span style={{ fontSize: 18, lineHeight: 1, marginTop: 1 }}>
          {TYPE_ICONS[obligation.type] || "📌"}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>
              {obligation.obligation_name}
            </span>
            <StatusBadge label={obligation.status} />
            {obligation.escalated_gap_id && (
              <span style={{
                fontSize: 10, padding: "2px 6px", borderRadius: 4,
                background: "rgba(192,57,43,0.12)", color: "#C0392B", fontWeight: 600,
              }}>
                GAP
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 8 }}>
            {obligation.authority} · {obligation.type} · {RECURRENCE_LABELS[obligation.recurrence] || obligation.recurrence}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: isOverdue ? "#C0392B" : "var(--color-text-secondary)", fontWeight: isOverdue ? 600 : 400 }}>
              Due: {obligation.due_date}
            </span>
            <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              {getOwnerName(obligation.owner)}
            </span>
            {isCompleted && obligation.completed_date && (
              <span style={{ fontSize: 11, color: "#27AE60" }}>
                ✓ Completed {obligation.completed_date}
              </span>
            )}
          </div>
        </div>
        {isCompliance && (
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
            {!isCompleted && (
              <button
                onClick={(e) => handleAction(e, onComplete)}
                title="Mark completed"
                style={{
                  padding: "5px 10px", fontSize: 11, borderRadius: 6, border: "1px solid #27AE60",
                  background: "none", color: "#27AE60", cursor: "pointer", fontWeight: 600,
                }}>
                ✓
              </button>
            )}
            {isOverdue && !obligation.escalated_gap_id && (
              <button
                onClick={(e) => handleAction(e, onEscalate)}
                title="Escalate to Gap Analysis"
                style={{
                  padding: "5px 10px", fontSize: 11, borderRadius: 6, border: "1px solid #C0392B",
                  background: "none", color: "#C0392B", cursor: "pointer", fontWeight: 600,
                }}>
                ↑
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
//  Main page
// =============================================================================

const TABS = ["All", "Overdue", "Due Soon", "Upcoming", "Completed"];

export default function ComplianceCalendar() {
  const [activeTab,       setActiveTab]       = useState("All");
  const [search,          setSearch]          = useState("");
  const [typeFilter,      setTypeFilter]      = useState("");
  const [selected,        setSelected]        = useState(null);
  const [showForm,        setShowForm]        = useState(false);
  const [editTarget,      setEditTarget]      = useState(null);
  const [completeTarget,  setCompleteTarget]  = useState(null);
  const [escalateTarget,  setEscalateTarget]  = useState(null);
  const [actionError,     setActionError]     = useState("");

  const { isCompliance } = useCurrentUserRole();
  const { confirm: showConfirm } = useAlert();
  const { data: obligations = [], isLoading, error, refetch } = useObligations();
  const completeM  = useCompleteObligation();
  const escalateM  = useEscalateObligation();
  const deleteM    = useSoftDeleteObligation();

  const displayed = useMemo(() => {
    let list = obligations;
    if (activeTab !== "All") {
      list = list.filter((o) => o.status === activeTab);
    }
    if (typeFilter) {
      list = list.filter((o) => o.type === typeFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (o) =>
          o.obligation_name?.toLowerCase().includes(q) ||
          o.authority?.toLowerCase().includes(q) ||
          getOwnerName(o.owner).toLowerCase().includes(q)
      );
    }
    return [...list].sort(
      (a, b) => (STATUS_ORDER[a.status] ?? 4) - (STATUS_ORDER[b.status] ?? 4)
    );
  }, [obligations, activeTab, typeFilter, search]);

  const counts = useMemo(() => {
    const c = { All: obligations.length };
    TABS.slice(1).forEach((t) => {
      c[t] = obligations.filter((o) => o.status === t).length;
    });
    return c;
  }, [obligations]);

  const handleComplete = (notes) => {
    setActionError("");
    completeM.mutate(
      { id: completeTarget.id, completion_notes: notes || undefined },
      {
        onSuccess: () => {
          setCompleteTarget(null);
          if (selected?.id === completeTarget.id) setSelected(null);
          refetch();
        },
        onError: (err) => setActionError(err.message || "Failed to mark complete"),
      }
    );
  };

  const handleEscalate = (notes) => {
    setActionError("");
    escalateM.mutate(
      { id: escalateTarget.id, escalation_notes: notes || undefined },
      {
        onSuccess: (data) => {
          setEscalateTarget(null);
          if (selected?.id === escalateTarget.id) setSelected(null);
          refetch();
          setActionError(`Escalated: ${data.gap_id || "gap created"}`);
          setTimeout(() => setActionError(""), 4000);
        },
        onError: (err) => setActionError(err.message || "Escalation failed"),
      }
    );
  };

  const handleDelete = async (id) => {
    const ok = await showConfirm({
      title: "Withdraw obligation?",
      message: "Withdraw this obligation? It will be marked as Withdrawn and retained in SharePoint.",
      confirmLabel: "Withdraw",
      cancelLabel: "Keep obligation",
    });
    if (!ok) return;
    deleteM.mutate(id, {
      onSuccess: () => { setSelected(null); refetch(); },
      onError:   (err) => setActionError(err.message || "Delete failed"),
    });
  };

  if (showForm || editTarget) {
    return (
      <CalendarForm
        initial={editTarget}
        onSuccess={() => { setShowForm(false); setEditTarget(null); refetch(); }}
        onCancel={() => { setShowForm(false); setEditTarget(null); }}
      />
    );
  }

  if (selected) {
    return (
      <>
        <ObligationDetail
          obligation={selected}
          onBack={() => setSelected(null)}
          onEdit={(ob) => { setEditTarget(ob); setSelected(null); }}
          onComplete={(ob) => setCompleteTarget(ob)}
          onEscalate={(ob) => setEscalateTarget(ob)}
          onDelete={handleDelete}
          isCompliance={isCompliance}
        />
        {completeTarget && (
          <CompleteModal
            obligation={completeTarget}
            onConfirm={handleComplete}
            onCancel={() => setCompleteTarget(null)}
            isPending={completeM.isPending}
          />
        )}
        {escalateTarget && (
          <EscalateModal
            obligation={escalateTarget}
            onConfirm={handleEscalate}
            onCancel={() => setEscalateTarget(null)}
            isPending={escalateM.isPending}
          />
        )}
        {actionError && (
          <div style={{
            position: "fixed", bottom: 20, right: 20, padding: "10px 16px",
            background: actionError.startsWith("Escalated") ? "#27AE60" : "#C0392B",
            color: "#fff", borderRadius: 8, fontSize: 13, zIndex: 2000,
          }}>
            {actionError}
          </div>
        )}
      </>
    );
  }

  return (
    <>
      {!isCompliance && (
        <ReadOnlyBanner message="You have read-only access to the Compliance Calendar. Contact the Compliance team to add or update obligations." />
      )}
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 3 }}>Compliance calendar</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Statutory, licensing, certification and regulatory obligations.
          </div>
        </div>
        {isCompliance && (
          <button
            onClick={() => setShowForm(true)}
            style={{
              padding: "9px 18px", fontSize: 13, borderRadius: 8, border: "none",
              background: "#378ADD", color: "#fff", cursor: "pointer", fontWeight: 600,
            }}>
            + Add obligation
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
          placeholder="Search obligations..."
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
          <option value="Statutory">Statutory</option>
          <option value="Licensing">Licensing</option>
          <option value="Certification">Certification</option>
          <option value="Regulatory">Regulatory</option>
        </select>
      </div>

      {/* Error banner */}
      {actionError && !actionError.startsWith("Escalated") && (
        <div style={{
          padding: "10px 16px", marginBottom: 12, background: "rgba(192,57,43,0.1)",
          border: "1px solid rgba(192,57,43,0.3)", borderRadius: 8,
          fontSize: 13, color: "#C0392B",
        }}>
          {actionError}
        </div>
      )}
      {actionError.startsWith("Escalated") && (
        <div style={{
          padding: "10px 16px", marginBottom: 12, background: "rgba(39,174,96,0.1)",
          border: "1px solid rgba(39,174,96,0.3)", borderRadius: 8,
          fontSize: 13, color: "#27AE60",
        }}>
          {actionError}
        </div>
      )}

      {/* Content */}
      {isLoading && (
        <>
          <CardSkeleton /><CardSkeleton /><CardSkeleton />
        </>
      )}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {!isLoading && !error && displayed.length === 0 && (
        <EmptyState
          message={
            search || typeFilter || activeTab !== "All"
              ? "No obligations match your filters."
              : "No compliance obligations added yet."
          }
        />
      )}
      {!isLoading && !error && displayed.length > 0 && (
        <>
          {displayed.map((ob) => (
            <ObligationCard
              key={ob.id}
              obligation={ob}
              onClick={() => setSelected(ob)}
              onComplete={(o) => setCompleteTarget(o)}
              onEscalate={(o) => setEscalateTarget(o)}
              isCompliance={isCompliance}
            />
          ))}
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 4 }}>
            {displayed.length} obligation{displayed.length !== 1 ? "s" : ""}
            {activeTab !== "All" ? ` · ${activeTab}` : ""}
          </div>
        </>
      )}

      {/* Modals */}
      {completeTarget && (
        <CompleteModal
          obligation={completeTarget}
          onConfirm={handleComplete}
          onCancel={() => setCompleteTarget(null)}
          isPending={completeM.isPending}
        />
      )}
      {escalateTarget && (
        <EscalateModal
          obligation={escalateTarget}
          onConfirm={handleEscalate}
          onCancel={() => setEscalateTarget(null)}
          isPending={escalateM.isPending}
        />
      )}
    </>
  );
}
