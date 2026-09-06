// =============================================================================
// components/layout/Navbar.jsx
// Fixed top navbar matching the Dragnet ERP shell's exact navbar spec
// (docs.local/ERP_components.md) — brand left, centred nav with hover
// dropdowns, user avatar + menu on the right. Replaces Sidebar + TopBar.
// OrgOS runs standalone (not federated), so this replicates the shell's
// look by hand rather than inheriting it.
// =============================================================================

import { useEffect, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faHouse,
  faGauge,
  faLayerGroup,
  faFileLines,
  faCalendarDays,
  faFileContract,
  faUsers,
  faArrowsRotate,
  faMagnifyingGlass,
  faUserGroup,
  faCodeCompare,
  faShieldHalved,
  faFolderOpen,
  faTriangleExclamation,
  faMap,
  faChartLine,
  faArrowRightFromBracket,
} from "@fortawesome/free-solid-svg-icons";
import { ChevronDown } from "lucide-react";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import { logoutToShell, SHELL_URL } from "../../auth/authBridge.js";

// A short grace period, not the ERP shell's documented 2.5s — that value
// reads as "stuck open" in practice for OrgOS's shorter dropdown lists.
// Kept non-zero only to survive the trigger→panel gap without flicker.
const DROPDOWN_CLOSE_DELAY_MS = 150;

// ── Nav structure — flat items and dropdown groups, mirroring the old
// Sidebar's tiers but as the ERP's flat-item + hover-dropdown pattern ──────
const NAV_GROUPS = [
  { type: "external", id: "home", label: "Home", icon: faHouse, href: SHELL_URL },
  { type: "flat", id: "workhub", label: "Dashboard", icon: faGauge },
  {
    type: "dropdown",
    id: "foundations",
    label: "Foundations",
    icon: faLayerGroup,
    children: [
      { id: "doc", label: "Document Register", icon: faFileLines },
      { id: "cal", label: "Compliance Calendar", icon: faCalendarDays },
      { id: "contract", label: "Contract Register", icon: faFileContract },
      { id: "org-roles", label: "Org Roles", icon: faUsers, complianceOnly: true },
    ],
  },
  {
    type: "dropdown",
    id: "extraction-lifecycle",
    label: "Extraction & Lifecycle",
    icon: faArrowsRotate,
    complianceOnly: true,
    children: [
      { id: "lifecycle", label: "Document Lifecycle", icon: faArrowsRotate },
      { id: "extraction", label: "Extraction Review", icon: faMagnifyingGlass },
      { id: "assignment", label: "Assignment & Ownership", icon: faUserGroup },
      { id: "harmonisation", label: "Harmonisation", icon: faCodeCompare },
    ],
  },
  {
    type: "dropdown",
    id: "core-registers",
    label: "Core Registers",
    icon: faShieldHalved,
    children: [
      { id: "control", label: "Control Register", icon: faShieldHalved },
      { id: "evidence", label: "Evidence Tracker", icon: faFolderOpen },
      { id: "risk", label: "Strategic Risks", icon: faTriangleExclamation },
      { id: "standards", label: "Standards Map", icon: faMap },
    ],
  },
  { type: "flat", id: "gap", label: "Gap Analysis", icon: faChartLine },
];

