// =============================================================================
// pages/shared/AccessDenied.jsx
// Full-page access denied screen shown when a Standard User navigates
// directly to a Compliance-only or Admin-only page.
// =============================================================================

export default function AccessDenied({ pageName, requiredRole = "Compliance", onBack }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
      }}
    >
      <div
        style={{
          maxWidth: 420,
          width: "100%",
          padding: "36px 32px",
          background: "var(--color-background-primary)",
          border: "1.5px solid #D0D0D0",
          borderRadius: 16,
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: 36, marginBottom: 12 }}>🔒</div>
        <div
          style={{
            fontSize: 15,
            fontWeight: 700,
            marginBottom: 8,
            color: "var(--color-text-primary)",
          }}
        >
          Access restricted
        </div>
        {pageName && (
          <div
            style={{
              fontSize: 13,
              color: "var(--color-text-secondary)",
              marginBottom: 16,
              lineHeight: 1.5,
            }}
          >
            <strong>{pageName}</strong> is available to{" "}
            {requiredRole === "Admin"
              ? "OrgOS Admins only"
              : "Compliance Officers and OrgOS Admins"}.
          </div>
        )}
        <div
          style={{
            padding: "10px 14px",
            background: "#F1EFE8",
            borderRadius: 8,
            fontSize: 12,
            color: "#595952",
            marginBottom: 20,
            lineHeight: 1.5,
          }}
        >
          If you need access to this feature, contact your OrgOS Admin to have the{" "}
          <strong>
            {requiredRole === "Admin" ? "OrgOS.Admin" : "Compliance.Lead"}
          </strong>{" "}
          role assigned to your account.
        </div>
        <button
          onClick={onBack}
          style={{
            padding: "9px 20px",
            fontSize: 13,
            borderRadius: 9,
            border: "1.5px solid #D0D0D0",
            background: "transparent",
            color: "var(--color-text-secondary)",
            cursor: "pointer",
            fontWeight: 500,
          }}
        >
          ← Go to Work Hub
        </button>
      </div>
    </div>
  );
}
