// =============================================================================
// components/layout/TopBar.jsx
// Top bar showing current user's name (resolved from MSAL) and logout button.
// =============================================================================

import { useMsal } from "@azure/msal-react";

/**
 * @param {{ currentScreen: string }} props
 */
export default function TopBar({ currentScreen }) {
  const { accounts, instance } = useMsal();
  const user = accounts[0];
  const displayName = user?.name || user?.username || "Unknown user";

  const handleLogout = () => {
    instance.logoutPopup({ postLogoutRedirectUri: window.location.origin });
  };

  return (
    <div
      style={{
        height: 44,
        borderBottom: "0.5px solid var(--color-border-tertiary)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 20px",
        background: "var(--color-background-primary)",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          fontSize: 12,
          color: "var(--color-text-secondary)",
          fontWeight: 500,
        }}
      >
        Dragnet Solutions · OrgOS
      </span>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span
          style={{
            fontSize: 12,
            color: "var(--color-text-secondary)",
          }}
        >
          {displayName}
        </span>
        <button
          onClick={handleLogout}
          style={{
            fontSize: 11,
            padding: "4px 10px",
            borderRadius: 6,
            border: "1px solid #D0D0D0",
            background: "transparent",
            color: "var(--color-text-secondary)",
            cursor: "pointer",
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
