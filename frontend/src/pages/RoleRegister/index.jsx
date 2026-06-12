// =============================================================================
// pages/RoleRegister/index.jsx
// Role Register — read-only for most users.
// Compliance Lead and OrgOS Admin can assign people to unassigned roles.
// Roles arrive from documents via the Extractor → AI Review Queue pipeline.
// The only manual creation path is CCO emergency override (OrgOS.Admin only).
// =============================================================================

import { useState, useMemo } from "react";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field, FormError } from "../../components/shared/Forms.jsx";
import {
  TableSkeleton,
  ErrorState,
  EmptyState,
} from "../../components/shared/LoadingState.jsx";
import { useRoles, useAssignRole } from "../../hooks/useGrc.js";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import ReadOnlyBanner from "../../components/shared/ReadOnlyBanner.jsx";
import RoleForm from "./RoleForm.jsx";

const COLS = [
  { key: "role_title", label: "Role" },
  { key: "department", label: "Department" },
  { key: "jd_reference", label: "JD ref", mono: true },
  { key: "current_holder", label: "Holder" },
  { key: "source_system", label: "Source" },
  { key: "assignment_status", label: "Status" },
];

const getHolder = (h) => (h ? h.display_name || h.email || "—" : "—");

// ── Assign person panel ────────────────────────────────────────────────────────
const AssignPanel = ({ role, onSuccess, onCancel }) => {
  const [holderOid, setHolderOid] = useState("");
  const assignRole = useAssignRole();

  const handleAssign = async () => {
    if (!holderOid.trim()) return;
    await assignRole.mutateAsync({ id: role.id, holderOid: holderOid.trim() });
    onSuccess();
  };

  return (
    <div
      style={{
        marginTop: 14,
        padding: "14px",
        background: "#EEEDFE",
        borderRadius: 10,
        border: "1px solid #AFA9EC",
      }}
    >
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: "#3C3489",
          marginBottom: 8,
        }}
      >
        Assign person to this role
      </div>
      <div style={{ fontSize: 11, color: "#3C3489", marginBottom: 10 }}>
        This role has no current holder. All controls referencing it are
        unroutable until someone is assigned.
      </div>
      {assignRole.error && <FormError message={assignRole.error.message} />}
      <div style={{ marginBottom: 8 }}>
        <label
          style={{
            display: "block",
            fontSize: 11,
            fontWeight: 500,
            color: "var(--color-text-secondary)",
            marginBottom: 4,
            textTransform: "uppercase",
            letterSpacing: "0.4px",
          }}
        >
          Entra ID OID <span style={{ color: "#A32D2D" }}>*</span>
        </label>
        <input
          type="text"
          value={holderOid}
          onChange={(e) => setHolderOid(e.target.value)}
          placeholder="Entra ID object ID of the person taking this role"
          style={{
            width: "100%",
            fontSize: 13,
            padding: "8px 10px",
            borderRadius: 8,
            border: "1.5px solid #AFA9EC",
            background: "#fff",
            color: "var(--color-text-primary)",
            outline: "none",
            boxSizing: "border-box",
          }}
        />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={handleAssign}
          disabled={assignRole.isPending || !holderOid.trim()}
          style={{
            padding: "8px 16px",
            fontSize: 12,
            borderRadius: 8,
            border: "none",
            background:
              assignRole.isPending || !holderOid.trim() ? "#E8E8E8" : "#534AB7",
            color: assignRole.isPending || !holderOid.trim() ? "#999" : "#fff",
            cursor:
              assignRole.isPending || !holderOid.trim()
                ? "not-allowed"
                : "pointer",
            fontWeight: 500,
          }}
        >
          {assignRole.isPending ? "Assigning..." : "Assign person"}
        </button>
        <button
          onClick={onCancel}
          style={{
            padding: "8px 14px",
            fontSize: 12,
            borderRadius: 8,
            border: "1.5px solid #C0C0C0",
            background: "transparent",
            color: "var(--color-text-secondary)",
            cursor: "pointer",
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

// ── Main component ─────────────────────────────────────────────────────────────
export default function RoleRegister() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [showAssign, setShowAssign] = useState(false);

  const { isAdmin, isCompliance, isStandard } = useCurrentUserRole();
  const { data: roles = [], isLoading, error, refetch } = useRoles();

  const unassignedCount = roles.filter(
    (r) => r.assignment_status === "Unassigned",
  ).length;

  const filtered = useMemo(() => {
    if (!search.trim()) return roles;
    const q = search.toLowerCase();
    return roles.filter(
      (r) =>
        r.role_title?.toLowerCase().includes(q) ||
        r.department?.toLowerCase().includes(q) ||
        getHolder(r.current_holder).toLowerCase().includes(q),
    );
  }, [roles, search]);

  // ── Detail view ──────────────────────────────────────────────────────────────
  if (selected) {
    const isUnassigned = selected.assignment_status === "Unassigned";
    return (
      <div style={{ maxWidth: 520 }}>
        <button
          onClick={() => {
            setSelected(null);
            setShowAssign(false);
          }}
          style={{
            fontSize: 12,
            color: "var(--color-text-info)",
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 0,
            marginBottom: 12,
          }}
        >
          ← Back
        </button>

        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          <StatusBadge label={selected.assignment_status} />
        </div>

        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
          {selected.role_title}
        </div>

        <Field l="Department" v={selected.department} />
        <Field l="JD reference" v={selected.jd_reference} />
        <Field l="Current holder" v={getHolder(selected.current_holder)} />
        <Field l="Source system" v={selected.source_system} />
        {selected.variant_terms && (
          <Field
            l="Variant terms"
            v={<span style={{ whiteSpace: "pre-line" }}>{selected.variant_terms}</span>}
          />
        )}

        {/* Unassigned warning */}
        {isUnassigned && (
          <div
            style={{
              marginTop: 14,
              padding: "10px 12px",
              background: "#FCEBEB",
              border: "1px solid #F09595",
              borderRadius: 8,
              fontSize: 12,
              color: "#791F1F",
            }}
          >
            This role has no holder. Controls referencing this role cannot be
            routed and evidence cannot be assigned.
          </div>
        )}

        {/* Assign panel — Admin only (role assignment affects control routing) */}
        {isUnassigned && isAdmin && !showAssign && (
          <button
            onClick={() => setShowAssign(true)}
            style={{
              marginTop: 12,
              padding: "9px 16px",
              fontSize: 12,
              borderRadius: 8,
              border: "none",
              background: "#534AB7",
              color: "#fff",
              cursor: "pointer",
              fontWeight: 500,
            }}
          >
            Assign person to this role
          </button>
        )}

        {isUnassigned && isAdmin && showAssign && (
          <AssignPanel
            role={selected}
            onSuccess={() => {
              setShowAssign(false);
              setSelected(null);
              refetch();
            }}
            onCancel={() => setShowAssign(false)}
          />
        )}

        {/* Reassign holder — Admin only */}
        {!isUnassigned && isAdmin && !showAssign && (
          <button
            onClick={() => setShowAssign(true)}
            style={{
              marginTop: 12,
              padding: "8px 14px",
              fontSize: 12,
              borderRadius: 8,
              border: "1.5px solid #C0C0C0",
              background: "transparent",
              color: "var(--color-text-secondary)",
              cursor: "pointer",
            }}
          >
            Reassign holder
          </button>
        )}

        {!isUnassigned && isAdmin && showAssign && (
          <AssignPanel
            role={selected}
            onSuccess={() => {
              setShowAssign(false);
              setSelected(null);
              refetch();
            }}
            onCancel={() => setShowAssign(false)}
          />
        )}
      </div>
    );
  }

  // ── CCO emergency override form ───────────────────────────────────────────────
  if (showForm) {
    return (
      <RoleForm
        onSuccess={() => {
          setShowForm(false);
          refetch();
        }}
        onCancel={() => setShowForm(false)}
      />
    );
  }

  // ── List view ─────────────────────────────────────────────────────────────────
  return (
    <>
      {isStandard && (
        <ReadOnlyBanner message="You have read-only access to the Role Register. Role assignment is restricted to OrgOS Admins." />
      )}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 12,
        }}
      >
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
            Role register
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Roles, JDs, holders.{" "}
          </div>
        </div>
        {/* Only OrgOS.Admin (CCO) sees the emergency add button */}
        {isAdmin && (
          <button
            onClick={() => setShowForm(true)}
            style={{
              padding: "8px 16px",
              fontSize: 12,
              borderRadius: 8,
              border: "1.5px solid #A32D2D",
              background: "transparent",
              color: "#A32D2D",
              cursor: "pointer",
              fontWeight: 500,
            }}
          >
            + Add role (override)
          </button>
        )}
      </div>

      {/* Unassigned roles banner */}
      {unassignedCount > 0 && (
        <div
          style={{
            padding: "10px 14px",
            background: "#FCEBEB",
            border: "1px solid #F09595",
            borderRadius: 10,
            marginBottom: 12,
            fontSize: 12,
            color: "#791F1F",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span>
            <strong>
              {unassignedCount} role{unassignedCount > 1 ? "s have" : " has"} no
              holder.
            </strong>{" "}
            Controls referencing{" "}
            {unassignedCount > 1 ? "these roles are" : "this role is"}{" "}
            unroutable. Evidence cannot be assigned.
          </span>
          {isCompliance && (
            <button
              onClick={() => setSearch("Unassigned")}
              style={{
                fontSize: 11,
                padding: "3px 10px",
                borderRadius: 5,
                border: "1px solid #F09595",
                background: "transparent",
                color: "#791F1F",
                cursor: "pointer",
                whiteSpace: "nowrap",
                marginLeft: 10,
              }}
            >
              View unassigned
            </button>
          )}
        </div>
      )}

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search roles..."
        style={{
          width: "100%",
          fontSize: 13,
          padding: "10px 14px",
          borderRadius: 8,
          border: "1.5px solid #C0C0C0",
          background: "var(--color-background-primary)",
          color: "var(--color-text-primary)",
          marginBottom: 10,
          boxSizing: "border-box",
          outline: "none",
        }}
      />

      {isLoading && <TableSkeleton rows={8} cols={COLS.length} />}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {!isLoading && !error && filtered.length === 0 && (
        <EmptyState
          message={
            search
              ? "No roles match your search."
              : "No roles in the register yet. Roles arrive from the extraction pipeline."
          }
        />
      )}

      {!isLoading && !error && filtered.length > 0 && (
        <>
          <div
            style={{
              border: "1px solid #D0D0D0",
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
                <tr style={{ background: "var(--color-background-secondary)" }}>
                  {COLS.map((c) => (
                    <th
                      key={c.key}
                      style={{
                        padding: "7px 8px",
                        textAlign: "left",
                        fontWeight: 500,
                        fontSize: 11,
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((role, i) => {
                  const isUnassigned = role.assignment_status === "Unassigned";
                  return (
                    <tr
                      key={role.id}
                      onClick={() => setSelected(role)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && setSelected(role)}
                      style={{
                        borderBottom: "1px solid #E8E8E8",
                        cursor: "pointer",
                        background: isUnassigned
                          ? "#FFF8F8"
                          : i % 2
                            ? "var(--color-background-secondary)"
                            : "transparent",
                        borderLeft: isUnassigned
                          ? "3px solid #F09595"
                          : "3px solid transparent",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.background =
                          "var(--color-background-info)")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.background = isUnassigned
                          ? "#FFF8F8"
                          : i % 2
                            ? "var(--color-background-secondary)"
                            : "transparent")
                      }
                    >
                      {COLS.map((col) => {
                        const v =
                          col.key === "current_holder"
                            ? getHolder(role.current_holder)
                            : col.key === "assignment_status"
                              ? null
                              : role[col.key];
                        return (
                          <td
                            key={col.key}
                            style={{
                              padding: "6px 8px",
                              fontFamily: col.mono
                                ? "var(--font-mono)"
                                : undefined,
                              fontSize: col.mono ? 10 : 12,
                            }}
                          >
                            {col.key === "assignment_status" ? (
                              <StatusBadge label={role.assignment_status} />
                            ) : (
                              (v ?? "—")
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              marginTop: 6,
            }}
          >
            {filtered.length} of {roles.length} · {unassignedCount} unassigned
          </div>
        </>
      )}
    </>
  );
}
