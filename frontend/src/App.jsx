// =============================================================================
// App.jsx — OrgOS main application shell
// Handles: auth state (MSAL), navigation, layout, screen routing.
// Tier 1 screens: fully wired to FastAPI backend via React Query.
// Tier 2–4 screens: prototype components kept intact (will be wired in later tiers).
// =============================================================================

import { useState } from "react";
import { Routes, Route } from "react-router-dom";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { loginRequest } from "./authConfig.js";
import Sidebar from "./components/layout/Sidebar.jsx";
import TopBar from "./components/layout/TopBar.jsx";
import { useCurrentUserRole } from "./hooks/useCurrentUserRole.js";
import { AlertProvider } from "./components/shared/AlertModal.jsx";
import AccessDenied from "./pages/shared/AccessDenied.jsx";
import LifecycleFeedback from "./pages/LifecycleFeedback/index.jsx";
import LifecycleApprove from "./pages/LifecycleApprove/index.jsx";
import ChatButton from "./components/chat/ChatButton.jsx";
import ChatPanel from "./components/chat/ChatPanel.jsx";

// Tier 1 — wired pages
import DocumentRegister from "./pages/DocumentRegister/index.jsx";
import RoleRegister from "./pages/RoleRegister/index.jsx";
import ComplianceCalendar from "./pages/ComplianceCalendar/index.jsx";
import ContractRegister from "./pages/ContractRegister/index.jsx";
import DocumentLifecycle from "./pages/DocumentLifecycle/index.jsx";
import WorkHub from "./pages/WorkHub/index.jsx";
import ExtractionReview from "./pages/ExtractionReview/index.jsx";
import ControlRegister from "./pages/ControlRegister/index.jsx";
import EvidenceTracker from "./pages/EvidenceTracker/index.jsx";
import AssignmentOwnership from "./pages/AssignmentOwnership/index.jsx";
import Harmonisation from "./pages/Harmonisation/index.jsx";
import StrategicRisks from "./pages/StrategicRisks/index.jsx";
import StandardsMap from "./pages/StandardsMap/index.jsx";
import GapAnalysis from "./pages/GapAnalysis/index.jsx";

