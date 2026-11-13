// =============================================================================
// pages/WorkHub/index.jsx — Dashboard (RBAC-scoped urgency view)
// =============================================================================

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { LoadingState } from "../../components/shared/LoadingState.jsx";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import apiClient, { complianceApi, contractsApi } from "../../api/grcApi.js";
import { OVERDUE, controlLine, dueForMe, dueState, dueText } from "../../components/shared/recordDue.js";

// =============================================================================
//  Data hooks
// =============================================================================

const usePendingQueue = () =>
  useQuery({
    queryKey: ["queue", "pending-wh"],
    queryFn: () =>
      apiClient.get("/api/v1/queue/items", { params: { review_status: "Pending Review" } }).then((r) => r.data),
    staleTime: 60_000,
  });

const useControls = (enabled) =>
  useQuery({
    queryKey: ["controls", "wh"],
    queryFn: () => apiClient.get("/api/v1/controls").then((r) => r.data),
    staleTime: 60_000,
    enabled,
  });

const useLifecycleDocs = () =>
  useQuery({
    queryKey: ["lifecycle", "all"],
    queryFn: () => apiClient.get("/api/v1/lifecycle/documents").then((r) => r.data),
    staleTime: 60_000,
  });

// "Overdue" is never stored: a record's state is computed (Missing, Late, Stale, Rejected need attention).
const ATTENTION = new Set(["Missing", "Late", "Stale", "Rejected"]);
const needsAttention = (r) => r.IsObligation
  ? ATTENTION.has(r.State)
  : r.Status === "Rejected" || (["Pending", "Submitted"].includes(r.Status) && r.DueDate && r.DueDate.slice(0, 10) < new Date().toISOString().slice(0, 10));

const useRecords = () =>
  useQuery({
    queryKey: ["records", "wh"],
    queryFn: () => apiClient.get("/api/v1/records").then((r) => r.data || []),
    staleTime: 60_000,
  });

// Open one record in the Record Tracker, ready to submit.
const openRecord = (id) =>
  window.dispatchEvent(new CustomEvent("orgos:navigate", { detail: { to: "records", recordId: id } }));

const useOverdueObligations = () =>
  useQuery({
    queryKey: ["obligations", "overdue"],
    queryFn: () => complianceApi.listOverdue(),
    staleTime: 60_000,
  });

const useExpiringContracts = () =>
  useQuery({
    queryKey: ["contracts", "expiring"],
    queryFn: () => contractsApi.listExpiring(),
    staleTime: 60_000,
  });

const useOpenGaps = () =>
  useQuery({
    queryKey: ["gaps", "open"],
    queryFn: () =>
      apiClient.get("/api/v1/gap-analysis", { params: { status_filter: "Open" } }).then((r) => r.data),
    staleTime: 60_000,
  });

// =============================================================================
//  Components
// =============================================================================

const UrgencyCard = ({ color, bg, bd, icon, title, count, message, action, onAction }) => (
  <div
    style={{
      border: `1px solid ${bd}`,
      borderLeft: `4px solid ${color}`,
      borderRadius: 12,
      background: bg,
      padding: "14px 16px",
      display: "flex",
      justifyContent: "space-between",
      alignItems: "flex-start",
      gap: 12,
    }}
  >
    <div style={{ flex: 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 15 }}>{icon}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color }}>
          <span style={{ fontSize: 18, fontWeight: 700, marginRight: 5, letterSpacing: "-1px" }}>
            {count}
          </span>
          {title}
        </span>
      </div>
      <div style={{ fontSize: 12, color, opacity: 0.8, lineHeight: 1.5 }}>{message}</div>
    </div>
    {action && (
      <button
        onClick={onAction}
        style={{
          padding: "7px 14px",
          fontSize: 11,
          borderRadius: 8,
          border: `1px solid ${color}`,
          background: "transparent",
          color,
          cursor: "pointer",
          fontWeight: 500,
          whiteSpace: "nowrap",
          flexShrink: 0,
        }}
      >
        {action}
      </button>
    )}
  </div>
);

const Stat = ({ label, value, color }) => (
  <div
    style={{
      padding: "14px 16px",
      borderRadius: 10,
      background: "var(--color-background-secondary)",
      border: "1px solid var(--color-border-tertiary)",
    }}
  >
    <div style={{ fontSize: 26, fontWeight: 700, color: color || "var(--color-text-primary)", letterSpacing: "-1px", marginBottom: 2 }}>
      {value ?? "—"}
    </div>
    <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>{label}</div>
  </div>
);

