// =============================================================================
// pages/AssignmentOwnership/index.jsx
// Zone 2 — Assignment & Ownership
// Handles three item subtypes with different decision sets:
//   Orphan (JD→Doc): JD responsibility with no controlling document
//   Orphan (Doc→JD): Control references a role whose JD lacks the responsibility
//   Conflict: Two documents define contradictory requirements
// Per DRG-QI-REF-DINT-01-26 Section 3.2
// =============================================================================

import { useState, useMemo } from "react";
import { useMsal } from "@azure/msal-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import {
  LoadingState,
  ErrorState,
  EmptyState,
} from "../../components/shared/LoadingState.jsx";
import apiClient from "../../api/grcApi.js";

// =============================================================================
//  API
// =============================================================================

const zone2Api = {
  list: () =>
    apiClient
      .get("/api/v1/queue/items", { params: { item_type: "Orphan" } })
      .then((r) => r.data),

  decide: (itemId, decision, rationale, extra = {}) =>
    apiClient
      .patch(`/api/v1/queue/items/${itemId}/decide`, {
        decision,
        rationale,
        ...extra,
      })
      .then((r) => r.data),
};

function useUserRoles() {
  const { accounts } = useMsal();
  const roles = accounts[0]?.idTokenClaims?.roles || [];
  return {
    isCompliance:
      roles.includes("Compliance.Lead") || roles.includes("OrgOS.Admin"),
  };
}

// =============================================================================
//  Decision panels — different per subtype
// =============================================================================

const JDToDocDecisions = [
  {
    key: "Create new document",
    label: "Create new document",
    desc: "A new policy or procedure is needed to govern this responsibility",
    primary: true,
  },
  {
    key: "Add to existing policy",
    label: "Add to existing policy",
    desc: "Add this responsibility to an existing approved document",
  },
  {
    key: "Intentional",
    label: "Intentional — no policy needed",
    desc: "This responsibility deliberately has no governing document",
  },
  {
    key: "Remove from JD",
    label: "Remove from JD",
    desc: "This responsibility should not be in the JD",
  },
  {
    key: "Mark False Positive",
    label: "Mark false positive",
    desc: "The AI incorrectly flagged this as an orphan",
  },
  {
    key: "Request Second Review",
    label: "Request 2nd review",
    desc: "Escalate to another compliance team member",
  },
];

const DocToJDDecisions = [
  {
    key: "Add to existing JD",
    label: "Add to JD",
    desc: "Add this responsibility to the role's job description",
    primary: true,
  },
  {
    key: "Reassign control",
    label: "Reassign control",
    desc: "Assign this control to a different role",
  },
  {
    key: "Create new role",
    label: "Create new role",
    desc: "A new role needs to be defined and added to the Role Register",
  },
  {
    key: "Remove from policy",
    label: "Remove from policy",
    desc: "This control should not reference this role",
  },
  {
    key: "Mark False Positive",
    label: "Mark false positive",
    desc: "The AI incorrectly flagged this as an orphan",
  },
  {
    key: "Request Second Review",
    label: "Request 2nd review",
    desc: "Escalate to another compliance team member",
  },
];

const ConflictDecisions = [
  {
    key: "Select governing document",
    label: "Select governing document",
    desc: "One document defines this requirement — the other needs revision",
    primary: true,
  },
  {
    key: "Escalate to ExCo",
    label: "Escalate to ExCo",
    desc: "This conflict requires senior leadership resolution",
  },
  {
    key: "Merge",
    label: "Merge requirements",
    desc: "Both requirements are valid — merge into one statement",
  },
  {
    key: "Mark False Positive",
    label: "Mark false positive",
    desc: "Not actually a conflict — AI misread the documents",
  },
];

