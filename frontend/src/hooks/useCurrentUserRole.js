// =============================================================================
// hooks/useCurrentUserRole.js
// Single source of truth for role detection across the entire OrgOS frontend.
// Reads Entra ID app roles from the MSAL token claims.
//
// Three roles:
//   Standard User  — no Entra app role assigned
//   Compliance     — Compliance.Lead role
//   Admin          — OrgOS.Admin role (superset of Compliance)
//
// Usage:
//   const { isAdmin, isCompliance, isStandard, oid, name, email, roleLabel } =
//     useCurrentUserRole();
// =============================================================================

import { useMsal } from "@azure/msal-react";

export function useCurrentUserRole() {
  const { accounts } = useMsal();
  const account = accounts[0];
  const claims  = account?.idTokenClaims || {};
  const roles   = Array.isArray(claims.roles) ? claims.roles : [];

  const isAdmin      = roles.includes("OrgOS.Admin");
  const isCompliance = roles.includes("Compliance.Lead") || isAdmin;
  const isStandard   = !isAdmin && !isCompliance;

  // Stable Entra OID — use as identity key, never changes
  const oid   = claims.oid || account?.localAccountId || account?.homeAccountId || "";
  const name  = account?.name || "";
  const email = account?.username || "";

  return {
    oid,
    name,
    email,
    roles,
    isAdmin,
    isCompliance,
    isStandard,
    roleLabel: isAdmin ? "Admin" : isCompliance ? "Compliance" : "Standard User",
  };
}
