// =============================================================================
// pages/EvidenceTracker/index.jsx
// Evidence Tracker — wired to SharePoint.
// Shows evidence items created by the Zone 1 cascade.
// Owner view: my evidence items to collect and submit.
// Compliance view: submitted items to verify, overdue items to chase.
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

const evidenceApi = {
  list: (params) =>
    apiClient.get("/api/v1/evidence", { params }).then(r => r.data),

  submit: (id, evidenceLink, notes) =>
    apiClient.patch(`/api/v1/evidence/${id}/submit`, {
      evidence_link: evidenceLink,
      submission_notes: notes || undefined,
    }).then(r => r.data),

  verify: (id, accepted, rejectionNote) =>
    apiClient.patch(`/api/v1/evidence/${id}/verify`, {
      accepted,
      rejection_note: rejectionNote || undefined,
    }).then(r => r.data),
};

// =============================================================================
//  Hooks
// =============================================================================

function useCurrentUser() {
  const { accounts } = useMsal();
  const a = accounts[0];
  const roles = a?.idTokenClaims?.roles || [];
  return {
    oid:          a?.idTokenClaims?.oid || a?.localAccountId || "",
    name:         a?.name || "",
    isCompliance: roles.includes("Compliance.Lead") || roles.includes("OrgOS.Admin"),
  };
}

function useEvidence() {
  return useQuery({
    queryKey: ["evidence"],
    queryFn:  () => evidenceApi.list({}),
    staleTime: 30_000,
  });
}

// =============================================================================
//  Status colours
// =============================================================================

const STATUS_STYLES = {
  "Pending":   { color: "#595952", bg: "#F1EFE8", bd: "#B4B2A9" },
  "Due Soon":  { color: "#633806", bg: "#FAEEDA", bd: "#FAC775" },
  "Overdue":   { color: "#791F1F", bg: "#FCEBEB", bd: "#F09595" },
  "Submitted": { color: "#0C447C", bg: "#E6F1FB", bd: "#85B7EB" },
  "Accepted":  { color: "#085041", bg: "#E1F5EE", bd: "#5DCAA5" },
  "Rejected":  { color: "#791F1F", bg: "#FCEBEB", bd: "#F09595" },
};

const EVID_TYPE_LABELS = {
  LOG: "System log export",
  CFG: "Configuration evidence",
  APR: "Signed approval record",
  FRM: "Completed form/record",
  TRN: "Training record",
  ACK: "Policy acknowledgement",
  TST: "Test/drill/verification",
  CRT: "Certificate/attestation",
  MTG: "Meeting/governance record",
  REV: "Review record",
  CHK: "Checklist completion",
  CNT: "Contract/agreement",
  INV: "Inventory/register extract",
  CHG: "Change record",
  INC: "Incident record",
  RPT: "Report/assessment",
};

// =============================================================================
//  Submit panel
// =============================================================================

