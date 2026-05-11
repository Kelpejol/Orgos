// =============================================================================
// pages/ExtractionReview/index.jsx
// Zone 1 — Extraction Review
// Reviews controls and evidence extracted from policies and contracts.
// Accept triggers full cascade: Control Register + Evidence Tracker + Audit Log.
// Per DRG-QI-REF-DINT-01-26 Section 4.1
// =============================================================================

import { useState, useMemo } from "react";
import { useMsal } from "@azure/msal-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { LoadingState, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import apiClient from "../../api/grcApi.js";

// =============================================================================
//  API
// =============================================================================

const zone1Api = {
  list: () =>
    apiClient.get("/api/v1/queue/items", { params: { item_type: "Extraction" } })
      .then(r => r.data),

  acceptControl: (itemId, body) =>
    apiClient.post(`/api/v1/queue/items/${itemId}/accept-control`, body)
      .then(r => r.data),

  reject: (itemId, rationale, rejectType = "Reject") =>
    apiClient.post(`/api/v1/queue/items/${itemId}/reject`,
      { rationale, reject_type: rejectType }).then(r => r.data),

  requestSecondReview: (itemId, rationale) =>
    apiClient.post(`/api/v1/queue/items/${itemId}/request-second-review`,
      { rationale }).then(r => r.data),
};

// =============================================================================
//  Hooks
// =============================================================================

function useUserRoles() {
  const { accounts } = useMsal();
  const roles = accounts[0]?.idTokenClaims?.roles || [];
  return {
    isCompliance: roles.includes("Compliance.Lead") || roles.includes("OrgOS.Admin"),
  };
}

function useZone1Items() {
  return useQuery({
    queryKey: ["zone1"],
    queryFn:  zone1Api.list,
    staleTime: 30_000,
  });
}

// =============================================================================
//  Confidence indicator
// =============================================================================

const ConfidenceDot = ({ score }) => {
  const pct = Math.round((score || 0) * 100);
  const color = pct >= 90 ? "#1D9E75" : pct >= 80 ? "#BA7517" : pct >= 60 ? "#A32D2D" : "#A32D2D";
  const label = pct >= 90 ? "High" : pct >= 80 ? "Amber" : pct >= 60 ? "Low" : "Very low";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
      <div style={{ flex: 1, height: 5, borderRadius: 3, background: "#E8E8E8", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 10, fontWeight: 600, color, minWidth: 56 }}>{pct}% {label}</span>
    </div>
  );
};

// =============================================================================
//  Chain preview — shows what Accept will create
// =============================================================================

const ChainPreview = ({ item }) => {
  const hasEvidence = item.EvidenceType && item.EvidenceDescription;
  return (
    <div style={{
      padding: "10px 12px", background: "#E6F1FB",
      borderRadius: 8, marginBottom: 12,
      border: "0.5px solid #85B7EB",
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#0C447C", marginBottom: 6 }}>
        If accepted, this creates:
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ fontSize: 11, color: "#0C447C" }}>
          → Control Register entry — {item.ControlType || "Directive"} · {item.ISOClause || "No clause"} · Owner: {item.ProposedOwnerRole || "Unresolved"}
        </div>
        {hasEvidence && (
          <div style={{ fontSize: 11, color: "#0C447C" }}>
            → Evidence Tracker entry — {item.EvidenceType} · {item.EvidenceFrequency || "frequency TBD"} · From: {item.EvidenceSourceSystem || "source TBD"}
          </div>
        )}
        {!hasEvidence && (
          <div style={{ fontSize: 11, color: "#BA7517" }}>
            → No evidence entry — evidence fields undefined on this item
          </div>
        )}
        <div style={{ fontSize: 11, color: "#0C447C" }}>
          → Audit log record — your identity, timestamp, rationale
        </div>
      </div>
    </div>
  );
};

// =============================================================================
//  Evidence panel
// =============================================================================

