// =============================================================================
// pages/WorkHub/index.jsx
// Work Hub — the dashboard. Shows urgency streams requiring immediate action.
// Unassigned roles, overdue evidence, stalled lifecycle documents.
// Depends on: hooks/useGrc.js, api/grcApi.js
// =============================================================================

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import {
  ErrorState,
  LoadingState,
} from "../../components/shared/LoadingState.jsx";
import apiClient from "../../api/grcApi.js";

// =============================================================================
//  Data hooks
// =============================================================================

function useUnassignedRoles() {
  return useQuery({
    queryKey: ["roles", "unassigned"],
    queryFn: () =>
      apiClient.get("/api/v1/grc/roles/unassigned").then((r) => r.data),
    staleTime: 60_000,
  });
}

function usePendingQueueItems() {
  return useQuery({
    queryKey: ["queue", "pending-count"],
    queryFn: () =>
      apiClient
        .get("/api/v1/queue/items", { params: { status: "Pending Review" } })
        .then((r) => r.data),
    staleTime: 60_000,
  });
}

function useOverdueEvidence() {
  return useQuery({
    queryKey: ["evidence", "overdue"],
    queryFn: () =>
      apiClient
        .get("/api/v1/evidence", { params: { status: "Overdue" } })
        .then((r) => r.data),
    staleTime: 60_000,
  });
}

function useLifecycleDocuments() {
  return useQuery({
    queryKey: ["lifecycle"],
    queryFn: () =>
      apiClient.get("/api/v1/lifecycle/documents").then((r) => r.data),
    staleTime: 60_000,
  });
}

// =============================================================================
//  Urgency card
// =============================================================================

const UrgencyCard = ({
  color,
  bg,
  bd,
  icon,
  title,
  count,
  message,
  action,
  onAction,
}) => (
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 4,
        }}
      >
        <span style={{ fontSize: 16 }}>{icon}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color }}>
          {count !== null && (
            <span
              style={{
                fontSize: 18,
                fontWeight: 700,
                marginRight: 6,
                letterSpacing: "-1px",
              }}
            >
              {count}
            </span>
          )}
          {title}
        </span>
      </div>
      <div style={{ fontSize: 12, color, opacity: 0.85, lineHeight: 1.5 }}>
        {message}
      </div>
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

// =============================================================================
//  Summary stat
// =============================================================================

const Stat = ({ label, value, color }) => (
  <div
    style={{
      padding: "14px 16px",
      borderRadius: 10,
      background: "var(--color-background-secondary)",
      border: "1px solid var(--color-border-tertiary)",
    }}
  >
    <div
      style={{
        fontSize: 26,
        fontWeight: 700,
        color: color || "var(--color-text-primary)",
        letterSpacing: "-1px",
        marginBottom: 2,
      }}
    >
      {value}
    </div>
    <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
      {label}
    </div>
  </div>
);

// =============================================================================
//  Main
// =============================================================================