function initialsFor(name, email) {
  const source = (name || "").trim() || (email || "").trim();
  if (!source) return "?";
  return source
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

// ── Desktop dropdown ─────────────────────────────────────────────────────
function NavDropdown({ group, nav, setNav, isCompliance }) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef(null);

  const visibleChildren = group.children.filter(
    (c) => !c.complianceOnly || isCompliance,
  );
  if (visibleChildren.length === 0) return null;

  const isActive = visibleChildren.some((c) => c.id === nav);

  const openNow = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const closeSoon = () => {
    closeTimer.current = setTimeout(() => setOpen(false), DROPDOWN_CLOSE_DELAY_MS);
  };

  useEffect(() => () => closeTimer.current && clearTimeout(closeTimer.current), []);

  return (
    <div
      style={{ position: "relative" }}
      onMouseEnter={openNow}
      onMouseLeave={closeSoon}
      onFocus={openNow}
      onBlur={closeSoon}
    >
      <button
        className={"navbar-link" + (isActive ? " navbar-link-active" : "")}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "7px 10px",
          borderRadius: 6,
          fontSize: 13,
          fontWeight: 500,
          fontFamily: "var(--font-ui)",
          background: isActive ? "rgba(196,30,30,.22)" : "transparent",
          color: isActive ? "#fff" : "rgba(255,255,255,.62)",
          cursor: "pointer",
          position: "relative",
        }}
      >
        <FontAwesomeIcon
          icon={group.icon}
          style={{ width: 13, height: 13, opacity: isActive ? 1 : 0.68 }}
        />
        <span>{group.label}</span>
        <ChevronDown
          size={11}
          style={{
            opacity: 0.45,
            transition: "transform 0.15s",
            transform: open ? "rotate(180deg)" : "none",
          }}
        />
        {isActive && (
          <span
            style={{
              content: "",
              position: "absolute",
              bottom: -1,
              left: 8,
              right: 8,
              height: 2,
              background: "#f87171",
              borderRadius: "2px 2px 0 0",
            }}
          />
        )}
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            minWidth: 175,
            background: "var(--c-navy-mid)",
            border: "1px solid rgba(255,255,255,.1)",
            boxShadow: "var(--shadow-xl)",
            borderRadius: "var(--radius-md)",
            padding: 6,
            zIndex: 200,
          }}
        >
          {visibleChildren.map((child) => {
            const active = child.id === nav;
            return (
              <div
                key={child.id}
                role="button"
                tabIndex={0}
                className={"navbar-link" + (active ? " navbar-link-active" : "")}
                onClick={() => {
                  setNav(child.id);
                  setOpen(false);
                }}
                onKeyDown={(e) => e.key === "Enter" && setNav(child.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "7px 10px",
                  borderRadius: 6,
                  fontSize: 13,
                  fontWeight: 500,
                  fontFamily: "var(--font-ui)",
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  background: active ? "rgba(196,30,30,.2)" : "transparent",
                  color: active ? "#fff" : "rgba(255,255,255,.62)",
                }}
              >
                <FontAwesomeIcon
                  icon={child.icon}
                  style={{
                    width: 13,
                    height: 13,
                    color: active ? "#fca5a5" : undefined,
                    opacity: active ? 1 : 0.68,
                  }}
                />
                {child.label}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── User avatar + menu ───────────────────────────────────────────────────
function UserSection({ name, email, roleLabel }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);
  const initials = initialsFor(name, email);

  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open]);

  const avatarGradient = {
    background: "linear-gradient(135deg, #c41e1e, #8b0f0f)",
    border: "1.5px solid rgba(255,255,255,.15)",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#fff",
    fontWeight: 700,
    flexShrink: 0,
  };

  return (
    <div ref={menuRef} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((p) => !p)}
        title={name || email}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          background: "transparent",
          cursor: "pointer",
          padding: 4,
          borderRadius: "var(--radius-full)",
        }}
      >
        <div style={{ ...avatarGradient, width: 30, height: 30, fontSize: 11 }}>
          {initials}
        </div>
        <ChevronDown size={11} style={{ opacity: 0.45, color: "#fff" }} />
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            minWidth: 220,
            background: "var(--c-navy-mid)",
            border: "1px solid rgba(255,255,255,.1)",
            boxShadow: "var(--shadow-xl)",
            borderRadius: "var(--radius-md)",
            padding: 8,
            zIndex: 200,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px" }}>
            <div style={{ ...avatarGradient, width: 32, height: 32, fontSize: 12 }}>
              {initials}
            </div>
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: "rgba(255,255,255,.92)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {name || "Unknown user"}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: "rgba(255,255,255,.35)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {email}
              </div>
              {roleLabel && (
                <div style={{ fontSize: 11, color: "rgba(255,255,255,.5)", marginTop: 2 }}>
                  {roleLabel}
                </div>
              )}
            </div>
          </div>

          <div style={{ height: 1, background: "rgba(255,255,255,.1)", margin: "6px 0" }} />

          <button
            onClick={logoutToShell}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 8px",
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 500,
              fontFamily: "var(--font-ui)",
              background: "transparent",
              color: "rgba(248,113,113,.85)",
              cursor: "pointer",
              textAlign: "left",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "rgba(239,68,68,.1)";
              e.currentTarget.style.color = "#f87171";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "rgba(248,113,113,.85)";
            }}
          >
            <FontAwesomeIcon icon={faArrowRightFromBracket} style={{ width: 13, height: 13 }} />
            <span>Sign Out</span>
          </button>
        </div>
      )}
    </div>
  );
}