const EvidencePanel = ({ item }) => {
  if (!item.EvidenceType && !item.EvidenceDescription) return null;
  const hasUndefined = item.EvidenceUndefined;
  return (
    <div style={{
      padding: "10px 12px",
      background: hasUndefined ? "#FAEEDA" : "#EEEDFE",
      borderRadius: 8, marginTop: 8,
      border: `0.5px solid ${hasUndefined ? "#FAC775" : "#AFA9EC"}`,
    }}>
      <div style={{ fontSize: 11, fontWeight: 600,
                    color: hasUndefined ? "#633806" : "#3C3489", marginBottom: 6 }}>
        {hasUndefined ? "Evidence undefined — requires design" : `Evidence: ${item.EvidenceType}`}
      </div>
      {hasUndefined ? (
        <div style={{ fontSize: 11, color: "#633806" }}>
          {item.EvidenceUndefinedReason || "No source system, format, or frequency identified."}
        </div>
      ) : (
        <>
          <Field l="Description"  v={item.EvidenceDescription} />
          <Field l="Source"       v={item.EvidenceSourceSystem} />
          <Field l="Format"       v={item.EvidenceFormat} />
          <Field l="Frequency"    v={item.EvidenceFrequency} />
          <Field l="Collection"   v={item.EvidenceCollectionMethod} />
          <Field l="Owner role"   v={item.EvidenceOwnerRole} />
          {item.EvidenceValidationCriteria && (
            <Field l="Validation" v={item.EvidenceValidationCriteria} />
          )}
        </>
      )}
    </div>
  );
};

// =============================================================================
//  Decision panel
// =============================================================================

