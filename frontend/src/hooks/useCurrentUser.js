// =============================================================================
// hooks/useCurrentUser.js
// Returns the logged-in user's identity from AuthContext (populated at boot
// from GET /api/auth/session — see main.jsx).
// =============================================================================

import { useAuth } from "../context/AuthContext.jsx";

/**
 * Returns the current user's identity.
 * oid — Entra ID object ID, used as owner_id in all register forms.
 * name — display name shown in greyed out field.
 * email — UPN / email address.
 */
export function useCurrentUser() {
  const { userOid, userName, userEmail } = useAuth();
  return { oid: userOid || "", name: userName || "", email: userEmail || "" };
}
