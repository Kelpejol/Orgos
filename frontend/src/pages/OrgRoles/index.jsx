// =============================================================================
// pages/OrgRoles/index.jsx
// Read-only directory of Dragnet users and their org_roles (orgos-admin,
// compliance, and any other Dragnet-wide tags), read live from Entra ID.
// OrgOS never assigns org_roles — that's exclusively a Dragnet ERP admin
// panel action. Compliance/OrgOS Admin only.
// =============================================================================

import { useMemo, useState } from "react";
import { useOrgRoles, useOwnershipSummary } from "../../hooks/useGrc.js";
import { TableSkeleton, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import ReadOnlyBanner from "../../components/shared/ReadOnlyBanner.jsx";
import GroupsPanel from "../../components/shared/GroupsPanel.jsx";

const OrgRoleChip = ({ role }) => (
  <span
    style={{
      fontSize: 10,
      padding: "1px 6px",
      borderRadius: 3,
      background: "#EEEDFE",
      color: "#3C3489",
      border: "0.5px solid #AFA9EC",
      whiteSpace: "nowrap",
    }}
  >
    {role}
  </span>
);

const OrgRolesCell = ({ roles }) => {
  if (!roles || roles.length === 0) {
    return <span style={{ color: "var(--color-text-tertiary)" }}>—</span>;
  }
  // List ALL roles; wrap within the column and expose the full list on hover.
  return (
    <div
      title={roles.join(", ")}
      style={{ display: "flex", flexWrap: "wrap", gap: 4, maxWidth: 240 }}
    >
      {roles.map((r) => (
        <OrgRoleChip key={r} role={r} />
      ))}
    </div>
  );
};

// Text cell that wraps long values gracefully and shows the full value on hover.
const TextCell = ({ value, muted }) => {
  if (!value) return <span style={{ color: "var(--color-text-tertiary)" }}>—</span>;
  return (
    <span
      title={value}
      style={{
        display: "inline-block",
        maxWidth: 220,
        overflowWrap: "anywhere",
        color: muted ? "var(--color-text-secondary)" : "var(--color-text-primary)",
      }}
    >
      {value}
    </span>
  );
};

export default function OrgRoles() {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("people");
  const { data: users = [], isLoading, error, refetch } = useOrgRoles();
  const { data: ownership = {} } = useOwnershipSummary();
  const ownsFor = (role) => ownership[(role || "").trim().toLowerCase()] || null;

  const filtered = useMemo(() => {
    if (!search.trim()) return users;
    const q = search.toLowerCase();
    return users.filter(
      (u) =>
        u.display_name?.toLowerCase().includes(q) ||
        u.email?.toLowerCase().includes(q) ||
        u.job_title?.toLowerCase().includes(q) ||
        u.department?.toLowerCase().includes(q) ||
        (u.org_roles || []).some((r) => r.toLowerCase().includes(q)),
    );
  }, [users, search]);

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
          Org roles &amp; groups
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          People with their job title and department, and the groups you can assign as owners.
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {[["people", "People"], ["groups", "Groups"]].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            padding: "7px 14px", fontSize: 12.5, fontWeight: 600, borderRadius: 8, cursor: "pointer",
            border: tab === k ? "1.5px solid var(--color-text-primary)" : "1.5px solid var(--color-border-tertiary)",
            background: tab === k ? "var(--color-text-primary)" : "transparent",
            color: tab === k ? "var(--color-background-primary)" : "var(--color-text-secondary)",
          }}>{label}</button>
        ))}
      </div>

      {tab === "groups" && <GroupsPanel />}

      {tab === "people" && (
        <>
      <ReadOnlyBanner message="Org roles are read live from Entra ID. Assignment is managed exclusively in the Dragnet ERP admin panel." />

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search people, job title, department, or roles..."
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

      {isLoading && <TableSkeleton rows={8} cols={6} />}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {!isLoading && !error && filtered.length === 0 && (
        <EmptyState
          message={
            search
              ? "No people match your search."
              : "No users with an org_role assigned yet."
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
                  {["Name", "Email", "Job title", "Department", "Owns", "Org roles"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "7px 8px",
                        textAlign: "left",
                        fontWeight: 500,
                        fontSize: 11,
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((u, i) => (
                  <tr
                    key={u.oid}
                    style={{
                      borderBottom: "1px solid #E8E8E8",
                      background: i % 2 ? "var(--color-background-secondary)" : "transparent",
                    }}
                  >
                    <td style={{ padding: "6px 8px", fontWeight: 500 }}>
                      {u.display_name || "—"}
                    </td>
                    <td style={{ padding: "6px 8px", color: "var(--color-text-secondary)" }}>
                      {u.email || "—"}
                    </td>
                    <td style={{ padding: "6px 8px" }}>
                      <TextCell value={u.job_title} />
                    </td>
                    <td style={{ padding: "6px 8px" }}>
                      <TextCell value={u.department} muted />
                    </td>
                    <td style={{ padding: "6px 8px", whiteSpace: "nowrap" }}>
                      {(() => {
                        const o = ownsFor(u.job_title);
                        if (!o) return <span style={{ color: "var(--color-text-tertiary)" }}>—</span>;
                        return (
                          <span title={`${o.controls} control(s), ${o.evidence} evidence item(s) owned by "${u.job_title}"`}
                                style={{ fontSize: 11 }}>
                            {o.controls > 0 && <b>{o.controls}</b>} {o.controls > 0 ? "ctrl" : ""}
                            {o.controls > 0 && o.evidence > 0 ? " · " : ""}
                            {o.evidence > 0 && <b>{o.evidence}</b>} {o.evidence > 0 ? "evid" : ""}
                          </span>
                        );
                      })()}
                    </td>
                    <td style={{ padding: "6px 8px" }}>
                      <OrgRolesCell roles={u.org_roles} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
            {filtered.length} of {users.length}
          </div>
        </>
      )}
        </>
      )}
    </>
  );
}