const SubmitPanel = ({ item, onSubmit, onClose, isPending }) => {
  const [link,  setLink]  = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!link.trim()) { setError("Evidence link is required."); return; }
    setError("");
    await onSubmit(item.id, link.trim(), notes.trim());
  };

  return (
    <div style={{ marginTop: 12, padding: "14px", background: "#E6F1FB",
                  borderRadius: 10, border: "1px solid #85B7EB" }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#0C447C", marginBottom: 8 }}>
        Submit evidence
      </div>
      {item.ValidationCriteria && (
        <div style={{ fontSize: 11, color: "#0C447C", marginBottom: 10,
                      padding: "6px 10px", background: "#D4E8FA", borderRadius: 6 }}>
          Acceptance criteria: {item.ValidationCriteria}
        </div>
      )}
      {error && (
        <div style={{ fontSize: 11, color: "#791F1F", marginBottom: 8 }}>{error}</div>
      )}
      <div style={{ marginBottom: 8 }}>
        <label style={{ display: "block", fontSize: 10, fontWeight: 500,
                        color: "var(--color-text-secondary)", marginBottom: 3,
                        textTransform: "uppercase", letterSpacing: "0.4px" }}>
          Evidence link <span style={{ color: "#A32D2D" }}>*</span>
        </label>
        <input
          type="url" value={link} onChange={e => setLink(e.target.value)}
          placeholder="Paste URL to artefact in SharePoint, Intune, GitHub, etc."
          style={{ width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 8,
                   border: `1.5px solid ${link.trim() ? "#5DCAA5" : "#C0C0C0"}`,
                   background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none", boxSizing: "border-box" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = link.trim() ? "#5DCAA5" : "#C0C0C0")}
        />
      </div>
      <div style={{ marginBottom: 10 }}>
        <label style={{ display: "block", fontSize: 10, fontWeight: 500,
                        color: "var(--color-text-secondary)", marginBottom: 3,
                        textTransform: "uppercase", letterSpacing: "0.4px" }}>
          Notes (optional)
        </label>
        <textarea value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="Any context for the compliance reviewer..."
          rows={2}
          style={{ width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", resize: "vertical",
                   fontFamily: "var(--font-sans)", outline: "none", boxSizing: "border-box" }} />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={handleSubmit} disabled={isPending || !link.trim()}
          style={{ padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "none",
                   fontWeight: 500,
                   background: isPending || !link.trim() ? "#E8E8E8" : "#1D9E75",
                   color: isPending || !link.trim() ? "#999" : "#fff",
                   cursor: isPending || !link.trim() ? "not-allowed" : "pointer" }}>
          {isPending ? "Submitting..." : "Submit for review"}
        </button>
        <button onClick={onClose}
          style={{ padding: "8px 12px", fontSize: 12, borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "transparent",
                   color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Cancel
        </button>
      </div>
    </div>
  );
};

// =============================================================================
//  Verify panel (Compliance only)
// =============================================================================

const VerifyPanel = ({ item, onVerify, onClose, isPending }) => {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const handleReject = async () => {
    if (!note.trim()) { setError("Rejection note is required."); return; }
    setError("");
    await onVerify(item.id, false, note.trim());
  };

  return (
    <div style={{ marginTop: 12, padding: "14px", background: "#EEEDFE",
                  borderRadius: 10, border: "1px solid #AFA9EC" }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#3C3489", marginBottom: 8 }}>
        Verify submission
      </div>
      {item.ValidationCriteria && (
        <div style={{ fontSize: 11, color: "#3C3489", marginBottom: 8,
                      padding: "6px 10px", background: "#E0DCFE", borderRadius: 6 }}>
          Check: {item.ValidationCriteria}
        </div>
      )}
      {item.EvidenceLink && (
        <div style={{ marginBottom: 10 }}>
          <a href={item.EvidenceLink} target="_blank" rel="noreferrer"
            style={{ fontSize: 12, color: "#3C3489", textDecoration: "underline" }}>
            Open submitted evidence ↗
          </a>
        </div>
      )}
      {item.SubmissionNotes && (
        <div style={{ fontSize: 11, color: "#3C3489", marginBottom: 10,
                      fontStyle: "italic" }}>
          Owner notes: "{item.SubmissionNotes}"
        </div>
      )}
      {error && (
        <div style={{ fontSize: 11, color: "#791F1F", marginBottom: 8 }}>{error}</div>
      )}
      <textarea value={note} onChange={e => setNote(e.target.value)}
        placeholder="Rejection note (required if rejecting)..."
        rows={2}
        style={{ width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 8,
                 border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                 color: "var(--color-text-primary)", resize: "vertical",
                 fontFamily: "var(--font-sans)", outline: "none",
                 boxSizing: "border-box", marginBottom: 10 }} />
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={() => onVerify(item.id, true)} disabled={isPending}
          style={{ padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "none",
                   fontWeight: 600,
                   background: isPending ? "#E8E8E8" : "#1D9E75",
                   color: isPending ? "#999" : "#fff",
                   cursor: isPending ? "not-allowed" : "pointer" }}>
          {isPending ? "Saving..." : "Accept evidence"}
        </button>
        <button onClick={handleReject} disabled={isPending}
          style={{ padding: "8px 14px", fontSize: 12, borderRadius: 8, border: "none",
                   background: isPending ? "#E8E8E8" : "#A32D2D",
                   color: isPending ? "#999" : "#fff",
                   cursor: isPending ? "not-allowed" : "pointer", fontWeight: 500 }}>
          Reject
        </button>
        <button onClick={onClose}
          style={{ padding: "8px 12px", fontSize: 12, borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "transparent",
                   color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Cancel
        </button>
      </div>
    </div>
  );
};

// =============================================================================
//  Evidence card
// =============================================================================

const EvidenceCard = ({ item, currentOid, isCompliance, onSubmit, onVerify, actionItemId }) => {
  const [expanded, setExpanded]     = useState(false);
  const [showSubmit, setShowSubmit] = useState(false);
  const [showVerify, setShowVerify] = useState(false);

  const ss = STATUS_STYLES[item.Status] || STATUS_STYLES["Pending"];
  const isOwner     = item.OwnerEntraId === currentOid;
  const canSubmit   = isOwner && ["Pending", "Due Soon", "Overdue", "Rejected"].includes(item.Status);
  const canVerify   = isCompliance && item.Status === "Submitted";
  const isPending   = actionItemId === item.id;

  return (
    <div style={{
      border: `1px solid ${ss.bd}`,
      borderLeft: `4px solid ${ss.color}`,
      borderRadius: 12,
      background: "var(--color-background-primary)",
      transition: "box-shadow 0.15s",
    }}
      onMouseEnter={e => (e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)")}
      onMouseLeave={e => (e.currentTarget.style.boxShadow = "none")}
    >
      {/* Header */}
      <div
        role="button" tabIndex={0}
        onClick={() => { setExpanded(!expanded); setShowSubmit(false); setShowVerify(false); }}
        onKeyDown={e => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "11px 14px", cursor: "pointer" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 5, flexWrap: "wrap", gap: 4 }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 3,
                           fontWeight: 600, background: ss.bg, color: ss.color,
                           border: `0.5px solid ${ss.bd}` }}>
              {item.Status}
            </span>
            {item.EvidenceType && (
              <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3,
                             background: "var(--color-background-secondary)",
                             color: "var(--color-text-tertiary)",
                             border: "0.5px solid var(--color-border-tertiary)",
                             fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                {item.EvidenceType}
              </span>
            )}
            {isOwner && canSubmit && (
              <span style={{ fontSize: 9, fontWeight: 600, color: ss.color,
                             textTransform: "uppercase", letterSpacing: "0.5px" }}>
                Action needed
              </span>
            )}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4, marginBottom: 3 }}>
          {item.EvidenceDescription || item.Title}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between",
                      fontSize: 11, color: "var(--color-text-secondary)" }}>
          <span>{item.OwnerRole || "No owner"} · {item.Frequency || "No frequency"}</span>
          {item.LinkedControlId && (
            <span style={{ color: "var(--color-text-tertiary)" }}>
              CTL-{item.LinkedControlId.slice(-4)}
            </span>
          )}
        </div>
      </div>

      {/* Expanded */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${ss.bd}`, padding: "12px 14px" }}>

          {/* Rejection notice */}
          {item.Status === "Rejected" && item.RejectionNote && (
            <div style={{ padding: "8px 10px", background: "#FCEBEB", borderRadius: 8,
                          fontSize: 11, color: "#791F1F", marginBottom: 10,
                          border: "0.5px solid #F09595" }}>
              Rejected: {item.RejectionNote}
            </div>
          )}

          {/* Fields */}
          {item.EvidenceType && (
            <Field l="Evidence type" v={`${item.EvidenceType} — ${EVID_TYPE_LABELS[item.EvidenceType] || ""}`} />
          )}
          <Field l="Source system"  v={item.SourceSystem} />
          <Field l="Format"         v={item.EvidenceFormat} />
          <Field l="Frequency"      v={item.Frequency} />
          <Field l="Collection"     v={item.CollectionMethod} />
          {item.ValidationCriteria && <Field l="Acceptance criteria" v={item.ValidationCriteria} />}
          {item.NextDue && <Field l="Next due"       v={item.NextDue} />}
          {item.LastCollected && <Field l="Last collected" v={item.LastCollected} />}
          {item.VerifiedBy && <Field l="Verified by"   v={item.VerifiedBy} />}

          {/* Evidence link */}
          {item.EvidenceLink && (
            <div style={{ marginTop: 8 }}>
              <a href={item.EvidenceLink} target="_blank" rel="noreferrer"
                style={{ fontSize: 12, color: "var(--color-text-info)", textDecoration: "underline" }}>
                View submitted evidence ↗
              </a>
            </div>
          )}

          {/* Submit action */}
          {canSubmit && !showSubmit && (
            <button onClick={e => { e.stopPropagation(); setShowSubmit(true); }}
              style={{ marginTop: 10, width: "100%", padding: "9px", fontSize: 12,
                       borderRadius: 8, border: "none", fontWeight: 500,
                       background: "#0C447C", color: "#fff", cursor: "pointer" }}>
              Submit evidence
            </button>
          )}
          {showSubmit && (
            <SubmitPanel
              item={item}
              onSubmit={async (id, link, notes) => {
                await onSubmit(id, link, notes);
                setShowSubmit(false);
              }}
              onClose={() => setShowSubmit(false)}
              isPending={isPending}
            />
          )}

          {/* Verify action */}
          {canVerify && !showVerify && (
            <button onClick={e => { e.stopPropagation(); setShowVerify(true); }}
              style={{ marginTop: 10, width: "100%", padding: "9px", fontSize: 12,
                       borderRadius: 8, border: "none", fontWeight: 500,
                       background: "#534AB7", color: "#fff", cursor: "pointer" }}>
              Verify submission
            </button>
          )}
          {showVerify && (
            <VerifyPanel
              item={item}
              onVerify={async (id, accepted, note) => {
                await onVerify(id, accepted, note);
                setShowVerify(false);
              }}
              onClose={() => setShowVerify(false)}
              isPending={isPending}
            />
          )}
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Main component
// =============================================================================

export default function EvidenceTracker() {
  const [view, setView]     = useState("mine");
  const [search, setSearch] = useState("");
  const [actionItemId, setActionItemId] = useState(null);

  const { oid, isCompliance } = useCurrentUser();
  const qc = useQueryClient();
  const { data: all = [], isLoading, error, refetch } = useEvidence();

  const views = useMemo(() => {
    const mine     = all.filter(e => e.OwnerEntraId === oid);
    const overdue  = all.filter(e => e.Status === "Overdue");
    const submitted = all.filter(e => e.Status === "Submitted");
    return { mine, overdue, submitted };
  }, [all, oid]);

  const activeItems = useMemo(() => {
    let list = view === "mine"      ? views.mine
             : view === "overdue"   ? views.overdue
             : view === "submitted" ? views.submitted
             : all;

    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(e =>
        (e.EvidenceDescription || "").toLowerCase().includes(q) ||
        (e.EvidenceType        || "").toLowerCase().includes(q) ||
        (e.OwnerRole           || "").toLowerCase().includes(q) ||
        (e.SourceSystem        || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [view, views, all, search]);

  const handleSubmit = async (id, link, notes) => {
    setActionItemId(id);
    try {
      await evidenceApi.submit(id, link, notes);
      qc.invalidateQueries({ queryKey: ["evidence"] });
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Submit failed.");
    } finally {
      setActionItemId(null);
    }
  };

  const handleVerify = async (id, accepted, rejectionNote) => {
    setActionItemId(id);
    try {
      await evidenceApi.verify(id, accepted, rejectionNote);
      qc.invalidateQueries({ queryKey: ["evidence"] });
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Verify failed.");
    } finally {
      setActionItemId(null);
    }
  };

  const tabViews = [
    { k: "mine",      l: `My evidence (${views.mine.length})` },
    ...(isCompliance ? [
      { k: "submitted", l: `Submitted (${views.submitted.length})` },
      { k: "overdue",   l: `Overdue (${views.overdue.length})` },
    ] : []),
    { k: "all", l: `All (${all.length})` },
  ];

  if (isLoading) return <LoadingState message="Loading evidence tracker..." />;
  if (error)     return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Evidence tracker</div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Every evidence requirement created by the Zone 1 cascade lives here.
              Collect, submit, and get verified — that is the proof of compliance.
            </div>
          </div>
          <div style={{ padding: "3px 10px", background: "#E1F5EE", borderRadius: 6,
                        fontSize: 11, color: "#085041", fontWeight: 600,
                        border: "0.5px solid #5DCAA5", flexShrink: 0 }}>
            {all.length} items
          </div>
        </div>
      </div>

      {/* View tabs + search */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        {tabViews.map(t => (
          <button key={t.k} onClick={() => setView(t.k)}
            style={{ padding: "5px 12px", fontSize: 12, borderRadius: 6, cursor: "pointer",
                     fontWeight: view === t.k ? 600 : 400,
                     border: view === t.k ? "1px solid var(--color-border-info)" : "1.5px solid #C0C0C0",
                     background: view === t.k ? "var(--color-background-info)" : "var(--color-background-primary)",
                     color: view === t.k ? "var(--color-text-info)" : "var(--color-text-secondary)" }}>
            {t.l}
          </button>
        ))}
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search evidence..."
          style={{ flex: 1, minWidth: 180, fontSize: 12, padding: "6px 12px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {/* Items */}
      {activeItems.length === 0 ? (
        <EmptyState message={
          all.length === 0
            ? "No evidence items yet. Accept extraction items in the Extraction Review screen to create evidence requirements here."
            : `No items in this view.`
        } />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {activeItems.map(item => (
            <EvidenceCard
              key={item.id}
              item={item}
              currentOid={oid}
              isCompliance={isCompliance}
              onSubmit={handleSubmit}
              onVerify={handleVerify}
              actionItemId={actionItemId}
            />
          ))}
        </div>
      )}

      {activeItems.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 8 }}>
          {activeItems.length} of {all.length}
        </div>
      )}
    </>
  );
}