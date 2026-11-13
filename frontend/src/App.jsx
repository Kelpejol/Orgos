// =============================================================================
// App.jsx — OrgOS main application shell
// Handles: navigation, layout, screen routing. Auth is resolved once at boot
// by main.jsx (Dragnet ERP session cookie) before this component ever renders.
// Every screen is wired to the FastAPI backend through React Query.
// =============================================================================

import { useEffect, useState } from "react";
import { Routes, Route } from "react-router-dom";
import Navbar from "./components/layout/Navbar.jsx";
import { useCurrentUserRole } from "./hooks/useCurrentUserRole.js";
import { AlertProvider } from "./components/shared/AlertModal.jsx";
import AccessDenied from "./pages/shared/AccessDenied.jsx";
import LifecycleFeedback from "./pages/LifecycleFeedback/index.jsx";
import ReadDocument from "./pages/ReadDocument/index.jsx";
import LifecycleApprove from "./pages/LifecycleApprove/index.jsx";
import ChatButton from "./components/chat/ChatButton.jsx";
import ChatPanel from "./components/chat/ChatPanel.jsx";

// Tier 1 — wired pages
import DocumentRegister from "./pages/DocumentRegister/index.jsx";
import ComplianceCalendar from "./pages/ComplianceCalendar/index.jsx";
import ContractRegister from "./pages/ContractRegister/index.jsx";
import DocumentLifecycle from "./pages/DocumentLifecycle/index.jsx";
import WorkHub from "./pages/WorkHub/index.jsx";
import ExtractionReview from "./pages/ExtractionReview/index.jsx";
import ControlRegister from "./pages/ControlRegister/index.jsx";
import RecordTracker from "./pages/RecordTracker/index.jsx";
import AssignmentOwnership from "./pages/AssignmentOwnership/index.jsx";
import Harmonisation from "./pages/Harmonisation/index.jsx";
import DocumentStandards from "./pages/DocumentStandards/index.jsx";
import StrategicRisks from "./pages/StrategicRisks/index.jsx";
import StandardsMap from "./pages/StandardsMap/index.jsx";
import GapAnalysis from "./pages/GapAnalysis/index.jsx";
import OrgRoles from "./pages/OrgRoles/index.jsx";

// Routes that require at minimum the Compliance role
const COMPLIANCE_ONLY_ROUTES = new Set([
  "extraction",
  "assignment",
  "harmonisation",
  "org-roles",
]);

// Human-readable names for AccessDenied screen
const ROUTE_NAMES = {
  lifecycle:     "Document Lifecycle",
  extraction:    "Extraction Review",
  assignment:    "Assignment & Ownership",
  harmonisation: "Harmonisation",
  "org-roles":   "Org Roles",
};

// ── Main app shell (all state-nav screens) ───────────────────────────────────
function OrgOSShell() {
  const [nav, setNav] = useState("workhub");
  const [documentFocus, setDocumentFocus] = useState("");
  const [recordFocus, setRecordFocus] = useState("");

  const { isCompliance } = useCurrentUserRole();

  const go = (id) => { setDocumentFocus(""); setRecordFocus(""); setNav(id); };

  // Other screens can send the user somewhere (e.g. a check's "Create role" opens Org Roles).
  useEffect(() => {
    const onNavigate = (e) => {
      if (!e.detail?.to) return;
      setDocumentFocus(e.detail.documentCode || "");
      setRecordFocus(e.detail.recordId || "");
      setNav(e.detail.to);
    };
    window.addEventListener("orgos:navigate", onNavigate);
    return () => window.removeEventListener("orgos:navigate", onNavigate);
  }, []);

  const renderScreen = () => {
    // Guard compliance-only routes — Standard Users see AccessDenied
    if (COMPLIANCE_ONLY_ROUTES.has(nav) && !isCompliance) {
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
      case "cal":
        return <ComplianceCalendar />;
      case "contract":
        return <ContractRegister />;
      case "lifecycle":
        return <DocumentLifecycle focusDocumentCode={documentFocus} onClearFocus={() => setDocumentFocus("")} />;
      case "extraction":
        return <ExtractionReview />;
      case "assignment":
        return <AssignmentOwnership />;
      case "harmonisation":
        return <Harmonisation />;
      case "doc-standards":
        return <DocumentStandards />;
      case "control":
        return <ControlRegister />;
      case "risk":
        return <StrategicRisks />;
      case "records":
        return <RecordTracker focusRecordId={recordFocus} onClearFocus={() => setRecordFocus("")} />;
      case "standards":
        return <StandardsMap />;
      case "gap":
        return <GapAnalysis />;
      case "org-roles":
        return <OrgRoles />;
      default:
        return null;
    }
  };

  return (
    <div
      style={{
        fontFamily: "var(--font-ui)",
        color: "var(--color-text-primary)",
        fontSize: 13,
      }}
    >
      <Navbar nav={nav} setNav={go} />
      <main
        style={{
          minHeight: "100vh",
          width: "100%",
          maxWidth: "var(--page-max-7xl)",
          margin: "0 auto",
          padding: "16px 20px",
          paddingTop: "calc(var(--navbar-height) + 16px)",
          boxSizing: "border-box",
          overflowX: "auto",
        }}
      >
        {renderScreen()}
      </main>
    </div>
  );
}

// ── Root — wires URL routes then falls back to the shell ─────────────────────
export default function OrgOS() {
  const [chatOpen, setChatOpen] = useState(false);

  return (
    <AlertProvider>
      <Routes>
        {/* Standalone pages — no sidebar, accessible via direct URL from Teams cards */}
        {/* Linked from Teams — read a document without opening the editable
            source. See pages/ReadDocument. */}
        <Route path="/read/:id" element={<ReadDocument />} />
        <Route path="/read" element={<ReadDocument />} />
        <Route path="/lifecycle/feedback/:id" element={<LifecycleFeedback />} />
        <Route path="/lifecycle/approve/:id"  element={<LifecycleApprove />} />
        {/* All other paths → full app shell with sidebar */}
        <Route path="*" element={<OrgOSShell />} />
      </Routes>

      {/* Global AI chat — visible on all pages (session is already resolved by main.jsx) */}
      <ChatButton onClick={() => setChatOpen(true)} />
      <ChatPanel isOpen={chatOpen} onClose={() => setChatOpen(false)} />
    </AlertProvider>
  );
}