const SC = {
  Overdue: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  "Due soon": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Upcoming: { bg: "#F1EFE8", tx: "#444441", bd: "#B4B2A9" },
  Active: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Expired: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  "Expiring soon": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Accepted: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Submitted: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  "Under review": { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  Rejected: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Covered: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Partial: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  "Not covered": { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Open: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  "In progress": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Resolved: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Critical: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Major: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Minor: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  Preventive: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  Detective: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Corrective: { bg: "#FAECE7", tx: "#712B13", bd: "#F0997B" },
  Directive: { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  Extraction: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  Orphan: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Harmonisation: { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
};
const B = ({ l }) => {
  const s = SC[l] || { bg: "#F1EFE8", tx: "#444441", bd: "#B4B2A9" };
  return (
    <span
      style={{
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: 3,
        background: s.bg,
        color: s.tx,
        border: "0.5px solid " + s.bd,
        whiteSpace: "nowrap",
      }}
    >
      {l}
    </span>
  );
};
const Field2 = ({ l, v, color }) => (
  <div
    style={{
      display: "flex",
      justifyContent: "space-between",
      padding: "5px 0",
      borderBottom: "0.5px solid var(--color-border-tertiary)",
      fontSize: 12,
    }}
  >
    <span style={{ color: "var(--color-text-secondary)" }}>{l}</span>
    <span style={{ color: color || "var(--color-text-primary)" }}>{v}</span>
  </div>
);
const Link2 = ({ label, onClick }) => (
  <span
    onClick={onClick}
    style={{
      fontSize: 11,
      padding: "3px 8px",
      borderRadius: 5,
      background: "var(--color-background-info)",
      color: "var(--color-text-info)",
      cursor: "pointer",
      border: "0.5px solid var(--color-border-info)",
    }}
  >
    {label}
  </span>
);
const Btn2 = ({ label, primary, danger, onClick }) => (
  <button
    onClick={onClick}
    style={{
      padding: "9px 14px",
      fontSize: 12,
      borderRadius: 8,
      border: primary || danger ? "none" : "1.5px solid #C0C0C0",
      background: primary
        ? "#1D9E75"
        : danger
          ? "#A32D2D"
          : "var(--color-background-primary)",
      color: primary || danger ? "#fff" : "var(--color-text-primary)",
      cursor: "pointer",
      fontWeight: primary || danger ? 500 : 400,
    }}
  >
    {label}
  </button>
);

const GAPS = [
  {
    id: "GAP-001",
    finding: "No security event assessment procedure",
    std: "ISO 27001",
    cl: "A.5.25",
    sev: "Critical",
    status: "Open",
    to: "Bobby Ikazoboh",
    impact: "Mandatory — audit finding",
    cat: "Missing artefact",
    remediation: "Create event assessment procedure",
    targetDate: "2026-06-30",
    verification: "Internal audit confirms procedure in use",
  },
  {
    id: "GAP-005",
    finding: "No internal audit procedure",
    std: "ISO 9001",
    cl: "9.2",
    sev: "Critical",
    status: "Open",
    to: "Wani",
    impact: "Mandatory — audit finding",
    cat: "Missing artefact",
    remediation: "Create DRG-QI-PRO-IA-01-26",
    targetDate: "2026-05-31",
    verification: "Procedure approved and first audit conducted",
  },
  {
    id: "GAP-003",
    finding: "No internal staff screening procedure",
    std: "ISO 27001",
    cl: "A.6.1",
    sev: "Major",
    status: "Open",
    to: "CGS",
    impact: "Screening company without internal screening",
    cat: "Missing artefact",
    remediation: "Create DRG-HR-PRO-SCR-01-26",
    targetDate: "2026-07-31",
    verification: "Procedure approved",
  },
  {
    id: "GAP-002",
    finding: "No standalone information security policy",
    std: "ISO 27001",
    cl: "A.5.1",
    sev: "Major",
    status: "In progress",
    to: "Daniel Iwuagwu",
    impact: "Common audit finding",
    cat: "Structural anomaly",
    remediation: "Create DRG-ISMS-POL-ISP-01-26",
    targetDate: "2026-05-15",
    verification: "Document approved",
  },
];

const Risks = () => {
  const CC = {
    Partnership: "#1D9E75",
    Regulatory: "#993556",
    Reputational: "#534AB7",
  };
  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
            Strategic risk register
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            SWOT / PESTLE — curated by ExCo.
          </div>
        </div>
        <button
          style={{
            padding: "8px 16px",
            fontSize: 12,
            borderRadius: 8,
            border: "none",
            background: "#378ADD",
            color: "#fff",
            cursor: "pointer",
            fontWeight: 500,
            height: 34,
          }}
        >
          + Add risk
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {SRK.map((r) => {
          const bl = "3px solid " + (CC[r.cat] || "#888");
          return (
            <div
              key={r.id}
              style={{
                background: "var(--color-background-primary)",
                border: "1px solid #D0D0D0",
                borderRadius: 12,
                padding: "12px 14px",
                borderLeft: bl,
              }}
            >
              <div style={{ display: "flex", gap: 4, marginBottom: 6 }}>
                <span
                  style={{
                    fontSize: 10,
                    padding: "1px 6px",
                    borderRadius: 3,
                    background: "var(--color-background-secondary)",
                    color: CC[r.cat],
                  }}
                >
                  {r.cat}
                </span>
                <B l={r.tx} />
              </div>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  lineHeight: 1.4,
                  marginBottom: 4,
                }}
              >
                {r.stmt}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: "var(--color-text-secondary)",
                  marginBottom: 4,
                }}
              >
                {r.action}
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 11,
                }}
              >
                <span style={{ color: "var(--color-text-secondary)" }}>
                  {r.owner}
                </span>
                <span style={{ color: "var(--color-text-tertiary)" }}>
                  Reviewed {r.rev}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
};



// Simple table register for standards map

// ── Login screen ─────────────────────────────────────────────────────────────
function LoginScreen() {
  const { instance } = useMsal();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        background: "#f3f4f6",
        fontFamily: "var(--font-sans)",
      }}
    >
      <div
        style={{
          background: "#fff",
          padding: "48px 40px",
          borderRadius: 16,
          border: "1px solid #E0E0E0",
          textAlign: "center",
          maxWidth: 360,
          width: "100%",
        }}
      >
        <div
          style={{
            fontSize: 24,
            fontWeight: 700,
            letterSpacing: "-0.5px",
            marginBottom: 4,
          }}
        >
          OrgOS
        </div>
        <div
          style={{
            fontSize: 13,
            color: "var(--color-text-secondary)",
            marginBottom: 32,
          }}
        >
          Dragnet Solutions · GRC Platform
        </div>
        <button
          onClick={() => instance.loginPopup(loginRequest)}
          style={{
            width: "100%",
            padding: "12px",
            fontSize: 13,
            fontWeight: 600,
            borderRadius: 10,
            border: "none",
            background: "#1F4E79",
            color: "#fff",
            cursor: "pointer",
          }}
        >
          Sign in with Microsoft 365
        </button>
        <div
          style={{
            fontSize: 11,
            color: "var(--color-text-tertiary)",
            marginTop: 16,
          }}
        >
          Use your Dragnet Microsoft 365 account
        </div>
      </div>
    </div>
  );
}

