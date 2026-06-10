// =============================================================================
// components/layout/Sidebar.jsx
// Navigation sidebar — collapsible, grouped by tier, highlights active screen.
// Items marked complianceOnly are hidden from Standard Users.
// Items marked adminOnly are hidden from Standard Users AND Compliance users.
// =============================================================================

import { useCurrentUserRole } from "../../hooks/useCurrentUserRole";

// complianceOnly: hidden from Standard Users
// adminOnly: hidden from Standard Users AND Compliance
const NAV = [
  { id: "workhub",       label: "Work hub",                tier: 0 },
  { id: "doc",           label: "Document register",        tier: 1 },
  { id: "role",          label: "Role register",            tier: 1 },
  { id: "cal",           label: "Compliance calendar",      tier: 1 },
  { id: "contract",      label: "Contract register",        tier: 1 },
  { id: "lifecycle",     label: "Document lifecycle",       tier: 2, complianceOnly: true },
  { id: "extraction",    label: "Extraction review",        tier: 2, complianceOnly: true },
  { id: "assignment",    label: "Assignment & ownership",   tier: 2, complianceOnly: true },
  { id: "harmonisation", label: "Harmonisation",            tier: 2, complianceOnly: true },
  { id: "control",       label: "Control register",         tier: 3 },
  { id: "evidence",      label: "Evidence tracker",         tier: 3 },
  { id: "risk",          label: "Strategic risks",          tier: 3 },
  { id: "standards",     label: "Standards map",            tier: 3 },
  { id: "gap",           label: "Gap analysis",             tier: 4 },
];

const TIER_LABELS = {
  0: "Hub",
  1: "Foundations",
  2: "Extraction & lifecycle",
  3: "Core registers",
  4: "Aggregation",
};

const TIER_COLOURS = {
  0: "#534AB7",
  1: "#378ADD",
  2: "#BA7517",
  3: "#1D9E75",
  4: "#D85A30",
};

/**
 * @param {{ nav: string, setNav: Function, collapsed: boolean, setCollapsed: Function }} props
 */
export default function Sidebar({ nav, setNav, collapsed, setCollapsed }) {
  const { isCompliance, isAdmin } = useCurrentUserRole();

  // Filter nav items based on role
  const visibleNav = NAV.filter((item) => {
    if (item.adminOnly)      return isAdmin;
    if (item.complianceOnly) return isCompliance; // isCompliance is true for admins too
    return true;
  });

  const grouped = {};
  visibleNav.forEach((n) => {
    if (!grouped[n.tier]) grouped[n.tier] = [];
    grouped[n.tier].push(n);
  });

  return (
    <div
      style={{
        width: collapsed ? 48 : 200,
        borderRight: "0.5px solid var(--color-border-tertiary)",
        flexShrink: 0,
        padding: "10px 0",
        overflowY: "auto",
        transition: "width 0.15s ease",
        background: "var(--color-background-primary)",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "0 8px 8px",
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "space-between",
        }}
      >
        {!collapsed && (
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              paddingLeft: 4,
              letterSpacing: "-0.3px",
              color: "var(--color-text-primary)",
            }}
          >
            OrgOS
          </span>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          style={{
            background: "none",
            border: "1px solid #D0D0D0",
            borderRadius: 6,
            cursor: "pointer",
            padding: "3px 7px",
            fontSize: 11,
            color: "var(--color-text-secondary)",
          }}
        >
          {collapsed ? "→" : "←"}
        </button>
      </div>

      {/* Nav groups */}
      {[0, 1, 2, 3, 4].map((tier) => (
        <div key={tier} style={{ marginBottom: 2 }}>
          {/* Tier label */}
          {!collapsed && (
            <div
              style={{
                padding: "5px 12px 2px",
                fontSize: 9,
                color: "var(--color-text-tertiary)",
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <span
                style={{
                  width: 4,
                  height: 4,
                  borderRadius: "50%",
                  background: TIER_COLOURS[tier],
                  flexShrink: 0,
                }}
              />
              {TIER_LABELS[tier]}
            </div>
          )}

          {/* Nav items */}
          {(grouped[tier] || []).map((item) => (
            <div
              key={item.id}
              role="button"
              tabIndex={0}
              title={collapsed ? item.label : undefined}
              onClick={() => setNav(item.id)}
              onKeyDown={(e) => e.key === "Enter" && setNav(item.id)}
              style={{
                padding: collapsed ? "5px 0" : "5px 12px 5px 20px",
                fontSize: 12,
                cursor: "pointer",
                textAlign: collapsed ? "center" : "left",
                color:
                  nav === item.id
                    ? "var(--color-text-info)"
                    : "var(--color-text-secondary)",
                background:
                  nav === item.id
                    ? "var(--color-background-info)"
                    : "transparent",
                fontWeight: nav === item.id ? 500 : 400,
                borderRadius: 4,
                margin: "1px 4px",
                transition: "background 0.1s",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {collapsed ? item.label.charAt(0).toUpperCase() : item.label}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