export default function WorkHub({ go }) {
  const roles = useUnassignedRoles();
  const queue = usePendingQueueItems();
  const lifecycle = useLifecycleDocuments();

  const overdueEvidence = useOverdueEvidence();
  const overdueEvidenceItems = overdueEvidence.data || [];

  const unassignedRoles = roles.data || [];
  const pendingItems = queue.data || [];
  const lifecycleDocs = lifecycle.data || [];

  const stalledDocs = useMemo(
    () => lifecycleDocs.filter((d) => (d.DaysInStage || 0) > 14),
    [lifecycleDocs],
  );

  const lowConfidence = useMemo(
    () => pendingItems.filter((i) => (i.ConfidenceScore || 0) < 0.6),
    [pendingItems],
  );

  const isLoading = roles.isLoading || queue.isLoading || lifecycle.isLoading;

  if (isLoading) return <LoadingState message="Loading work hub..." />;

  const hasUrgencies =
    unassignedRoles.length > 0 ||
    stalledDocs.length > 0 ||
    lowConfidence.length > 0;

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
          Work hub
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          Items requiring your attention across OrgOS.
        </div>
      </div>

      {/* Summary stats */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 10,
          marginBottom: 24,
        }}
      >
        <Stat
          label="Pending queue items"
          value={pendingItems.length}
          color={pendingItems.length > 0 ? "#BA7517" : undefined}
        />
        <Stat
          label="Unassigned roles"
          value={unassignedRoles.length}
          color={unassignedRoles.length > 0 ? "#A32D2D" : undefined}
        />
        <Stat label="Documents in review" value={lifecycleDocs.length} />
        <Stat
          label="Overdue evidence"
          value={overdueEvidenceItems.length}
          color={overdueEvidenceItems.length > 0 ? "#A32D2D" : undefined}
        />
        <Stat
          label="Stalled documents"
          value={stalledDocs.length}
          color={stalledDocs.length > 0 ? "#BA7517" : undefined}
        />
      </div>

      {/* Urgency stream */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
          {hasUrgencies ? "Needs attention" : "Everything looks good"}
        </div>

        {!hasUrgencies && (
          <div
            style={{
              padding: "24px",
              textAlign: "center",
              border: "1px dashed var(--color-border-tertiary)",
              borderRadius: 12,
              fontSize: 13,
              color: "var(--color-text-tertiary)",
            }}
          >
            No urgent items. All roles are assigned, no stalled documents, and
            no low-confidence queue items.
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Unassigned roles — highest priority */}
          {unassignedRoles.length > 0 && (
            <UrgencyCard
              color="#A32D2D"
              bg="#FFF8F8"
              bd="#F09595"
              icon="⚠"
              title={`role${unassignedRoles.length > 1 ? "s have" : " has"} no holder`}
              count={unassignedRoles.length}
              message={
                `Controls referencing ${unassignedRoles.length > 1 ? "these roles are" : "this role is"} unroutable. ` +
                `Evidence cannot be assigned. ` +
                `Roles: ${unassignedRoles.map((r) => r.role_title).join(", ")}.`
              }
              action="Assign now"
              onAction={() => go("role")}
            />
          )}

          {overdueEvidenceItems.length > 0 && (
            <UrgencyCard
              color="#A32D2D"
              bg="#FFF8F8"
              bd="#F09595"
              icon="◎"
              title={`evidence item${overdueEvidenceItems.length > 1 ? "s are" : " is"} overdue`}
              count={overdueEvidenceItems.length}
              message={
                `Evidence collection is overdue for ${overdueEvidenceItems.length} control${overdueEvidenceItems.length > 1 ? "s" : ""}. ` +
                `This means those controls have no current proof of operation. ` +
                `Overdue: ${overdueEvidenceItems
                  .slice(0, 3)
                  .map((e) => e.EvidenceDescription?.slice(0, 40) || "Unnamed")
                  .join(", ")}` +
                (overdueEvidenceItems.length > 3
                  ? ` and ${overdueEvidenceItems.length - 3} more.`
                  : ".")
              }
              action="View evidence"
              onAction={() => go("evidence")}
            />
          )}

          {/* Low confidence queue items */}
          {lowConfidence.length > 0 && (
            <UrgencyCard
              color="#791F1F"
              bg="#FCEBEB"
              bd="#F09595"
              icon="◎"
              title={`low-confidence extraction${lowConfidence.length > 1 ? "s" : ""} in review queue`}
              count={lowConfidence.length}
              message="These items scored below 60% confidence. They may be false positives and need careful human review before acceptance."
              action="Review queue"
              onAction={() => go("extraction")}
            />
          )}

          {/* Stalled lifecycle documents */}
          {stalledDocs.length > 0 && (
            <UrgencyCard
              color="#BA7517"
              bg="#FAEEDA"
              bd="#FAC775"
              icon="◷"
              title={`document${stalledDocs.length > 1 ? "s" : ""} stalled in lifecycle`}
              count={stalledDocs.length}
              message={
                `${stalledDocs.length > 1 ? "Documents have" : "A document has"} been in the same stage for over 14 days. ` +
                `Stalled: ${stalledDocs.map((d) => d.Title || d.DocumentCode).join(", ")}.`
              }
              action="View lifecycle"
              onAction={() => go("lifecycle")}
            />
          )}

          {/* Pending queue items — informational */}
          {pendingItems.length > 0 && unassignedRoles.length === 0 && (
            <UrgencyCard
              color="#633806"
              bg="#FAEEDA"
              bd="#FAC775"
              icon="◈"
              title={`item${pendingItems.length > 1 ? "s" : ""} pending review in AI queue`}
              count={pendingItems.length}
              message="Extracted controls, obligations, and findings are waiting for compliance team review and confirmation."
              action="Open queue"
              onAction={() => go("extraction")}
            />
          )}
        </div>
      </div>

      {/* Unassigned roles detail table */}
      {unassignedRoles.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              marginBottom: 8,
              color: "#A32D2D",
            }}
          >
            Unassigned roles — controls are unroutable
          </div>
          <div
            style={{
              border: "1px solid #F09595",
              borderRadius: 10,
              overflow: "hidden",
            }}
          >
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 12,
              }}
            >
              <thead>
                <tr style={{ background: "#FFF0F0" }}>
                  {["Role", "Department", "JD ref", "Status"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "7px 10px",
                        textAlign: "left",
                        fontWeight: 500,
                        fontSize: 11,
                        color: "#A32D2D",
                        borderBottom: "1px solid #F09595",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {unassignedRoles.map((role, i) => (
                  <tr
                    key={role.id}
                    style={{
                      borderBottom:
                        i < unassignedRoles.length - 1
                          ? "1px solid #FCE0E0"
                          : "none",
                      background: i % 2 ? "#FFF8F8" : "transparent",
                    }}
                  >
                    <td style={{ padding: "7px 10px", fontWeight: 500 }}>
                      {role.role_title}
                    </td>
                    <td
                      style={{
                        padding: "7px 10px",
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      {role.department || "—"}
                    </td>
                    <td
                      style={{
                        padding: "7px 10px",
                        fontFamily: "var(--font-mono)",
                        fontSize: 10,
                        color: "var(--color-text-tertiary)",
                      }}
                    >
                      {role.jd_reference || "—"}
                    </td>
                    <td style={{ padding: "7px 10px" }}>
                      <StatusBadge label="Unassigned" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            onClick={() => go("role")}
            style={{
              marginTop: 8,
              padding: "8px 16px",
              fontSize: 12,
              borderRadius: 8,
              border: "1.5px solid #F09595",
              background: "transparent",
              color: "#A32D2D",
              cursor: "pointer",
              fontWeight: 500,
            }}
          >
            Go to Role Register to assign →
          </button>
        </div>
      )}
    </>
  );
}
