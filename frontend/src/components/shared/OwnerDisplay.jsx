// =============================================================================
// OwnerDisplay.jsx — shows an owner ROLE and who it actually resolves to.
//
// The Control owner is a role in Org Roles, resolved to its members. A text that
// is only a Microsoft job title is shown as NOT A ROLE: nobody owns it. It shows:
//   • a kind badge (ROLE / NOT A ROLE / UNASSIGNED)
//   • the people who hold it (click to expand)
//   • an alias note when the document's wording matched via an alias
//
// Expects the resolved fields the API stamps on controls/records:
//   OwnerRole, OwnerKind, OwnerPeople, OwnerResolved, OwnerCanonical, OwnerViaAlias
// =============================================================================

import { useState } from "react";

const KINDS = {
  group:      { label: "ROLE",      fg: "#3C3489", bg: "#EEEDFE", bd: "#AFA9EC" },
  // A job title is never a role (Bobby): shown so the officer sees why it isn't owned.
  job_title:  { label: "NOT A ROLE (job title)", fg: "#8A5A00", bg: "#FDF3E2", bd: "#F0CE94" },
  unresolved: { label: "UNASSIGNED", fg: "#8A5A00", bg: "#FDF3E2", bd: "#F0CE94" },
};

export default function OwnerDisplay({ item, compact = false }) {
  const [open, setOpen] = useState(false);
  const role     = item?.OwnerRole || "";
  const kind     = item?.OwnerKind || (role ? "unresolved" : "unresolved");
  const people   = item?.OwnerPeople || [];
  const viaAlias = item?.OwnerViaAlias === true;
  const canonical = item?.OwnerCanonical || "";
  const k = KINDS[kind] || KINDS.unresolved;

  if (!role) {
    return <span style={{ color: "var(--color-text-tertiary)" }}>No owner</span>;
  }

  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 3 }}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span>{role}</span>
        <span
          title={
            kind === "unresolved"
              ? "This owner could not be resolved. Check the role and its members in Org Roles."
              : `${people.length} ${people.length === 1 ? "person" : "people"} hold this role`
          }
          style={{ fontSize: 9, fontWeight: 700, color: k.fg, background: k.bg,
                   border: `0.5px solid ${k.bd}`, borderRadius: 20, padding: "1px 6px" }}>
          {k.label}
        </span>
        {people.length > 0 && (
          <button
            onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
            style={{ fontSize: 10.5, border: "none", background: "transparent", padding: 0,
                     cursor: "pointer", color: "var(--color-text-info)", textDecoration: "underline" }}>
            {open ? "hide" : `${people.length} ${people.length === 1 ? "person" : "people"}`}
          </button>
        )}
      </span>

      {/* Alias trust cue — explain why a different wording matched */}
      {viaAlias && canonical && (
        <span style={{ fontSize: 10.5, color: "var(--color-text-tertiary)", fontStyle: "italic" }}>
          matched via alias “{role}” → {canonical}
        </span>
      )}

      {open && people.length > 0 && (
        <span style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 2 }}>
          {people.map((p) => (
            <span key={p.oid}
              title={p.email}
              style={{ fontSize: 10.5, background: "var(--color-background-secondary)",
                       border: "1px solid var(--color-border-tertiary)", borderRadius: 20,
                       padding: "2px 8px", color: "var(--color-text-secondary)" }}>
              {p.display_name || p.email}
            </span>
          ))}
        </span>
      )}

      {!compact && kind === "unresolved" && (
        <span style={{ fontSize: 10.5, color: "#8A5A00" }}>
          Check this role in Org Roles and assign the people who hold it. If the name is
          wrong, use an existing role or create the role there.
        </span>
      )}
    </span>
  );
}