// ── Mobile nav panel ─────────────────────────────────────────────────────
function MobileNav({ nav, setNav, isCompliance, onNavigate }) {
  return (
    <nav
      style={{
        position: "fixed",
        top: "var(--navbar-height)",
        left: 0,
        right: 0,
        background: "var(--c-navy)",
        borderTop: "1px solid rgba(255,255,255,.08)",
        boxShadow: "var(--shadow-lg)",
        padding: "8px 12px 16px",
        zIndex: 99,
        maxHeight: "calc(100vh - var(--navbar-height))",
        overflowY: "auto",
      }}
    >
      {NAV_GROUPS.filter((g) => !g.complianceOnly || isCompliance).map((group) => {
        if (group.type === "external") {
          return (
            <a
              key={group.id}
              href={group.href}
              className="navbar-link"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 8px",
                borderRadius: 6,
                fontSize: 14,
                fontWeight: 500,
                textDecoration: "none",
                color: "rgba(255,255,255,.62)",
              }}
            >
              <FontAwesomeIcon icon={group.icon} style={{ width: 14, height: 14 }} />
              {group.label}
            </a>
          );
        }
        if (group.type === "flat") {
          const active = group.id === nav;
          return (
            <div
              key={group.id}
              role="button"
              tabIndex={0}
              className={"navbar-link" + (active ? " navbar-link-active" : "")}
              onClick={() => onNavigate(group.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 8px",
                borderRadius: 6,
                fontSize: 14,
                fontWeight: 500,
                background: active ? "rgba(196,30,30,.22)" : "transparent",
                color: active ? "#fff" : "rgba(255,255,255,.62)",
              }}
            >
              <FontAwesomeIcon icon={group.icon} style={{ width: 14, height: 14 }} />
              {group.label}
            </div>
          );
        }
        const visibleChildren = group.children.filter((c) => !c.complianceOnly || isCompliance);
        if (visibleChildren.length === 0) return null;
        return (
          <div key={group.id} style={{ marginTop: 6 }}>
            <div
              style={{
                fontSize: 11,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "rgba(255,255,255,.35)",
                padding: "6px 8px 2px",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <FontAwesomeIcon icon={group.icon} style={{ width: 11, height: 11 }} />
              {group.label}
            </div>
            {visibleChildren.map((child) => {
              const active = child.id === nav;
              return (
                <div
                  key={child.id}
                  role="button"
                  tabIndex={0}
                  className={"navbar-link" + (active ? " navbar-link-active" : "")}
                  onClick={() => onNavigate(child.id)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "9px 8px 9px 20px",
                    borderRadius: 6,
                    fontSize: 13,
                    fontWeight: 500,
                    background: active ? "rgba(196,30,30,.2)" : "transparent",
                    color: active ? "#fff" : "rgba(255,255,255,.5)",
                  }}
                >
                  <FontAwesomeIcon
                    icon={child.icon}
                    style={{ width: 13, height: 13, color: active ? "#fca5a5" : undefined }}
                  />
                  {child.label}
                </div>
              );
            })}
          </div>
        );
      })}
    </nav>
  );
}