const DecisionPanel = ({ item, onDecide, isPending }) => {
  const [rationale, setRationale]     = useState("");
  const [editMode, setEditMode]       = useState(false);
  const [edits, setEdits]             = useState({});
  const [activeAction, setActiveAction] = useState(null);

  const ratOk = rationale.trim().length >= 10;

  const handleAction = async (action) => {
    if (!ratOk) return;
    setActiveAction(action);
    await onDecide(action, rationale.trim(), editMode ? edits : {});
    setActiveAction(null);
  };

  const editField = (k) => (e) => setEdits(p => ({ ...p, [k]: e.target.value }));

  const inputStyle = {
    width: "100%", fontSize: 11, padding: "5px 8px", borderRadius: 6,
    border: "1px solid #C0C0C0", background: "var(--color-background-primary)",
    color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box",
    marginTop: 3,
  };

  return (
    <div style={{ marginTop: 12 }}>
      {/* Edit toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
        <input type="checkbox" id={`edit-${item.id}`}
          checked={editMode} onChange={e => setEditMode(e.target.checked)} />
        <label htmlFor={`edit-${item.id}`}
          style={{ fontSize: 11, color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Edit before accepting
        </label>
      </div>

      {/* Edit fields */}
      {editMode && (
        <div style={{ padding: "10px 12px", background: "var(--color-background-secondary)",
                      borderRadius: 8, marginBottom: 10, border: "1px solid #D0D0D0" }}>
          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 8, color: "var(--color-text-secondary)" }}>
            Override AI values (leave blank to keep original)
          </div>
          {[
            ["control_statement", "Control statement", item.ControlStatement],
            ["control_type",      "Control type",      item.ControlType],
            ["iso_clause",        "ISO clause",        item.ISOClause],
            ["owner_role",        "Owner role",        item.ProposedOwnerRole],
            ["risk_implication",  "Risk implication",  item.RiskStatement],
            ["escalation_note",   "Escalation note",   ""],
          ].map(([key, label, placeholder]) => (
            <div key={key} style={{ marginBottom: 6 }}>
              <label style={{ fontSize: 10, color: "var(--color-text-tertiary)",
                              textTransform: "uppercase", letterSpacing: "0.4px" }}>{label}</label>
              <input type="text" value={edits[key] || ""}
                onChange={editField(key)}
                placeholder={placeholder || ""}
                style={inputStyle} />
            </div>
          ))}
        </div>
      )}

      {/* Rationale */}
      <textarea
        value={rationale}
        onChange={e => setRationale(e.target.value)}
        placeholder="Decision rationale — required (min 10 characters). Explain why you are making this decision. This is your audit trail."
        rows={3}
        style={{
          width: "100%", fontSize: 12, padding: "9px 12px", borderRadius: 8,
          border: `1.5px solid ${ratOk ? "#5DCAA5" : "#C0C0C0"}`,
          background: "var(--color-background-primary)",
          color: "var(--color-text-primary)", resize: "vertical",
          fontFamily: "var(--font-sans)", marginBottom: 10,
          boxSizing: "border-box", outline: "none",
        }}
        onFocus={e => (e.target.style.borderColor = "#378ADD")}
        onBlur={e => (e.target.style.borderColor = ratOk ? "#5DCAA5" : "#C0C0C0")}
      />

      {!ratOk && rationale.length > 0 && (
        <div style={{ fontSize: 10, color: "#A32D2D", marginBottom: 8 }}>
          Rationale must be at least 10 characters
        </div>
      )}

      {/* Decision buttons */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <button
          onClick={() => handleAction("accept")}
          disabled={!ratOk || isPending}
          style={{ padding: "10px", fontSize: 12, borderRadius: 8, border: "none",
                   background: !ratOk || isPending ? "#E8E8E8" : "#1D9E75",
                   color: !ratOk || isPending ? "#999" : "#fff",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer",
                   fontWeight: 600, gridColumn: editMode ? "1 / 3" : "1" }}
        >
          {activeAction === "accept" ? "Creating records..." : editMode ? "Edit & Accept →" : "Accept →"}
        </button>

        {!editMode && (
          <button
            onClick={() => setEditMode(true)}
            disabled={isPending}
            style={{ padding: "10px", fontSize: 12, borderRadius: 8,
                     border: "1.5px solid #C0C0C0", background: "transparent",
                     color: "var(--color-text-primary)", cursor: "pointer" }}
          >
            Edit & accept
          </button>
        )}

        <button
          onClick={() => handleAction("reject")}
          disabled={!ratOk || isPending}
          style={{ padding: "10px", fontSize: 12, borderRadius: 8, border: "none",
                   background: !ratOk || isPending ? "#E8E8E8" : "#A32D2D",
                   color: !ratOk || isPending ? "#999" : "#fff",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer", fontWeight: 500 }}
        >
          Reject
        </button>

        <button
          onClick={() => handleAction("false_positive")}
          disabled={!ratOk || isPending}
          style={{ padding: "10px", fontSize: 12, borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "transparent",
                   color: "var(--color-text-secondary)",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer" }}
        >
          Mark false positive
        </button>

        <button
          onClick={() => handleAction("second_review")}
          disabled={!ratOk || isPending}
          style={{ padding: "10px", fontSize: 12, borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "transparent",
                   color: "var(--color-text-secondary)",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer" }}
        >
          Request 2nd review
        </button>
      </div>
    </div>
  );
};

// =============================================================================
//  Document viewer — embeds SharePoint document inline
// =============================================================================

const DocumentViewer = ({ url, docCode }) => {
  const [expanded, setExpanded] = useState(false);

  // Use the URL directly in the iframe — SharePoint handles sharing link redirects.
  // The wdStartOn and action=embedview params only work with direct file URLs, not sharing links.
  const embedUrl = url;

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "#0C447C" }}>
          Source document — {docCode}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={() => setExpanded(!expanded)}
            style={{ fontSize: 11, padding: "3px 10px", borderRadius: 5,
                     border: "1px solid #85B7EB",
                     background: expanded ? "#0C447C" : "transparent",
                     color: expanded ? "#fff" : "#0C447C", cursor: "pointer" }}
          >
            {expanded ? "Hide" : "Preview"}
          </button>
          <a href={url} target="_blank" rel="noreferrer"
            style={{ fontSize: 11, padding: "3px 10px", borderRadius: 5,
                     border: "1px solid #85B7EB", background: "transparent",
                     color: "#0C447C", textDecoration: "none" }}>
            Open in SharePoint ↗
          </a>
        </div>
      </div>

      {expanded && (
        <div style={{ borderRadius: 8, overflow: "hidden",
                      border: "1px solid #85B7EB" }}>
          <div style={{ padding: "10px 14px", background: "#E6F1FB",
                        fontSize: 11, color: "#0C447C" }}>
            SharePoint preview — use "Open in SharePoint ↗" for full editing access.
          </div>
          <iframe
            src={embedUrl}
            width="100%"
            height="520"
            frameBorder="0"
            title={`Source: ${docCode}`}
            style={{ display: "block" }}
          />
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Extraction item card
// =============================================================================

const ExtractionCard = ({ item, isCompliance, onDecide, isPending }) => {
  const [expanded, setExpanded] = useState(false);
  const isDecided = item.ReviewStatus && item.ReviewStatus !== "Pending Review";
  const pct = Math.round((item.ConfidenceScore || 0) * 100);

  return (
    <div style={{
      border: `1px solid ${isDecided ? "#D0D0D0" : "#85B7EB"}`,
      borderLeft: `4px solid ${isDecided ? "#D0D0D0" : "#0C447C"}`,
      borderRadius: 12,
      background: isDecided ? "var(--color-background-secondary)" : "var(--color-background-primary)",
      opacity: isDecided ? 0.65 : 1,
      transition: "box-shadow 0.15s",
    }}
      onMouseEnter={e => !isDecided && (e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)")}
      onMouseLeave={e => (e.currentTarget.style.boxShadow = "none")}
    >
      {/* Header */}
      <div
        role="button" tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={e => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "12px 14px", cursor: "pointer" }}
      >
        {/* Badges */}
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 6, flexWrap: "wrap", gap: 4 }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {item.DocumentType    && <StatusBadge label={item.DocumentType} />}
            {item.ControlType     && <StatusBadge label={item.ControlType} />}
            {item.CompletenessFlag === "DEFICIENT" && <StatusBadge label="Deficient" />}
            {pct < 60 && (
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3,
                             background: "#FCEBEB", color: "#791F1F",
                             border: "0.5px solid #F09595", fontWeight: 600 }}>
                VERY LOW CONFIDENCE
              </span>
            )}
            {isDecided && <StatusBadge label={item.ReviewStatus} />}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        {/* Control statement */}
        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 6 }}>
          {item.ControlStatement || item.Title || "Untitled item"}
        </div>

        {/* Risk + confidence */}
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", gap: 12 }}>
          {item.RiskStatement && (
            <div style={{ fontSize: 11, color: "#A32D2D", flex: 1 }}>
              Risk: {item.RiskStatement.length > 100
                ? item.RiskStatement.slice(0, 100) + "..." : item.RiskStatement}
            </div>
          )}
          <div style={{ minWidth: 160 }}>
            <ConfidenceDot score={item.ConfidenceScore} />
          </div>
        </div>

        {/* Source */}
        <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4 }}>
          {item.SourceDocumentCode}{item.SourceClause ? ` · ${item.SourceClause}` : ""}
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div style={{ borderTop: `1px solid #85B7EB`, padding: "14px 14px" }}>

          {/* If already decided — show outcome */}
          {isDecided ? (
            <div style={{ padding: "10px 12px", background: "#E1F5EE",
                          borderRadius: 8, marginBottom: 12,
                          border: "1px solid #5DCAA5" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#085041", marginBottom: 3 }}>
                {item.ReviewStatus} — {item.Decision}
              </div>
              {item.DecisionRationale && (
                <div style={{ fontSize: 11, color: "#085041", fontStyle: "italic" }}>
                  "{item.DecisionRationale}"
                </div>
              )}
              {item.CascadeResult && (
                <div style={{ fontSize: 10, color: "#085041", marginTop: 4, opacity: 0.8 }}>
                  {item.CascadeResult}
                </div>
              )}
            </div>
          ) : isCompliance ? (
            <>
              <ChainPreview item={item} />
              <DecisionPanel item={item} onDecide={(action, rationale, edits) =>
                onDecide(item.id, action, rationale, edits)} isPending={isPending} />
            </>
          ) : (
            <div style={{ padding: "10px 12px", background: "var(--color-background-secondary)",
                          borderRadius: 8, marginBottom: 12, fontSize: 12,
                          color: "var(--color-text-tertiary)",
                          border: "1px dashed var(--color-border-tertiary)" }}>
              Compliance Lead role required to make decisions.
            </div>
          )}

          {/* Full details below decisions */}
          <div style={{ borderTop: "0.5px solid var(--color-border-tertiary)", paddingTop: 12, marginTop: 4 }}>
            {item.ISOClause        && <Field l="ISO clause"     v={item.ISOClause} />}
            {item.ProposedOwnerRole && <Field l="Proposed owner" v={item.ProposedOwnerRole} />}
            {item.SourceType       && <Field l="Source type"    v={item.SourceType} />}
            {item.DeficiencyReason && (
              <div style={{ padding: "6px 10px", background: "#FCEBEB", borderRadius: 6,
                            fontSize: 11, color: "#791F1F", marginTop: 6 }}>
                Deficiency: {item.DeficiencyReason}
              </div>
            )}
            <EvidencePanel item={item} />

            {/* Document viewer */}
            {item.SourceDocumentUrl && (
              <DocumentViewer url={item.SourceDocumentUrl} docCode={item.SourceDocumentCode} />
            )}
            {!item.SourceDocumentUrl && item.SourceDocumentCode && (
              <div style={{ marginTop: 10, padding: "7px 10px",
                            background: "var(--color-background-secondary)",
                            borderRadius: 7, fontSize: 11, color: "var(--color-text-tertiary)",
                            border: "0.5px solid var(--color-border-tertiary)" }}>
                Source: {item.SourceDocumentCode}
                {item.SourceClause ? ` · ${item.SourceClause}` : ""}
                {" — Document URL not stored. Add SourceDocumentUrl to this queue item to enable embedded viewing."}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Main component
// =============================================================================

export default function ExtractionReview() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("pending");
  const [actionState, setActionState] = useState({ pending: false, itemId: null });

  const { isCompliance } = useUserRoles();
  const qc = useQueryClient();
  const { data: items = [], isLoading, error, refetch } = useZone1Items();

  const pendingCount = items.filter(
    i => !i.ReviewStatus || i.ReviewStatus === "Pending Review"
  ).length;

  const filtered = useMemo(() => {
    let list = filter === "pending"
      ? items.filter(i => !i.ReviewStatus || i.ReviewStatus === "Pending Review")
      : filter === "low"
      ? items.filter(i => (i.ConfidenceScore || 0) < 0.6)
      : items;

    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(i =>
        (i.ControlStatement || "").toLowerCase().includes(q) ||
        (i.SourceDocumentCode || "").toLowerCase().includes(q) ||
        (i.ProposedOwnerRole || "").toLowerCase().includes(q) ||
        (i.ISOClause || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [items, search, filter]);

  const handleDecide = async (itemId, action, rationale, edits) => {
    setActionState({ pending: true, itemId });
    try {
      if (action === "accept") {
        await zone1Api.acceptControl(itemId, {
          rationale,
          ...Object.fromEntries(Object.entries(edits).filter(([, v]) => v)),
        });
      } else if (action === "reject") {
        await zone1Api.reject(itemId, rationale, "Reject");
      } else if (action === "false_positive") {
        await zone1Api.reject(itemId, rationale, "Mark False Positive");
      } else if (action === "second_review") {
        await zone1Api.requestSecondReview(itemId, rationale);
      }
      qc.invalidateQueries({ queryKey: ["zone1"] });
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Decision failed.");
    } finally {
      setActionState({ pending: false, itemId: null });
    }
  };

  if (isLoading) return <LoadingState message="Loading extraction items..." />;
  if (error)     return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
              Extraction review
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Zone 1 — Controls and evidence extracted from policies and contracts.
              Accept creates permanent Control Register and Evidence Tracker entries.
            </div>
          </div>
          <div style={{ padding: "3px 10px", background: "#E6F1FB", borderRadius: 6,
                        fontSize: 11, color: "#0C447C", fontWeight: 600,
                        border: "0.5px solid #85B7EB", flexShrink: 0 }}>
            {pendingCount} pending
          </div>
        </div>
        {!isCompliance && (
          <div style={{ marginTop: 8, padding: "8px 12px", background: "#FAEEDA",
                        borderRadius: 8, fontSize: 12, color: "#633806",
                        border: "0.5px solid #FAC775" }}>
            View only — Compliance Lead role required to make decisions.
          </div>
        )}
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {[
          { k: "pending", l: `Pending (${pendingCount})` },
          { k: "low",     l: `Low confidence` },
          { k: "all",     l: `All (${items.length})` },
        ].map(f => (
          <button key={f.k} onClick={() => setFilter(f.k)}
            style={{ padding: "5px 12px", fontSize: 12, borderRadius: 6, cursor: "pointer",
                     fontWeight: filter === f.k ? 600 : 400,
                     border: filter === f.k ? "1px solid var(--color-border-info)" : "1.5px solid #C0C0C0",
                     background: filter === f.k ? "var(--color-background-info)" : "var(--color-background-primary)",
                     color: filter === f.k ? "var(--color-text-info)" : "var(--color-text-secondary)" }}>
            {f.l}
          </button>
        ))}
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search by control, document, owner, ISO clause..."
          style={{ flex: 1, minWidth: 200, fontSize: 12, padding: "6px 12px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {/* Items */}
      {filtered.length === 0 ? (
        <EmptyState message={
          pendingCount === 0
            ? "All items reviewed. Run the bulk extractor to process more documents."
            : "No items match your search."
        } />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map(item => (
            <ExtractionCard
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
        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 8 }}>
          {filtered.length} of {items.length}
        </div>
      )}
    </>
  );
}