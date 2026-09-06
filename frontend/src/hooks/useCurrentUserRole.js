// =============================================================================
// hooks/useCurrentUserRole.js
// Single source of truth for role detection across the entire OrgOS frontend.
// Reads org_roles from the session established at boot via AuthContext
// (sourced from GET /api/auth/session, which validates the erp_auth cookie).
//
// Three roles:
//   Standard User  — no org_role assigned
//   Compliance     — "compliance" org_role
//   Admin          — "orgos-admin" org_role (superset of Compliance)
//
// Usage:
//   const { isAdmin, isCompliance, isStandard, oid, name, email, roleLabel } =
//     useCurrentUserRole();
// =============================================================================

import { useAuth } from "../context/AuthContext.jsx";

export function useCurrentUserRole() {
  const { roles, userName, userEmail, userOid } = useAuth();

  const isAdmin      = roles.includes("orgos-admin");
  const isCompliance = roles.includes("compliance") || isAdmin;
  const isStandard   = !isAdmin && !isCompliance;

  return {
    oid: userOid,
    name: userName,
    email: userEmail,
    roles,
    isAdmin,
    isCompliance,
    isStandard,
    roleLabel: isAdmin ? "Admin" : isCompliance ? "Compliance" : "Standard User",
  };
}
