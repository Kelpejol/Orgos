// =============================================================================
// components/shared/OwnerField.jsx
// Auto-resolved owner field — reads the logged-in user's OID from MSAL.
// The input is greyed out and read-only. No manual entry.
// Used across all four Tier 1 register forms.
// =============================================================================

import { useCurrentUser } from "../../hooks/useCurrentUser.js";
import { useState } from "react";

/**
 * @param {{ onResolve: Function }} props
 * onResolve is called immediately with the OID so the parent form
 * can store it in its state without any user interaction.
 */
export default function OwnerField({ onResolve }) {
  const { oid, name, email } = useCurrentUser();

  // Call onResolve once on mount so parent form has the OID
  // without needing the user to do anything
  const [resolved, setResolved] = useState(false);
  
  if (!resolved && oid && onResolve) {
    onResolve(oid);
    setResolved(true);
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <label style={{
        display: "block", fontSize: 11, fontWeight: 500,
        color: "var(--color-text-secondary)", marginBottom: 4,
        textTransform: "uppercase", letterSpacing: "0.4px",
      }}>
        Owner
      </label>
      <div style={{
        width: "100%", fontSize: 13, padding: "8px 10px",
        borderRadius: 8, border: "1.5px solid #E0E0E0",
        background: "var(--color-background-secondary)",
        color: "var(--color-text-secondary)",
        boxSizing: "border-box",
        display: "flex", justifyContent: "space-between",
        alignItems: "center",
      }}>
        <span>{name || email || "Loading..."}</span>
        <span style={{
          fontSize: 10, padding: "2px 6px", borderRadius: 4,
          background: "#E1F5EE", color: "#085041",
          border: "0.5px solid #5DCAA5", fontWeight: 500,
        }}>
          Auto-resolved from Microsoft 365
        </span>
      </div>
      <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 3 }}>
        {oid || "OID not available — ensure you are signed in"}
      </div>
    </div>
  );
}