// "Due for me": the records I must produce, overdue first. Each says which control it proves,
// in words, and opens straight on its submit form.
const DueForMe = ({ records, onSeeAll }) => {
  const shown = records.slice(0, 6);
  return (
    <div style={{ marginBottom: 22 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          Due for me {records.length > 0 && <span style={{ color: "var(--color-text-tertiary)", fontWeight: 400 }}>({records.length})</span>}
        </div>
        {records.length > 0 && (
          <button onClick={onSeeAll} style={{ background: "none", border: "none", padding: 0, fontSize: 12,
                                              color: "var(--color-text-info)", cursor: "pointer" }}>
            See all in Record tracker →
          </button>
        )}
      </div>
      {records.length === 0 ? (
        <div style={{ padding: "16px", border: "1px dashed var(--color-border-tertiary)", borderRadius: 12,
                      fontSize: 12.5, color: "var(--color-text-tertiary)", textAlign: "center" }}>
          No records are due from you.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {shown.map((r) => {
            const overdue = OVERDUE.has(dueState(r));
            const tone = overdue ? { c: "#A32D2D", bg: "#FFF8F8", bd: "#F09595" } : { c: "#8A5A00", bg: "#FFFBF2", bd: "#F0CE94" };
            return (
              <div key={r.id} style={{ border: `1px solid ${tone.bd}`, borderLeft: `4px solid ${tone.c}`, borderRadius: 10,
                                       background: tone.bg, padding: "10px 14px", display: "flex", gap: 12,
                                       alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
                <div style={{ flex: "1 1 260px", minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.4 }}>{controlLine(r)}</div>
                  <div style={{ fontSize: 11.5, color: "var(--color-text-secondary)", marginTop: 2 }}>
                    Record: {r.RecordDescription || r.Title}
                    {r.ControlDocument && <span> · {r.ControlDocument}</span>}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                  <span style={{ fontSize: 11.5, fontWeight: 600, color: tone.c }}>{dueText(r)}</span>
                  <button onClick={() => openRecord(r.id)}
                    style={{ padding: "6px 12px", fontSize: 11.5, fontWeight: 600, borderRadius: 7, border: "none",
                             background: "#0C447C", color: "#fff", cursor: "pointer", whiteSpace: "nowrap" }}>
                    Submit record
                  </button>
                </div>
              </div>
            );
          })}
          {records.length > shown.length && (
            <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)" }}>
              +{records.length - shown.length} more in the Record tracker.
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const QuickLink = ({ label, icon, onClick }) => (
  <button
    onClick={onClick}
    style={{
      display: "flex",
      alignItems: "center",
      gap: 6,
      padding: "7px 13px",
      fontSize: 12,
      fontWeight: 500,
      borderRadius: 8,
      border: "1.5px solid var(--color-border-secondary)",
      background: "var(--color-background-primary)",
      color: "var(--color-text-primary)",
      cursor: "pointer",
      whiteSpace: "nowrap",
    }}
  >
    <span>{icon}</span>{label}
  </button>
);

// =============================================================================
//  Main
// =============================================================================

export default function WorkHub({ go }) {
  const { isCompliance, isStandard, name, oid } = useCurrentUserRole();

  const queueQ       = usePendingQueue();
  const lifecycleQ   = useLifecycleDocs();
  const recordsQ     = useRecords();
  const overdueObligQ= useOverdueObligations();
  const expiringQ    = useExpiringContracts();
  const gapsQ        = useOpenGaps();
  const controlsQ    = useControls(isCompliance);

  const allRecords = recordsQ.data      || [];
  const allEvid    = useMemo(() => allRecords.filter(needsAttention), [allRecords]);
  const dueMine    = useMemo(() => dueForMe(allRecords), [allRecords]);
  const allOblig   = overdueObligQ.data || [];
  const allQueue   = queueQ.data        || [];
  const allLife    = lifecycleQ.data    || [];
  const allExpire  = expiringQ.data     || [];
  const allGaps    = gapsQ.data         || [];

  // Standard Users see only their own items.
  // Role holders are resolved server-side into OwnedByMe; that shared resolver
  // still supports legacy directory titles. Records do not store OwnerEntraId.
  const myEvid  = isStandard
    ? allEvid.filter((e) => e.OwnedByMe === true)
    : allEvid;

  const myOblig = isStandard
    ? allOblig.filter((o) => o.owner_id === oid || o.owner?.oid === oid || o.OwnerEntraId === oid)
    : allOblig;

  const stalled      = useMemo(() => allLife.filter((d) => (d.DaysInStage || 0) > 14), [allLife]);
  const criticalGaps = useMemo(() => allGaps.filter((g) => g.Severity === "Critical"), [allGaps]);
  const blocked      = useMemo(() => (controlsQ.data || []).filter((c) => c.Status === "Blocked"), [controlsQ.data]);
  // Documents in Review whose roles are not in Org Roles (the role check runs whenever the file changes).
  const roleProblems = useMemo(() => allLife.filter((d) => {
    if (d.Stage !== "Review" || !d.CDIFailures) return false;
    try { return JSON.parse(d.CDIFailures).some((f) => (f.check_id || f.check) === "V07"); } catch { return false; }
  }), [allLife]);
  const myDocs       = useMemo(() => allLife.filter((d) => d.OwnerEntraId === oid && d.ApprovalStatus !== "Approved"
    && ["Review", "Sensitisation"].includes(d.Stage)), [allLife, oid]);

  if (recordsQ.isLoading || overdueObligQ.isLoading) {
    return <LoadingState message="Loading work hub..." />;
  }

  const firstName = name ? name.split(" ")[0] : "";

  const urgencies = [
    // Blocking — shown to all roles (scoped)
    myEvid.length > 0   && { key: "evid",    color: "#A32D2D", bg: "#FFF8F8", bd: "#F09595", icon: "◎",
      count: myEvid.length,
      title: `record${myEvid.length > 1 ? "s" : ""} missing, late, stale or rejected`,
      message: isStandard
        ? `You have ${myEvid.length} overdue record item${myEvid.length > 1 ? "s" : ""} assigned to you. Submit as soon as possible.`
        : `${myEvid.length} control${myEvid.length > 1 ? "s are" : " is"} missing a record. ` +
          myEvid.slice(0, 3).map((e) => e.RecordDescription || "Item").join(", ") +
          (myEvid.length > 3 ? ` +${myEvid.length - 3} more.` : "."),
      action: "View records", nav: "records" },

    myOblig.length > 0  && { key: "oblig",   color: "#A32D2D", bg: "#FFF8F8", bd: "#F09595", icon: "⊘",
      count: myOblig.length,
      title: `compliance obligation${myOblig.length > 1 ? "s" : ""} overdue`,
      message: isStandard
        ? `You have ${myOblig.length} overdue obligation${myOblig.length > 1 ? "s" : ""}: ` +
          myOblig.slice(0, 2).map((o) => o.obligation_name || o.Title || "Obligation").join(", ") + "."
        : myOblig.slice(0, 3).map((o) => o.obligation_name || o.Title || "Obligation").join(", ") +
          (myOblig.length > 3 ? ` +${myOblig.length - 3} more.` : "."),
      action: "View calendar", nav: "cal" },

    // Everyone: the documents I own that are still being worked on
    myDocs.length > 0 && { key: "mydocs", color: "#0C447C", bg: "#F4F9FE", bd: "#85B7EB", icon: "◷",
      count: myDocs.length,
      title: `of my document${myDocs.length > 1 ? "s" : ""} in Review or Sensitisation`,
      message: myDocs.slice(0, 3).map((d) => `${d.Title || d.DocumentCode} (${d.Stage})`).join(", ") +
        (myDocs.length > 3 ? ` +${myDocs.length - 3} more.` : "."),
      action: "Open lifecycle", nav: "lifecycle" },

    // Compliance/Admin only
    isCompliance && blocked.length > 0 && { key: "blocked", color: "#791F1F", bg: "#FCEBEB", bd: "#F09595", icon: "⊘",
      count: blocked.length,
      title: `control${blocked.length > 1 ? "s" : ""} Blocked`,
      message: blocked.slice(0, 3).map((c) => `${c.ControlName || c.Title}: ${c.BlockedReason || "owner not in Org Roles"}`).join(" · ") +
        (blocked.length > 3 ? ` +${blocked.length - 3} more.` : ""),
      action: "Control Register", nav: "control" },

    isCompliance && roleProblems.length > 0 && { key: "roles", color: "#8A5A00", bg: "#FDF3E2", bd: "#F0CE94", icon: "⚑",
      count: roleProblems.length,
      title: `document${roleProblems.length > 1 ? "s" : ""} in Review naming roles not in Org Roles`,
      message: roleProblems.slice(0, 3).map((d) => d.Title || d.DocumentCode).join(", ") +
        (roleProblems.length > 3 ? ` +${roleProblems.length - 3} more.` : "") + " — fix them with “Fix CDI issues” on each card.",
      action: "View lifecycle", nav: "lifecycle" },

    isCompliance && criticalGaps.length > 0 && { key: "gaps", color: "#791F1F", bg: "#FCEBEB", bd: "#F09595", icon: "⊗",
      count: criticalGaps.length,
      title: `critical gap${criticalGaps.length > 1 ? "s" : ""} open`,
      message: `These will fail an external audit. ` +
        criticalGaps.slice(0, 3).map((g) => g.Clause || g.GapId || "").filter(Boolean).join(", ") +
        (criticalGaps.length > 3 ? ` +${criticalGaps.length - 3} more.` : "."),
      action: "Gap analysis", nav: "gap" },

    isCompliance && allExpire.length > 0 && { key: "contracts", color: "#BA7517", bg: "#FAEEDA", bd: "#FAC775", icon: "◷",
      count: allExpire.length,
      title: `contract${allExpire.length > 1 ? "s" : ""} expiring within 60 days`,
      message: allExpire.slice(0, 3).map((c) =>
        `${c.title || c.Title || "Contract"} — ${c.counterparty || c.Counterparty || ""}`
      ).join(", ") + (allExpire.length > 3 ? ` +${allExpire.length - 3} more.` : "."),
      action: "View contracts", nav: "contract" },

    isCompliance && stalled.length > 0 && { key: "stalled", color: "#BA7517", bg: "#FAEEDA", bd: "#FAC775", icon: "◷",
      count: stalled.length,
      title: `document${stalled.length > 1 ? "s" : ""} stalled in lifecycle`,
      message: stalled.slice(0, 3).map((d) => d.Title || d.DocumentCode || "Document").join(", ") +
        (stalled.length > 3 ? ` +${stalled.length - 3} more.` : "."),
      action: "View lifecycle", nav: "lifecycle" },

    isCompliance && allQueue.length > 0 && { key: "queue", color: "#633806", bg: "#FAEEDA", bd: "#FAC775", icon: "◈",
      count: allQueue.length,
      title: `item${allQueue.length > 1 ? "s" : ""} pending in extraction review`,
      message: "Controls from approved documents, and problems between documents, are waiting for review.",
      action: "Open queue", nav: "extraction" },

  ].filter(Boolean);

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
          {firstName ? `Welcome, ${firstName}` : "Work hub"}
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          {isStandard
            ? "Your compliance items requiring action."
            : "Compliance overview — urgency items across OrgOS."}
        </div>
      </div>

      {/* The records I must produce — first, for everyone */}
      <DueForMe records={dueMine} onSeeAll={() => go("records")} />

      {/* Quick links — Compliance/Admin */}
      {isCompliance && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 22 }}>
          <QuickLink icon="◈" label="Extraction Review"  onClick={() => go("extraction")} />
          <QuickLink icon="◷" label="Document Lifecycle" onClick={() => go("lifecycle")} />
          <QuickLink icon="◎" label="Gap Analysis"       onClick={() => go("gap")} />
          <QuickLink icon="◉" label="Standards Map"      onClick={() => go("standards")} />
          <QuickLink icon="⚑" label="Strategic Risks"    onClick={() => go("risk")} />
        </div>
      )}

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10, marginBottom: 24 }}>
        <Stat
          label={isStandard ? "My records needing attention" : "Records needing attention"}
          value={myEvid.length}
          color={myEvid.length > 0 ? "#A32D2D" : undefined}
        />
        <Stat
          label={isStandard ? "My overdue obligations" : "Overdue obligations"}
          value={myOblig.length}
          color={myOblig.length > 0 ? "#A32D2D" : undefined}
        />
        {isCompliance && (
          <Stat label="Pending queue items" value={allQueue.length}
            color={allQueue.length > 0 ? "#BA7517" : undefined} />
        )}
        {isCompliance && (
          <Stat label="Expiring contracts" value={allExpire.length}
            color={allExpire.length > 0 ? "#BA7517" : undefined} />
        )}
        {isCompliance && (
          <Stat label="Blocked controls" value={blocked.length}
            color={blocked.length > 0 ? "#A32D2D" : undefined} />
        )}
        {isCompliance && (
          <Stat label="Open gaps" value={allGaps.length}
            color={criticalGaps.length > 0 ? "#A32D2D" : allGaps.length > 0 ? "#BA7517" : undefined} />
        )}
      </div>

      {/* Urgency stream */}
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
        {urgencies.length > 0 ? "Needs attention" : "Everything looks good"}
      </div>

      {urgencies.length === 0 ? (
        <div style={{ padding: "28px", textAlign: "center", border: "1px dashed var(--color-border-tertiary)", borderRadius: 12, fontSize: 13, color: "var(--color-text-tertiary)" }}>
          {isStandard
            ? "No overdue records or obligations assigned to you. Keep it up."
            : "No urgent items right now."}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {urgencies.map((u) => (
            <UrgencyCard
              key={u.key}
              color={u.color} bg={u.bg} bd={u.bd}
              icon={u.icon} count={u.count} title={u.title} message={u.message}
              action={u.action} onAction={() => go(u.nav)}
            />
          ))}
        </div>
      )}

    </>
  );
}
