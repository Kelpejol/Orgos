// =============================================================================
// pages/WorkHub/index.jsx — Dashboard (RBAC-scoped urgency view)
// =============================================================================

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { LoadingState } from "../../components/shared/LoadingState.jsx";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import apiClient, { complianceApi, contractsApi } from "../../api/grcApi.js";

// =============================================================================
//  Data hooks
// =============================================================================

const useUnassignedRoles = () =>
  useQuery({
    queryKey: ["roles", "unassigned"],
    queryFn: () => apiClient.get("/api/v1/grc/roles/unassigned").then((r) => r.data),
    staleTime: 60_000,
  });

const usePendingQueue = () =>
  useQuery({
    queryKey: ["queue", "pending-wh"],
    queryFn: () =>
      apiClient.get("/api/v1/queue/items", { params: { status: "Pending Review" } }).then((r) => r.data),
    staleTime: 60_000,
  });

const useLifecycleDocs = () =>
  useQuery({
    queryKey: ["lifecycle", "all"],
    queryFn: () => apiClient.get("/api/v1/lifecycle/documents").then((r) => r.data),
    staleTime: 60_000,
  });

const useOverdueEvidence = () =>
  useQuery({
    queryKey: ["evidence", "overdue"],
    queryFn: () =>
      apiClient.get("/api/v1/evidence", { params: { status: "Overdue" } }).then((r) => r.data),
    staleTime: 60_000,
  });

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
      apiClient.get("/api/v1/gap-analysis", { params: { status: "Open" } }).then((r) => r.data),
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
  const { isAdmin, isCompliance, isStandard, name, oid } = useCurrentUserRole();

  const rolesQ       = useUnassignedRoles();
  const queueQ       = usePendingQueue();
  const lifecycleQ   = useLifecycleDocs();
  const overdueEvidQ = useOverdueEvidence();
  const overdueObligQ= useOverdueObligations();
  const expiringQ    = useExpiringContracts();
  const gapsQ        = useOpenGaps();

  const allEvid    = overdueEvidQ.data  || [];
  const allOblig   = overdueObligQ.data || [];
  const allRoles   = rolesQ.data        || [];
  const allQueue   = queueQ.data        || [];
  const allLife    = lifecycleQ.data    || [];
  const allExpire  = expiringQ.data     || [];
  const allGaps    = gapsQ.data         || [];

  // Standard Users see only their own items
  const myEvid  = isStandard
    ? allEvid.filter((e) => e.owner_oid === oid || e.OwnerEntraId === oid || e.owner?.oid === oid)
    : allEvid;

  const myOblig = isStandard
    ? allOblig.filter((o) => o.owner_id === oid || o.owner?.oid === oid || o.OwnerEntraId === oid)
    : allOblig;

  const stalled      = useMemo(() => allLife.filter((d) => (d.DaysInStage || 0) > 14), [allLife]);
  const criticalGaps = useMemo(() => allGaps.filter((g) => g.severity === "Critical"), [allGaps]);

  if (overdueEvidQ.isLoading || overdueObligQ.isLoading) {
    return <LoadingState message="Loading work hub..." />;
  }

  const firstName = name ? name.split(" ")[0] : "";

  const urgencies = [
    // Blocking — shown to all roles (scoped)
    myEvid.length > 0   && { key: "evid",    color: "#A32D2D", bg: "#FFF8F8", bd: "#F09595", icon: "◎",
      count: myEvid.length,
      title: `evidence item${myEvid.length > 1 ? "s" : ""} overdue`,
      message: isStandard
        ? `You have ${myEvid.length} overdue evidence item${myEvid.length > 1 ? "s" : ""} assigned to you. Submit as soon as possible.`
        : `${myEvid.length} control${myEvid.length > 1 ? "s are" : " is"} missing evidence. ` +
          myEvid.slice(0, 3).map((e) => e.evidence_description || e.EvidenceDescription || "Item").join(", ") +
          (myEvid.length > 3 ? ` +${myEvid.length - 3} more.` : "."),
      action: "View evidence", nav: "evidence" },

    myOblig.length > 0  && { key: "oblig",   color: "#A32D2D", bg: "#FFF8F8", bd: "#F09595", icon: "⊘",
      count: myOblig.length,
      title: `compliance obligation${myOblig.length > 1 ? "s" : ""} overdue`,
      message: isStandard
        ? `You have ${myOblig.length} overdue obligation${myOblig.length > 1 ? "s" : ""}: ` +
          myOblig.slice(0, 2).map((o) => o.obligation_name || o.Title || "Obligation").join(", ") + "."
        : myOblig.slice(0, 3).map((o) => o.obligation_name || o.Title || "Obligation").join(", ") +
          (myOblig.length > 3 ? ` +${myOblig.length - 3} more.` : "."),
      action: "View calendar", nav: "cal" },

    // Compliance/Admin only
    isCompliance && allRoles.length > 0 && { key: "roles",   color: "#A32D2D", bg: "#FFF8F8", bd: "#F09595", icon: "⚠",
      count: allRoles.length,
      title: `unassigned role${allRoles.length > 1 ? "s" : ""} — controls unroutable`,
      message: `Controls referencing unassigned roles cannot route evidence. ` +
        allRoles.slice(0, 3).map((r) => r.role_title).join(", ") +
        (allRoles.length > 3 ? ` +${allRoles.length - 3} more.` : "."),
      action: isAdmin ? "Assign now" : "View roles", nav: "role" },

    isCompliance && criticalGaps.length > 0 && { key: "gaps", color: "#791F1F", bg: "#FCEBEB", bd: "#F09595", icon: "⊗",
      count: criticalGaps.length,
      title: `critical gap${criticalGaps.length > 1 ? "s" : ""} — no controls at all`,
      message: `These clauses will fail any external audit. ` +
        criticalGaps.slice(0, 3).map((g) => g.iso_clause || g.ISOClause || g.gap_id || "").filter(Boolean).join(", ") +
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
      title: `item${allQueue.length > 1 ? "s" : ""} pending in AI review queue`,
      message: "Extracted controls and findings are waiting for compliance team review.",
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

      {/* Quick links — Compliance/Admin */}
      {isCompliance && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 22 }}>
          <QuickLink icon="◈" label="AI Review Queue"    onClick={() => go("extraction")} />
          <QuickLink icon="◷" label="Document Lifecycle" onClick={() => go("lifecycle")} />
          <QuickLink icon="◎" label="Gap Analysis"       onClick={() => go("gap")} />
          <QuickLink icon="◉" label="Standards Map"      onClick={() => go("standards")} />
          <QuickLink icon="⚑" label="Strategic Risks"    onClick={() => go("risk")} />
        </div>
      )}

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10, marginBottom: 24 }}>
        <Stat
          label={isStandard ? "My overdue evidence" : "Overdue evidence"}
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
          <Stat label="Unassigned roles" value={allRoles.length}
            color={allRoles.length > 0 ? "#A32D2D" : undefined} />
        )}
        {isCompliance && (
          <Stat label="Expiring contracts" value={allExpire.length}
            color={allExpire.length > 0 ? "#BA7517" : undefined} />
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
            ? "No overdue evidence or obligations assigned to you. Keep it up."
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

      {/* Unassigned roles table — Compliance/Admin */}
      {isCompliance && allRoles.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: "#A32D2D" }}>
            Unassigned roles
          </div>
          <div style={{ border: "1px solid #F09595", borderRadius: 10, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#FFF0F0" }}>
                  {["Role", "Department", "JD ref"].map((h) => (
                    <th key={h} style={{ padding: "7px 10px", textAlign: "left", fontWeight: 500, fontSize: 11, color: "#A32D2D", borderBottom: "1px solid #F09595" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {allRoles.map((role, i) => (
                  <tr key={role.id} style={{ borderBottom: i < allRoles.length - 1 ? "1px solid #FCE0E0" : "none", background: i % 2 ? "#FFF8F8" : "transparent" }}>
                    <td style={{ padding: "7px 10px", fontWeight: 500 }}>{role.role_title}</td>
                    <td style={{ padding: "7px 10px", color: "var(--color-text-secondary)" }}>{role.department || "—"}</td>
                    <td style={{ padding: "7px 10px", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--color-text-tertiary)" }}>{role.jd_reference || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            onClick={() => go("role")}
            style={{ marginTop: 8, padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "1.5px solid #F09595", background: "transparent", color: "#A32D2D", cursor: "pointer", fontWeight: 500 }}
          >
            {isAdmin ? "Go to Role Register to assign →" : "Go to Role Register →"}
          </button>
        </div>
      )}
    </>
  );
}