const DecisionPanel = ({ item, decisions, onDecide, isPending }) => {
  const [rationale, setRationale] = useState("");
  const [active, setActive] = useState(null);
  const ratOk = rationale.trim().length >= 10;

  const handle = async (key) => {
    if (!ratOk) return;
    setActive(key);
    await onDecide(item.id, key, rationale.trim());
    setActive(null);
  };

  return (
    <div style={{ marginTop: 12 }}>
      <textarea
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
        placeholder="Decision rationale — required (min 10 characters). This is your audit trail."
        rows={2}
        style={{
          width: "100%",
          fontSize: 12,
          padding: "9px 12px",
          borderRadius: 8,
          border: `1.5px solid ${ratOk ? "#5DCAA5" : "#C0C0C0"}`,
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
          (e.target.style.borderColor = ratOk ? "#5DCAA5" : "#C0C0C0")
        }
      />
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {decisions.map((d) => (
          <button
            key={d.key}
            onClick={() => handle(d.key)}
            disabled={!ratOk || isPending}
            title={d.desc}
            style={{
              padding: "9px 12px",
              fontSize: 12,
              borderRadius: 8,
              textAlign: "left",
              border: d.primary ? "none" : "1.5px solid #C0C0C0",
              background:
                !ratOk || isPending
                  ? "#E8E8E8"
                  : d.primary
                    ? "#791F1F"
                    : "var(--color-background-primary)",
              color:
                !ratOk || isPending
                  ? "#999"
                  : d.primary
                    ? "#fff"
                    : "var(--color-text-primary)",
              cursor: !ratOk || isPending ? "not-allowed" : "pointer",
              fontWeight: d.primary ? 600 : 400,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>{active === d.key ? "Processing..." : d.label}</span>
            <span style={{ fontSize: 10, opacity: 0.6, marginLeft: 8 }}>
              {d.desc}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
};

// =============================================================================
//  Orphan card
// =============================================================================

const OrphanCard = ({ item, isCompliance, onDecide, isPending }) => {
  const [expanded, setExpanded] = useState(false);
  const isDecided = item.ReviewStatus && item.ReviewStatus !== "Pending Review";
  const direction = item.OrphanDirection || "JD_to_Doc";
  const isJDtoDoc = direction === "JD_to_Doc";

  const borderColor = isJDtoDoc ? "#F09595" : "#85B7EB";
  const accentColor = isJDtoDoc ? "#791F1F" : "#0C447C";
  const dirLabel = isJDtoDoc ? "JD → No policy" : "Policy → Not in JD";
  const decisions = isJDtoDoc ? JDToDocDecisions : DocToJDDecisions;

  return (
    <div
      style={{
        border: `1px solid ${borderColor}`,
        borderLeft: `4px solid ${accentColor}`,
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
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "12px 14px", cursor: "pointer" }}
      >
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
                background: isJDtoDoc ? "#FCEBEB" : "#E6F1FB",
                color: accentColor,
                border: `0.5px solid ${borderColor}`,
              }}
            >
              {dirLabel}
            </span>
            {isDecided && <StatusBadge label={item.ReviewStatus} />}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            lineHeight: 1.4,
            marginBottom: 4,
          }}
        >
          {item.ResponsibilityStatement || item.ControlStatement || item.Title}
        </div>

        <div
          style={{
            fontSize: 11,
            color: "#A32D2D",
            lineHeight: 1.4,
            marginBottom: 4,
          }}
        >
          {item.OrphanReason || "No explanation provided"}
        </div>

        <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>
          {item.SourceDocumentCode}
          {item.SourceClause ? ` · ${item.SourceClause}` : ""}
        </div>
      </div>

      {expanded && (
        <div
          style={{
            borderTop: `1px solid ${borderColor}`,
            padding: "12px 14px",
          }}
        >
          {/* Gap explanation */}
          <div
            style={{
              padding: "10px 12px",
              borderRadius: 8,
              marginBottom: 12,
              background: isJDtoDoc ? "#FFF8F8" : "#F0F7FF",
              border: `0.5px solid ${borderColor}`,
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: accentColor,
                marginBottom: 4,
              }}
            >
              {isJDtoDoc
                ? "JD responsibility has no governing policy"
                : "Control references a role whose JD lacks this responsibility"}
            </div>
            <div
              style={{
                fontSize: 11,
                color: accentColor,
                opacity: 0.85,
                lineHeight: 1.5,
              }}
            >
              {isJDtoDoc
                ? "Until resolved: no control governs this activity, no evidence is collected, and this responsibility is untracked in the compliance chain."
                : "Until resolved: the control exists but the role's JD does not acknowledge this accountability. The person may not know they own this control."}
            </div>
          </div>

          {/* Details */}
          <Field l="Direction" v={direction} />
          <Field l="Classification" v={item.OrphanClassification} />
          {item.OrphanReason && <Field l="Reason" v={item.OrphanReason} />}

          {/* Already decided */}
          {isDecided ? (
            <div
              style={{
                marginTop: 10,
                padding: "10px 12px",
                background: "#E1F5EE",
                borderRadius: 8,
                border: "1px solid #5DCAA5",
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, color: "#085041" }}>
                {item.ReviewStatus} — {item.Decision}
              </div>
              {item.DecisionRationale && (
                <div
                  style={{
                    fontSize: 11,
                    color: "#085041",
                    fontStyle: "italic",
                    marginTop: 3,
                  }}
                >
                  "{item.DecisionRationale}"
                </div>
              )}
            </div>
          ) : isCompliance ? (
            <DecisionPanel
              item={item}
              decisions={decisions}
              onDecide={onDecide}
              isPending={isPending}
            />
          ) : (
            <div
              style={{
                marginTop: 10,
                padding: "8px 12px",
                background: "var(--color-background-secondary)",
                borderRadius: 8,
                fontSize: 11,
                color: "var(--color-text-tertiary)",
                border: "1px dashed var(--color-border-tertiary)",
              }}
            >
              Compliance Lead role required to make decisions.
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Main component
// =============================================================================

export default function AssignmentOwnership() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("pending");
  const [actionState, setActionState] = useState({
    pending: false,
    itemId: null,
  });

  const { isCompliance } = useUserRoles();
  const qc = useQueryClient();
  const {
    data: items = [],
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["zone2"],
    queryFn: zone2Api.list,
    staleTime: 30_000,
  });

  const pendingCount = items.filter(
    (i) => !i.ReviewStatus || i.ReviewStatus === "Pending Review",
  ).length;

  const filtered = useMemo(() => {
    let list =
      filter === "pending"
        ? items.filter(
            (i) => !i.ReviewStatus || i.ReviewStatus === "Pending Review",
          )
        : items;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (i) =>
          (i.ResponsibilityStatement || "").toLowerCase().includes(q) ||
          (i.ControlStatement || "").toLowerCase().includes(q) ||
          (i.SourceDocumentCode || "").toLowerCase().includes(q) ||
          (i.OrphanReason || "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [items, search, filter]);

  const handleDecide = async (itemId, decision, rationale) => {
    setActionState({ pending: true, itemId });
    try {
      await zone2Api.decide(itemId, decision, rationale);
      qc.invalidateQueries({ queryKey: ["zone2"] });
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Decision failed.");
    } finally {
      setActionState({ pending: false, itemId: null });
    }
  };

  if (isLoading) return <LoadingState message="Loading assignment items..." />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
          }}
        >
          <div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
              Assignment & ownership
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Zone 2 — JD responsibilities without governing policies, and
              controls whose owning role's JD doesn't acknowledge the
              responsibility.
            </div>
          </div>
          <div
            style={{
              padding: "3px 10px",
              background: "#FCEBEB",
              borderRadius: 6,
              fontSize: 11,
              color: "#791F1F",
              fontWeight: 600,
              border: "0.5px solid #F09595",
              flexShrink: 0,
            }}
          >
            {pendingCount} pending
          </div>
        </div>
        {!isCompliance && (
          <div
            style={{
              marginTop: 8,
              padding: "8px 12px",
              background: "#FAEEDA",
              borderRadius: 8,
              fontSize: 12,
              color: "#633806",
              border: "0.5px solid #FAC775",
            }}
          >
            View only — Compliance Lead role required to make decisions.
          </div>
        )}
      </div>

      <div
        style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}
      >
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
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search orphan items..."
          style={{
            flex: 1,
            minWidth: 180,
            fontSize: 12,
            padding: "6px 12px",
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

      {filtered.length === 0 ? (
        <EmptyState
          message={
            items.length === 0
              ? "No Zone 2 items yet. Run the Job Descriptions folder through the bulk extractor to generate orphan items. Orphans surface when a JD responsibility has no governing policy, or vice versa."
              : "No items match your search."
          }
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map((item) => (
            <OrphanCard
              key={item.id}
              item={item}
              isCompliance={isCompliance}
              onDecide={handleDecide}
              isPending={actionState.pending && actionState.itemId === item.id}
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
}
