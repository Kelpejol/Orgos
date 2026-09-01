// =============================================================================
// context/AuthContext.jsx — session identity, populated once at boot from
// GET /api/auth/session (see main.jsx). Replaces the old MSAL account object
// as the single source of truth for who's signed in and what they can do.
// =============================================================================

import { createContext, useContext } from "react";

const AuthContext = createContext(null);

export function AuthProvider({ children, user, roles, refreshToken }) {
  return (
    <AuthContext.Provider value={{ user, roles, refreshToken }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return {
    userName: ctx.user.name,
    userEmail: ctx.user.email,
    userOid: ctx.user.oid,
    roles: ctx.roles,
    hasRole: (role) => ctx.roles.includes(role.toLowerCase()),
    refreshToken: ctx.refreshToken,
  };
}