// Routes that require at minimum the Compliance.Lead role
const COMPLIANCE_ONLY_ROUTES = new Set([
  "lifecycle",
  "extraction",
  "assignment",
  "harmonisation",
]);

// Human-readable names for AccessDenied screen
const ROUTE_NAMES = {
  lifecycle:     "Document Lifecycle",
  extraction:    "Extraction Review",
  assignment:    "Assignment & Ownership",
  harmonisation: "Harmonisation",
};

// ── Main app shell (all state-nav screens) ───────────────────────────────────
function OrgOSShell() {
  const isAuthenticated = useIsAuthenticated();
  const [nav, setNav] = useState("workhub");
  const [collapsed, setCollapsed] = useState(
    typeof window !== "undefined" && window.innerWidth < 768,
  );

  // Must be called unconditionally — hook runs regardless of auth state
  const { isCompliance } = useCurrentUserRole();

  // AUTH BYPASS — comment this block back in to re-enable login gate
  // if (!isAuthenticated) return <LoginScreen />;

  const go = (id) => setNav(id);

  const renderScreen = () => {
    // Guard compliance-only routes — Standard Users see AccessDenied
    // AUTH BYPASS — comment condition back in to re-enable role guard
    if (false && COMPLIANCE_ONLY_ROUTES.has(nav) && !isCompliance) {
      return (
        <AccessDenied
          pageName={ROUTE_NAMES[nav]}
          requiredRole="Compliance"
          onBack={() => go("workhub")}
        />
      );
    }

    switch (nav) {
      case "workhub":
        return <WorkHub go={go} />;
      case "doc":
        return <DocumentRegister go={go} />;
      case "role":
        return <RoleRegister />;
      case "cal":
        return <ComplianceCalendar />;
      case "contract":
        return <ContractRegister />;
      case "lifecycle":
        return <DocumentLifecycle />;
      case "extraction":
        return <ExtractionReview />;
      case "assignment":
        return <AssignmentOwnership />;
      case "harmonisation":
        return <Harmonisation />;
      case "control":
        return <ControlRegister />;
      case "risk":
        return <StrategicRisks />;
      case "evidence":
        return <EvidenceTracker />;
      case "standards":
        return <StandardsMap />;
      case "gap":
        return <GapAnalysis />;
      default:
        return null;
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        fontFamily: "var(--font-sans)",
        color: "var(--color-text-primary)",
        fontSize: 13,
      }}
    >
      <TopBar currentScreen={nav} />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar
          nav={nav}
          setNav={go}
          collapsed={collapsed}
          setCollapsed={setCollapsed}
        />
        <div
          style={{
            flex: 1,
            padding: "16px 20px",
            overflowY: "auto",
            overflowX: "auto",
          }}
        >
          {renderScreen()}
        </div>
      </div>
    </div>
  );
}

// ── Root — wires URL routes then falls back to the shell ─────────────────────
export default function OrgOS() {
  const [chatOpen, setChatOpen] = useState(false);
  const isAuthenticated = useIsAuthenticated();

  return (
    <AlertProvider>
      <Routes>
        {/* Standalone pages — no sidebar, accessible via direct URL from Teams cards */}
        <Route path="/lifecycle/feedback/:id" element={<LifecycleFeedback />} />
        <Route path="/lifecycle/approve/:id"  element={<LifecycleApprove />} />
        {/* All other paths → full app shell with sidebar */}
        <Route path="*" element={<OrgOSShell />} />
      </Routes>

      {/* Global AI chat — AUTH BYPASS: always show; restore {isAuthenticated && (...)} to re-enable */}
      {(true /* isAuthenticated */) && (
        <>
          <ChatButton onClick={() => setChatOpen(true)} />
          <ChatPanel isOpen={chatOpen} onClose={() => setChatOpen(false)} />
        </>
      )}
    </AlertProvider>
  );
}
