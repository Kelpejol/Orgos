// =============================================================================
// hooks/useCurrentUser.js
// Returns the logged-in user's identity from the MSAL session.
// No API call needed — the OID is in the token claims already decoded by MSAL.
// =============================================================================

import { useMsal } from "@azure/msal-react";

/**
 * Returns the current user's identity from the active MSAL account.
 * oid — Entra ID object ID, used as owner_id in all register forms.
 * name — display name shown in greyed out field.
 * email — UPN / email address.
 */
export function useCurrentUser() {
  const { accounts } = useMsal();
  const account = accounts[0];

  if (!account) {
    return { oid: "", name: "", email: "" };
  }

  return {
    oid: account.idTokenClaims?.oid || account.localAccountId || "",
    name: account.name || account.username || "",
    email: account.username || "",
  };
}