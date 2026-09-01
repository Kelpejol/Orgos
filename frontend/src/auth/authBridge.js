// =============================================================================
// auth/authBridge.js — Tier-1 standalone session bridge to the Dragnet ERP shell.
// Replaces MSAL entirely. No token ever touches this app directly — the
// erp_auth HttpOnly cookie is set by the ERP backend and read by OrgOS's own
// backend. This module only ever talks to OrgOS's own /api/auth/* routes.
// =============================================================================

const SHELL_URL = import.meta.env.VITE_ERP_URL;
const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Check the erp_auth cookie via OrgOS's own backend — covers new tabs and
// fresh visits (the cookie itself is HttpOnly, unreadable from JS directly).
export async function verifySession() {
  try {
    const res = await fetch(`${API_BASE}/api/auth/session`, { credentials: "include" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// No session found — redirect to the ERP shell with the current URL as the
// return destination. The shell authenticates, sets the cookie, and bounces
// back here with no token ever appearing in the URL.
export function redirectToShell() {
  const currentUrl = window.location.href;
  window.location.href = `${SHELL_URL}?redirect=${encodeURIComponent(currentUrl)}`;
}

// Clear the local session and hand off to the ERP's own logout flow.
export function logoutToShell() {
  fetch(`${API_BASE}/api/auth/session`, { method: "DELETE", credentials: "include" }).catch(() => {});
  window.location.href = `${SHELL_URL}/logout`;
}
