// =============================================================================
// pages/AIReviewQueue/index.jsx
// AI Review Queue — three tabs: Extraction, Orphan, Harmonisation.
// All items share the same card anatomy and six decision actions.
// Every decision requires a mandatory rationale text entry.
// Wired to the AI Review Queue SharePoint list via the backend API.
// Depends on: hooks/useGrc.js, components/shared/StatusBadge, Forms
// =============================================================================

import { useState, useMemo } from "react";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import {
  LoadingState,
  ErrorState,
  EmptyState,
} from "../../components/shared/LoadingState.jsx";
import UserSearchField from "../../components/shared/UserSearchField.jsx";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAlert } from "../../components/shared/AlertModal.jsx";
import apiClient from "../../api/grcApi.js";

// =============================================================================
//  API calls
// =============================================================================

const queueApi = {
  list: (itemType) =>
    apiClient
      .get("/api/v1/queue/items", {
        params: itemType ? { item_type: itemType } : {},
      })
      .then((r) => r.data),

  decide: (itemId, decision, rationale) =>
    apiClient
      .patch(`/api/v1/queue/items/${itemId}/decide`, { decision, rationale })
      .then((r) => r.data),
};

// =============================================================================
//  Hooks
// =============================================================================

function useQueueItems(itemType) {
  return useQuery({
    queryKey: ["queue", itemType],
    queryFn: () => queueApi.list(itemType),
    staleTime: 30_000,
  });
}

function useDecide() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, decision, rationale }) =>
      queueApi.decide(itemId, decision, rationale),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

// =============================================================================
//  Constants
// =============================================================================

const DECISIONS = [
  { key: "Accept", label: "Accept", primary: true },
  { key: "Edit and Accept", label: "Edit & accept", primary: false },
  { key: "Reject", label: "Reject", danger: true },
  { key: "Route to Owner", label: "Route to owner", primary: false },
  { key: "Mark False Positive", label: "Mark false positive", primary: false },
  { key: "Request Second Review", label: "Request 2nd review", primary: false },
];

const CONFIDENCE_THRESHOLDS = {
  HIGH: 0.8,
  MEDIUM: 0.6,
};

// =============================================================================
//  Shared components
// =============================================================================

const ConfidenceBar = ({ score }) => {
  const pct = Math.round((score || 0) * 100);
  const color = pct >= 80 ? "#1D9E75" : pct >= 60 ? "#BA7517" : "#A32D2D";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          flex: 1,
          height: 5,
          borderRadius: 3,
          background: "var(--color-border-tertiary)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: color,
            borderRadius: 3,
          }}
        />
      </div>
      <span style={{ fontSize: 10, fontWeight: 600, color, minWidth: 28 }}>
        {pct}%
      </span>
    </div>
  );
};

const EvidencePanel = ({ item }) => {
  if (!item.EvidenceType && !item.EvidenceDescription) return null;

  const hasUndefined = item.EvidenceUndefined;

  return (
    <div
      style={{
        padding: "10px 12px",
        background: hasUndefined ? "#FAEEDA" : "#EEEDFE",
        borderRadius: 8,
        marginTop: 10,
        border: `0.5px solid ${hasUndefined ? "#FAC775" : "#AFA9EC"}`,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: hasUndefined ? "#633806" : "#3C3489",
          marginBottom: 6,
        }}
      >
        {hasUndefined
          ? "Evidence undefined — requires design"
          : `Evidence: ${item.EvidenceType}`}
      </div>
      {hasUndefined ? (
        <div style={{ fontSize: 11, color: "#633806" }}>
          {item.EvidenceUndefinedReason ||
            "No source system, format, or frequency identified."}
        </div>
      ) : (
        <>
          <Field l="Description" v={item.EvidenceDescription} />
          <Field l="Source system" v={item.EvidenceSourceSystem} />
          <Field l="Format" v={item.EvidenceFormat} />
          <Field l="Frequency" v={item.EvidenceFrequency} />
          <Field l="Collection" v={item.EvidenceCollectionMethod} />
          <Field l="Owner" v={item.EvidenceOwnerRole} />
          {item.EvidenceValidationCriteria && (
            <Field l="Validation" v={item.EvidenceValidationCriteria} />
          )}
        </>
      )}
    </div>
  );
};

// =============================================================================
//  Decision panel — shown for compliance users on unexpanded items
// =============================================================================