// ── Main navbar ──────────────────────────────────────────────────────────
export default function Navbar({ nav, setNav }) {
  const { name, email, roleLabel, isCompliance } = useCurrentUserRole();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [logoFailed, setLogoFailed] = useState(false);

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth > 768) setMobileOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const go = (id) => {
    setNav(id);
    setMobileOpen(false);
  };

  return (
    <>
      <nav
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          height: "var(--navbar-height)",
          background: "var(--c-navy)",
          boxShadow: "0 1px 0 rgba(255,255,255,.06), 0 2px 16px rgba(0,0,0,.2)",
          zIndex: 100,
          fontFamily: "var(--font-ui)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            position: "relative",
            height: "100%",
            padding: "0 16px",
          }}
        >
          {/* Brand */}
          <a
            href="/"
            onClick={(e) => {
              e.preventDefault();
              go("workhub");
            }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              textDecoration: "none",
              paddingRight: 20,
              borderRight: "1px solid rgba(255,255,255,.08)",
              marginRight: 6,
              flexShrink: 0,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.82")}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
          >
            {!logoFailed && (
              <img
                src="/dragnet-logo.png"
                alt="Dragnet"
                onError={() => setLogoFailed(true)}
                style={{ width: 30, height: 30, objectFit: "contain", borderRadius: 4 }}
              />
            )}
            <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: "-0.01em", color: "#fff" }}>
              OrgOS
            </span>
          </a>

          {/* Centred nav — desktop only */}
          <div
            className="navbar-desktop-links"
            style={{
              position: "absolute",
              left: "50%",
              transform: "translateX(-50%)",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {NAV_GROUPS.filter((g) => !g.complianceOnly || isCompliance).map((group) => {
              if (group.type === "external") {
                return (
                  <a
                    key={group.id}
                    href={group.href}
                    className="navbar-link"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "7px 10px",
                      borderRadius: 6,
                      fontSize: 13,
                      fontWeight: 500,
                      fontFamily: "var(--font-ui)",
                      textDecoration: "none",
                      color: "rgba(255,255,255,.62)",
                      cursor: "pointer",
                    }}
                  >
                    <FontAwesomeIcon icon={group.icon} style={{ width: 13, height: 13, opacity: 0.68 }} />
                    <span>{group.label}</span>
                  </a>
                );
              }
              if (group.type === "flat") {
                const isActive = nav === group.id;
                return (
                  <button
                    key={group.id}
                    onClick={() => go(group.id)}
                    className={"navbar-link" + (isActive ? " navbar-link-active" : "")}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "7px 10px",
                      borderRadius: 6,
                      fontSize: 13,
                      fontWeight: 500,
                      fontFamily: "var(--font-ui)",
                      background: isActive ? "rgba(196,30,30,.22)" : "transparent",
                      color: isActive ? "#fff" : "rgba(255,255,255,.62)",
                      cursor: "pointer",
                      position: "relative",
                    }}
                  >
                    <FontAwesomeIcon
                      icon={group.icon}
                      style={{ width: 13, height: 13, opacity: isActive ? 1 : 0.68 }}
                    />
                    <span>{group.label}</span>
                    {isActive && (
                      <span
                        style={{
                          position: "absolute",
                          bottom: -1,
                          left: 8,
                          right: 8,
                          height: 2,
                          background: "#f87171",
                          borderRadius: "2px 2px 0 0",
                        }}
                      />
                    )}
                  </button>
                );
              }
              return (
                <NavDropdown
                  key={group.id}
                  group={group}
                  nav={nav}
                  setNav={go}
                  isCompliance={isCompliance}
                />
              );
            })}
          </div>

          {/* Right zone */}
          <div
            className="navbar-desktop-right"
            style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}
          >
            <UserSection name={name} email={email} roleLabel={roleLabel} />
          </div>

          {/* Hamburger — mobile only */}
          <button
            className="navbar-hamburger"
            aria-label="Toggle navigation"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((p) => !p)}
            style={{
              display: "none",
              marginLeft: "auto",
              width: 32,
              height: 32,
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 5,
              background: "transparent",
              cursor: "pointer",
            }}
          >
            <span
              style={{
                width: 18,
                height: 2,
                background: "#fff",
                borderRadius: 2,
                transition: "transform 0.2s, opacity 0.2s",
                transform: mobileOpen ? "translateY(7px) rotate(45deg)" : "none",
              }}
            />
            <span
              style={{
                width: 18,
                height: 2,
                background: "#fff",
                borderRadius: 2,
                opacity: mobileOpen ? 0 : 1,
                transition: "opacity 0.2s",
              }}
            />
            <span
              style={{
                width: 18,
                height: 2,
                background: "#fff",
                borderRadius: 2,
                transition: "transform 0.2s",
                transform: mobileOpen ? "translateY(-7px) rotate(-45deg)" : "none",
              }}
            />
          </button>
        </div>
      </nav>

      {mobileOpen && (
        <>
          <div
            onClick={() => setMobileOpen(false)}
            style={{
              position: "fixed",
              top: "var(--navbar-height)",
              left: 0,
              right: 0,
              bottom: 0,
              background: "rgba(0,0,0,.5)",
              zIndex: 98,
            }}
          />
          <MobileNav nav={nav} setNav={go} isCompliance={isCompliance} onNavigate={go} />
        </>
      )}

      {/* Hover + responsive rules — inline component styles can't express
          :hover or media queries, so this is the CSS this component needs. */}
      <style>{`
        .navbar-link:hover:not(.navbar-link-active) {
          background: rgba(255,255,255,.07) !important;
          color: rgba(255,255,255,.92) !important;
        }
        .navbar-link:hover:not(.navbar-link-active) svg {
          opacity: 1 !important;
        }
        @media (max-width: 768px) {
          .navbar-desktop-links, .navbar-desktop-right { display: none !important; }
          .navbar-hamburger { display: flex !important; }
        }
      `}</style>
    </>
  );
}
