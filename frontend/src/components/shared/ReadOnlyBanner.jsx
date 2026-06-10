// =============================================================================
// components/shared/ReadOnlyBanner.jsx
// Shown at the top of pages where the current user has read-only access.
// Appears for Standard Users on all write-capable registers.
// =============================================================================

export default function ReadOnlyBanner({ message }) {
  return (
    <div
      style={{
        padding: "9px 14px",
        background: "#F1EFE8",
        border: "1px solid #B4B2A9",
        borderRadius: 10,
        marginBottom: 14,
        fontSize: 12,
        color: "#595952",
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      <span style={{ fontSize: 14 }}>📋</span>
      <span>
        {message || "You have read-only access to this register. Contact the Compliance team to request changes."}
      </span>
    </div>
  );
}