const DecisionPanel = ({ item, onDecide, isPending }) => {
  const [rationale,     setRationale]     = useState("");
  const [reviewerMode,  setReviewerMode]  = useState(false);
  const [reviewer,      setReviewer]      = useState(null);
  const { notify } = useAlert();

  const handleDecide = async (decisionKey) => {
    if (!rationale.trim()) {
      notify({
        tone: "warning",
        title: "Rationale required",
        message: "A rationale is required for every decision.",
      });
      return;
    }
    if (decisionKey === "Request Second Review") {
      setReviewerMode(true);
      return;
    }
    await onDecide(item.id, decisionKey, rationale);
  };

  const handleConfirmReviewer = async () => {
    if (!reviewer) return;
    const fullRationale = `Reviewer: ${reviewer.display_name} (${reviewer.email}). ${rationale}`;
    await onDecide(item.id, "Request Second Review", fullRationale);
    setReviewerMode(false);
    setReviewer(null);
  };

  return (
    <div style={{ marginBottom: 4 }}>
      {/* Rationale — above buttons so user fills it first */}
      <textarea
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
        placeholder="Decision rationale (required) — explain your decision before selecting an action..."
        rows={2}
        style={{
          width: "100%",
          fontSize: 12,
          padding: "9px 12px",
          borderRadius: 8,
          border: `1.5px solid ${rationale.trim() ? "#5DCAA5" : "#C0C0C0"}`,
          background: "var(--color-background-primary)",
          color: "var(--color-text-primary)",
          resize: "vertical",
          fontFamily: "var(--font-sans)",
          marginBottom: 10,
          boxSizing: "border-box",
          outline: "none",
        }}
        onFocus={(e) => (e.target.style.borderColor = "#378ADD")}
        onBlur={(e) =>
          (e.target.style.borderColor = rationale.trim() ? "#5DCAA5" : "#C0C0C0")
        }
      />

      {/* Inline reviewer picker — shown when "Request 2nd review" is clicked */}
      {reviewerMode && (
        <div style={{
          marginBottom: 10, padding: "12px 14px",
          background: "var(--color-background-secondary)",
          borderRadius: 10, border: "1.5px solid #378ADD",
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8,
                        color: "var(--color-text-primary)" }}>
            Select reviewer
          </div>
          <UserSearchField
            onSelect={setReviewer}
            label=""
            placeholder="Search by name or email..."
            accentColor="#378ADD"
          />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button
              onClick={handleConfirmReviewer}
              disabled={!reviewer || isPending}
              style={{
                flex: 1, padding: "8px", fontSize: 12, borderRadius: 8,
                border: "none", fontWeight: 600,
                background: !reviewer || isPending ? "#E8E8E8" : "#378ADD",
                color: !reviewer || isPending ? "#999" : "#fff",
                cursor: !reviewer || isPending ? "not-allowed" : "pointer",
              }}
            >
              {reviewer ? `Send to ${reviewer.display_name}` : "Select a person above"}
            </button>
            <button
              onClick={() => { setReviewerMode(false); setReviewer(null); }}
              style={{
                padding: "8px 12px", fontSize: 12, borderRadius: 8,
                border: "1.5px solid #C0C0C0", background: "transparent",
                color: "var(--color-text-secondary)", cursor: "pointer",
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* 6 decision buttons — 2 column grid */}
      {!reviewerMode && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {DECISIONS.map((d) => (
            <button
              key={d.key}
              onClick={() => handleDecide(d.key)}
              disabled={isPending}
              style={{
                padding: "10px 12px",
                fontSize: 12,
                borderRadius: 8,
                cursor: isPending ? "not-allowed" : "pointer",
                fontWeight: d.primary || d.danger ? 600 : 400,
                border: d.primary || d.danger ? "none" : "1.5px solid #C0C0C0",
                background: isPending
                  ? "#E8E8E8"
                  : d.primary
                    ? "#1D9E75"
                    : d.danger
                      ? "#A32D2D"
                      : "var(--color-background-primary)",
                color: isPending
                  ? "#999"
                  : d.primary || d.danger
                    ? "#fff"
                    : "var(--color-text-primary)",
                transition: "opacity 0.1s",
              }}
              onMouseEnter={(e) =>
                !isPending && !d.primary && !d.danger &&
                (e.currentTarget.style.background = "var(--color-background-secondary)")
              }
              onMouseLeave={(e) =>
                !d.primary && !d.danger &&
                (e.currentTarget.style.background = "var(--color-background-primary)")
              }
            >
              {d.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Queue item card — same anatomy for all three tabs
// =============================================================================

const QueueCard = ({ item, isCompliance, onDecide, isPending }) => {
  const [expanded, setExpanded] = useState(false);

  const itemType = item.ItemType || "Extraction";
  const confidence = item.ConfidenceScore || 0;
  const isLowConf = confidence < CONFIDENCE_THRESHOLDS.MEDIUM;
  const isDecided = item.ReviewStatus && item.ReviewStatus !== "Pending Review";

  const typeStyles = {
    Extraction: { color: "#0C447C", bg: "#E6F1FB", bd: "#85B7EB" },
    Orphan: { color: "#791F1F", bg: "#FCEBEB", bd: "#F09595" },
    Harmonisation: { color: "#3C3489", bg: "#EEEDFE", bd: "#AFA9EC" },
  };
  const ts = typeStyles[itemType] || typeStyles.Extraction;

  const primaryText =
    item.ControlStatement ||
    item.ResponsibilityStatement ||
    item.FindingStatement ||
    item.Title ||
    "Untitled item";

  const secondaryText =
    item.RiskStatement || item.OrphanReason || item.RemediationRequired || "";

  return (
    <div
      style={{
        border: `1px solid ${ts.bd}`,
        borderLeft: `4px solid ${ts.color}`,
        borderRadius: 12,
        background: isDecided
          ? "var(--color-background-secondary)"
          : "var(--color-background-primary)",
        opacity: isDecided ? 0.65 : 1,
        transition: "box-shadow 0.15s",
      }}
      onMouseEnter={(e) =>
        !isDecided &&
        (e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)")
      }
      onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "none")}
    >
      {/* Card header — always visible, click to expand */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "12px 14px", cursor: "pointer" }}
      >
        {/* Badges row */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 6,
            flexWrap: "wrap",
            gap: 4,
          }}
        >
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <span
              style={{
                fontSize: 10,
                padding: "1px 7px",
                borderRadius: 3,
                fontWeight: 600,
                background: ts.bg,
                color: ts.color,
                border: `0.5px solid ${ts.bd}`,
              }}
            >
              {itemType}
            </span>
            {item.DocumentType && (
              <StatusBadge label={item.DocumentType} small />
            )}
            {item.ControlType && <StatusBadge label={item.ControlType} small />}
            {item.Severity && <StatusBadge label={item.Severity} small />}
            {item.CompletenessFlag === "DEFICIENT" && (
              <StatusBadge label="Deficient" small />
            )}
            {isLowConf && (
              <span
                style={{
                  fontSize: 9,
                  padding: "1px 5px",
                  borderRadius: 3,
                  background: "#FCEBEB",
                  color: "#791F1F",
                  border: "0.5px solid #F09595",
                  fontWeight: 600,
                }}
              >
                LOW CONFIDENCE
              </span>
            )}
            {isDecided && <StatusBadge label={item.ReviewStatus} small />}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        {/* Primary statement */}
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            lineHeight: 1.4,
            marginBottom: 4,
          }}
        >
          {primaryText}
        </div>

        {/* Risk / reason + confidence */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          {secondaryText && (
            <div
              style={{
                fontSize: 11,
                color: "#A32D2D",
                flex: 1,
                lineHeight: 1.4,
              }}
            >
              {secondaryText.length > 120
                ? secondaryText.slice(0, 120) + "..."
                : secondaryText}
            </div>
          )}
          <div style={{ minWidth: 110 }}>
            <ConfidenceBar score={confidence} />
          </div>
        </div>

        {/* Source */}
        <div
          style={{
            fontSize: 10,
            color: "var(--color-text-tertiary)",
            marginTop: 4,
          }}
        >
          {item.SourceDocumentCode}
          {item.SourceClause ? ` · ${item.SourceClause}` : ""}
        </div>
      </div>

      {/* Expanded panel */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${ts.bd}`, padding: "14px 14px" }}>
          {/* ── DECISIONS FIRST — most important action ── */}
          {isDecided ? (
            <div
              style={{
                padding: "12px 14px",
                background: "#E1F5EE",
                borderRadius: 10,
                marginBottom: 14,
                border: "1px solid #5DCAA5",
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: "#085041",
                  marginBottom: 4,
                }}
              >
                {item.ReviewStatus} — {item.Decision}
              </div>
              {item.DecisionRationale && (
                <div
                  style={{
                    fontSize: 11,
                    color: "#085041",
                    opacity: 0.85,
                    fontStyle: "italic",
                  }}
                >
                  "{item.DecisionRationale}"
                </div>
              )}
            </div>
          ) : isCompliance ? (
            <DecisionPanel
              item={item}
              onDecide={onDecide}
              isPending={isPending}
            />
          ) : (
            <div
              style={{
                padding: "10px 14px",
                background: "var(--color-background-secondary)",
                borderRadius: 8,
                marginBottom: 14,
                fontSize: 12,
                color: "var(--color-text-tertiary)",
                border: "1px dashed var(--color-border-tertiary)",
              }}
            >
              Compliance Lead role required to make decisions on queue items.
              Contact the Compliance team to have this item reviewed.
            </div>
          )}

          {/* ── DIVIDER ── */}
          <div
            style={{
              borderTop: "0.5px solid var(--color-border-tertiary)",
              paddingTop: 12,
              marginTop: 4,
            }}
          >
            {/* Control details */}
            {item.ControlStatement && (
              <>
                {item.RiskStatement && (
                  <Field l="Risk" v={item.RiskStatement} />
                )}
                {item.ISOClause && <Field l="ISO clause" v={item.ISOClause} />}
                {item.ProposedOwnerRole && (
                  <Field l="Proposed owner" v={item.ProposedOwnerRole} />
                )}
                {item.SourceType && (
                  <Field l="Source type" v={item.SourceType} />
                )}
                {item.Counterparty && (
                  <Field l="Counterparty" v={item.Counterparty} />
                )}
                {item.NDPASection && (
                  <Field l="NDPA section" v={item.NDPASection} />
                )}
                {item.DeficiencyReason && (
                  <div
                    style={{
                      padding: "8px 10px",
                      background: "#FCEBEB",
                      borderRadius: 6,
                      fontSize: 11,
                      color: "#791F1F",
                      marginTop: 8,
                    }}
                  >
                    Deficiency: {item.DeficiencyReason}
                  </div>
                )}
                <EvidencePanel item={item} />
              </>
            )}

            {/* Orphan details */}
            {item.ResponsibilityStatement && (
              <>
                <Field l="Direction" v={item.OrphanDirection} />
                <Field l="Classification" v={item.OrphanClassification} />
                <Field l="Reason" v={item.OrphanReason} />
              </>
            )}

            {/* Regulatory details */}
            {item.Authority && (
              <>
                <Field l="Authority" v={item.Authority} />
                <Field l="Deadline" v={item.ObligationDeadline} />
                <Field l="Recurrence" v={item.ObligationRecurrence} />
                {item.StandardReference && (
                  <Field l="Standard" v={item.StandardReference} />
                )}
                {item.PenaltyIfMissed && (
                  <Field l="Penalty" v={item.PenaltyIfMissed} color="#A32D2D" />
                )}
              </>
            )}

            {/* Audit details */}
            {item.FindingType && (
              <>
                <Field l="Finding type" v={item.FindingType} />
                <Field l="Gap type" v={item.GapType} />
                <Field l="Remediation" v={item.RemediationRequired} />
                {item.StandardReference && (
                  <Field l="Standard" v={item.StandardReference} />
                )}
                {item.IsRepeatedFinding && (
                  <div
                    style={{
                      padding: "6px 10px",
                      background: "#FCEBEB",
                      borderRadius: 6,
                      fontSize: 11,
                      color: "#791F1F",
                      marginTop: 6,
                    }}
                  >
                    Repeated finding — previously unresolved
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Tab content — shared across all three tabs
// =============================================================================

const TabContent = ({ itemType, isCompliance }) => {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("pending"); // "pending" | "all"
  const decide = useDecide();

  const {
    data: items = [],
    isLoading,
    error,
    refetch,
  } = useQueueItems(itemType);

  const filtered = useMemo(() => {
    let list = items;
    if (filter === "pending") {
      list = list.filter(
        (i) => !i.ReviewStatus || i.ReviewStatus === "Pending Review",
      );
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (i) =>
          (i.ControlStatement || "").toLowerCase().includes(q) ||
          (i.ResponsibilityStatement || "").toLowerCase().includes(q) ||
          (i.FindingStatement || "").toLowerCase().includes(q) ||
          (i.SourceDocumentCode || "").toLowerCase().includes(q) ||
          (i.ProposedOwnerRole || "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [items, search, filter]);

  const pendingCount = items.filter(
    (i) => !i.ReviewStatus || i.ReviewStatus === "Pending Review",
  ).length;

  const handleDecide = async (itemId, decision, rationale) => {
    await decide.mutateAsync({ itemId, decision, rationale });
  };

  if (isLoading) return <LoadingState message="Loading queue items..." />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      {/* Filter + search bar */}
      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 12,
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", gap: 4 }}>
          {[
            { k: "pending", l: `Pending (${pendingCount})` },
            { k: "all", l: `All (${items.length})` },
          ].map((f) => (
            <button
              key={f.k}
              onClick={() => setFilter(f.k)}
              style={{
                padding: "5px 12px",
                fontSize: 12,
                borderRadius: 6,
                cursor: "pointer",
                fontWeight: filter === f.k ? 600 : 400,
                border:
                  filter === f.k
                    ? "1px solid var(--color-border-info)"
                    : "1.5px solid #C0C0C0",
                background:
                  filter === f.k
                    ? "var(--color-background-info)"
                    : "var(--color-background-primary)",
                color:
                  filter === f.k
                    ? "var(--color-text-info)"
                    : "var(--color-text-secondary)",
              }}
            >
              {f.l}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search items..."
          style={{
            flex: 1,
            fontSize: 13,
            padding: "7px 12px",
            borderRadius: 8,
            border: "1.5px solid #C0C0C0",
            background: "var(--color-background-primary)",
            color: "var(--color-text-primary)",
            outline: "none",
          }}
          onFocus={(e) => (e.target.style.borderColor = "#378ADD")}
          onBlur={(e) => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {/* Items */}
      {filtered.length === 0 ? (
        <EmptyState
          message={
            pendingCount === 0
              ? "No pending items in this queue. All items have been reviewed."
              : "No items match your search."
          }
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map((item) => (
            <QueueCard
              key={item.id}
              item={item}
              isCompliance={isCompliance}
              onDecide={handleDecide}
              isPending={decide.isPending}
            />
          ))}
        </div>
      )}

      {filtered.length > 0 && (
        <div
          style={{
            fontSize: 11,
            color: "var(--color-text-tertiary)",
            marginTop: 8,
          }}
        >
          {filtered.length} of {items.length}
        </div>
      )}
    </>
  );
};

// =============================================================================
//  Main component — three tabs
// =============================================================================

export default function AIReviewQueue() {
  const [activeTab, setActiveTab] = useState("Extraction");
  const { isCompliance } = useCurrentUserRole();

  const tabs = [
    {
      key: "Extraction",
      label: "Extraction",
      desc: "Controls, obligations, and findings extracted from policy, contract, regulatory, and audit documents",
      color: "#0C447C",
      bg: "#E6F1FB",
      bd: "#85B7EB",
    },
    {
      key: "Orphan",
      label: "Orphan",
      desc: "JD responsibilities with no controlling document, and controls with no JD owner",
      color: "#791F1F",
      bg: "#FCEBEB",
      bd: "#F09595",
    },
    {
      key: "Harmonisation",
      label: "Harmonisation",
      desc: "Variant role terms and near-duplicate controls across documents requiring canonical resolution",
      color: "#3C3489",
      bg: "#EEEDFE",
      bd: "#AFA9EC",
    },
  ];

  const activeTabMeta = tabs.find((t) => t.key === activeTab);

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
          AI review queue
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          Every AI extraction lands here for human confirmation before entering
          any register.
          {!isCompliance && (
            <span style={{ color: "#BA7517", marginLeft: 6 }}>
              View only — Compliance Lead role required to make decisions.
            </span>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
        {tabs.map((tab) => {
          const active = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              title={tab.desc}
              style={{
                padding: "9px 20px",
                fontSize: 13,
                cursor: "pointer",
                fontWeight: active ? 700 : 500,
                color: active ? "#fff" : "var(--color-text-secondary)",
                background: active
                  ? tab.color
                  : "var(--color-background-primary)",
                border: active
                  ? `1.5px solid ${tab.color}`
                  : "1.5px solid #C0C0C0",
                borderRadius: 8,
                transition: "all 0.12s",
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Active tab description */}
      {activeTabMeta && (
        <div
          style={{
            padding: "8px 12px",
            borderRadius: 8,
            marginBottom: 14,
            background: activeTabMeta.bg,
            border: `0.5px solid ${activeTabMeta.bd}`,
            fontSize: 12,
            color: activeTabMeta.color,
          }}
        >
          {activeTabMeta.desc}
        </div>
      )}

      {/* Tab content */}
      <TabContent itemType={activeTab} isCompliance={isCompliance} />
    </>
  );
}
