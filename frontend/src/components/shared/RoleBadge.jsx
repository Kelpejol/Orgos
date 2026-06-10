// =============================================================================
// components/shared/RoleBadge.jsx
// Small chip displayed in the TopBar next to the user's name.
// Colour-coded by role so users always know their access level.
// =============================================================================

const ROLE_STYLES = {
  Admin: {
    background: "#EEEDFE",
    color: "#3C3489",
    border: "0.5px solid #AFA9EC",
    label: "Admin",
  },
  Compliance: {
    background: "#E6F1FB",
    color: "#0C447C",
    border: "0.5px solid #85B7EB",
    label: "Compliance",
  },
  "Standard User": {
    background: "#F1EFE8",
    color: "#595952",
    border: "0.5px solid #B4B2A9",
    label: "Standard User",
  },
};

export default function RoleBadge({ roleLabel }) {
  const style = ROLE_STYLES[roleLabel] || ROLE_STYLES["Standard User"];

  return (
    <span
      style={{
        fontSize: 10,
        padding: "2px 8px",
        borderRadius: 4,
        fontWeight: 600,
        letterSpacing: "0.2px",
        background: style.background,
        color: style.color,
        border: style.border,
        whiteSpace: "nowrap",
      }}
    >
      {style.label}
    </span>
  );
}
