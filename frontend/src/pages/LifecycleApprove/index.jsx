// =============================================================================
// LifecycleApprove/index.jsx — Approver review page
// Accessible at /lifecycle/approve/:id
// No sidebar — standalone page for Teams link recipients.
// Only the designated approver can Approve or Reject. Others get a read-only view.
// =============================================================================

import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { lifecycleApi } from "../../api/grcApi.js";
import { CascadeImpactPreview } from "../../components/shared/CascadeImpactModal.jsx";
import { useAiSuggestion } from "../../hooks/useAiSuggestion.js";
import { useCurrentUser } from "../../hooks/useCurrentUser.js";

// =============================================================================
//  Helpers
// =============================================================================

function formatDate(dateStr) {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("en-GB", {
      day: "numeric", month: "long", year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

function formatDatetime(dateStr) {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleString("en-GB", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

const CATEGORY_COLOURS = {
  Concern:       { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Suggestion:    { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  "Factual error": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Approval:      { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  General:       { bg: "#F1EFE8", tx: "#444441", bd: "#B4B2A9" },
};

function CategoryBadge({ cat }) {
  const c = CATEGORY_COLOURS[cat] || CATEGORY_COLOURS.General;
  return (
    <span style={{
      fontSize: 10, padding: "1px 6px", borderRadius: 3,
      background: c.bg, color: c.tx, border: `0.5px solid ${c.bd}`,
    }}>
      {cat}
    </span>
  );
}

// =============================================================================
//  Reject modal
// =============================================================================

function RejectModal({ onConfirm, onClose, isPending }) {
  const [reason, setReason] = useState("");
  const MIN = 20;
  const valid = reason.trim().length >= MIN;

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
    }} onClick={onClose}>
      <div
        style={{
          background: "#fff", borderRadius: 14, padding: 28, width: "100%",
          maxWidth: 480, margin: "0 16px",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>
          Reject and return to Review
        </div>
        <div style={{ fontSize: 12, color: "#666", marginBottom: 18, lineHeight: 1.6 }}>
          Rejecting will return this document to the Review stage. The owner will need
          to address your concerns and re-upload before re-submitting for approval.
        </div>

        <label style={{ display: "block", fontSize: 12, color: "#555", marginBottom: 5 }}>
          Rejection reason <span style={{ color: "#A32D2D" }}>*</span>
          <span style={{ color: "#999", fontWeight: 400 }}> (minimum {MIN} characters)</span>
        </label>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={4}
          placeholder="Describe why this document cannot be approved in its current form…"
          style={{
            width: "100%", padding: "9px 10px", fontSize: 12, borderRadius: 8,
            border: "1.5px solid #D0D0D0", resize: "vertical", boxSizing: "border-box",
            fontFamily: "inherit",
          }}
        />
        <div style={{ fontSize: 11, color: reason.trim().length < MIN ? "#A32D2D" : "#999", marginTop: 4 }}>
          {reason.trim().length}/{MIN} minimum
        </div>

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 20 }}>
          <button
            onClick={onClose}
            style={{
              padding: "9px 18px", fontSize: 12, borderRadius: 8,
              border: "1px solid #C0C0C0", background: "#fff", cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => valid && onConfirm(reason.trim())}
            disabled={!valid || isPending}
            style={{
              padding: "9px 18px", fontSize: 12, fontWeight: 600, borderRadius: 8,
              border: "none", background: !valid ? "#CCC" : "#A32D2D",
              color: "#fff", cursor: !valid ? "not-allowed" : "pointer",
            }}
          >
            {isPending ? "Rejecting…" : "Reject document"}
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
//  Main page
// =============================================================================

export default function LifecycleApprove() {
  const { id } = useParams();
  const { oid: currentOid } = useCurrentUser();
  const queryClient = useQueryClient();

  const [showRejectModal, setShowRejectModal] = useState(false);
  const [showApproveConfirm, setShowApproveConfirm] = useState(false);
  const [approveNotes, setApproveNotes] = useState("");
  const [approvalImpact, setApprovalImpact] = useState(null);
  const aiAssessmentHook = useAiSuggestion(
    id,
    'ai_assessment',
    () => lifecycleApi.aiAssessment(id).then(r => r.data),
  );

  const { data: doc, isLoading, error } = useQuery({
    queryKey: ["lifecycle-approve", id],
    queryFn: () => lifecycleApi.get(id).then((r) => r.data),
    enabled: !!id,
  });

  const approveMutation = useMutation({
    mutationFn: (notes) =>
      lifecycleApi.approve(id, { notes }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries(["lifecycle-approve", id]);
      setShowApproveConfirm(false);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (rejection_reason) =>
      lifecycleApi.reject(id, { rejection_reason }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries(["lifecycle-approve", id]);
      setShowRejectModal(false);
    },
  });

  const loadAiAssessment = () =>
    aiAssessmentHook.hasSuggestion ? aiAssessmentHook.regenerate() : aiAssessmentHook.generate();

  const shell = (children) => (
    <div style={{
      minHeight: "100vh", background: "#F7F8FA",
      fontFamily: "system-ui, -apple-system, sans-serif", fontSize: 13,
    }}>
      <div style={{
        background: "#fff", borderBottom: "1px solid #E0E0E0",
        padding: "12px 24px", display: "flex", alignItems: "center", gap: 12,
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "#1F4E79" }}>OrgOS</div>
        <span style={{ color: "#CCC" }}>|</span>
        <div style={{ fontSize: 12, color: "#666" }}>Document Approval Review</div>
      </div>
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "28px 20px" }}>
        {children}
      </div>
    </div>
  );

  if (isLoading) {
    return shell(
      <div style={{ textAlign: "center", padding: "60px 0", color: "#888" }}>Loading…</div>
    );
  }

  if (error || !doc) {
    return shell(
      <div style={{
        background: "#fff", border: "1px solid #F09595", borderRadius: 12,
        padding: 24, color: "#791F1F",
      }}>
        <div style={{ fontWeight: 600 }}>Could not load document</div>
      </div>
    );
  }

  const isDesignatedApprover = doc.ApproverEntraId && currentOid === doc.ApproverEntraId;
  const isApproved = doc.ApprovalStatus === "Approved";
  const isRejected = doc.ApprovalStatus === "Rejected" && doc.Stage === "Review";
  const canDecide = isDesignatedApprover && doc.Stage === "Approval" && !isApproved;

  // Parse feedback
  let feedbackList = [];
  if (doc.SensitisationFeedback) {
    try {
      const parsed = JSON.parse(doc.SensitisationFeedback);
      if (Array.isArray(parsed)) feedbackList = parsed;
    } catch {
      feedbackList = [];
    }
  }

  return shell(
    <>
      {showRejectModal && (
        <RejectModal
          onConfirm={(reason) => rejectMutation.mutate(reason)}
          onClose={() => setShowRejectModal(false)}
          isPending={rejectMutation.isPending}
        />
      )}

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>
          {doc.DocumentCode || "—"} · {doc.DocumentType || "Document"} · {doc.Department || ""}
        </div>
        <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>{doc.Title}</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 11, padding: "2px 8px", borderRadius: 4,
            background: "#E6F1FB", color: "#0C447C", border: "0.5px solid #85B7EB",
          }}>
            {doc.Stage === "Approval" ? "Pending approval" : doc.Stage}
          </span>
          {isApproved && (
            <span style={{
              fontSize: 11, padding: "2px 8px", borderRadius: 4,
              background: "#E1F5EE", color: "#085041", border: "0.5px solid #5DCAA5",
            }}>
              Approved — {formatDate(doc.ApprovedDate)}
            </span>
          )}
          {isRejected && (
            <span style={{
              fontSize: 11, padding: "2px 8px", borderRadius: 4,
              background: "#FCEBEB", color: "#791F1F", border: "0.5px solid #F09595",
            }}>
              Rejected — returned to Review
            </span>
          )}
        </div>
      </div>

      {/* Role banner */}
      {!isDesignatedApprover && doc.Stage === "Approval" && (
        <div style={{
          background: "#FFF8E1", border: "1px solid #FAC775", borderRadius: 10,
          padding: "12px 16px", marginBottom: 20, fontSize: 12, color: "#633806",
        }}>
          You are viewing this document as an observer.
          Only <strong>{doc.ApproverName || "the designated approver"}</strong> can approve or reject this document.
        </div>
      )}

      {/* Two-column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20 }}>
        {/* Left column: document + feedback */}
        <div>
          {/* Document details */}
          <div style={{
            background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12,
            padding: 20, marginBottom: 16,
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>Document details</div>
            {[
              ["Owner",           doc.OwnerName || "—"],
              ["Approver",        doc.ApproverName || "—"],
              ["Submitted for approval", doc.SubmittedForApproval ? formatDate(doc.SubmittedForApproval) : "—"],
              ["CDI status",      doc.CDIStatus || "—"],
              ["Rejection count", String(doc.RejectionCount || 0)],
              ["Standards",       doc.StandardsMapping || "—"],
            ].map(([l, v]) => (
              <div key={l} style={{
                display: "flex", justifyContent: "space-between",
                padding: "5px 0", borderBottom: "0.5px solid #F0F0F0", fontSize: 12,
              }}>
                <span style={{ color: "#777" }}>{l}</span>
                <span style={{ color: "#222", fontWeight: 500 }}>{v}</span>
              </div>
            ))}
            {doc.SharePointFileUrl && (
              <a
                href={doc.SharePointFileUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "inline-block", marginTop: 12, fontSize: 12,
                  color: "#1F4E79", textDecoration: "underline",
                }}
              >
                Open document in SharePoint →
              </a>
            )}
          </div>

          {/* AI approval brief — document merits + neutral change summary.
              The approver does NOT see raw stakeholder comments. */}
          {(() => {
            const brief = aiAssessmentHook.suggestion?.brief || {};
            const ready = brief.readiness === "Ready for approval";
            return (
              <div style={{
                background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12, padding: 20,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>AI approval brief</div>
                  {aiAssessmentHook.hasSuggestion && !aiAssessmentHook.suggestion?.error && (
                    <span style={{ fontSize: 11, padding: "2px 10px", borderRadius: 20,
                      background: ready ? "#E1F5EE" : "#FDF3E2", color: ready ? "#085041" : "#8A5A00",
                      border: `0.5px solid ${ready ? "#5DCAA5" : "#F0CE94"}`, fontWeight: 600 }}>
                      {brief.readiness || (ready ? "Ready for approval" : "Review recommended")}
                    </span>
                  )}
                </div>

                {!aiAssessmentHook.hasSuggestion && !aiAssessmentHook.loading && (
                  <>
                    <div style={{ fontSize: 12, color: "#666", lineHeight: 1.6, marginBottom: 12 }}>
                      Generate a neutral brief on this document — its purpose, scope, standards
                      coverage, CDI status, key controls, and what changed during sensitisation.
                    </div>
                    <button onClick={loadAiAssessment} style={{
                      width: "100%", padding: "9px", fontSize: 12, fontWeight: 500, borderRadius: 8,
                      border: "1px solid #C0C0C0", background: "#fff", cursor: "pointer", color: "#333" }}>
                      Generate approval brief
                    </button>
                  </>
                )}
                {aiAssessmentHook.loading && (
                  <div style={{ textAlign: "center", padding: "24px 0", color: "#888", fontSize: 12 }}>
                    Preparing the brief…
                  </div>
                )}
                {aiAssessmentHook.hasSuggestion && !aiAssessmentHook.suggestion?.error && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {brief.readiness_note && (
                      <div style={{ fontSize: 12.5, color: "#333", lineHeight: 1.6,
                        padding: "10px 12px", background: "#F8F8F8", borderRadius: 8 }}>
                        {brief.readiness_note}
                      </div>
                    )}
                    {[["Purpose", brief.purpose], ["Scope", brief.scope],
                      ["Standards", brief.standards_coverage], ["Document quality", brief.cdi_note]]
                      .filter(([, v]) => v).map(([l, v]) => (
                      <div key={l}>
                        <div style={{ fontSize: 10.5, fontWeight: 700, color: "#999",
                          textTransform: "uppercase", letterSpacing: "0.4px", marginBottom: 3 }}>{l}</div>
                        <div style={{ fontSize: 12.5, color: "#333", lineHeight: 1.5 }}>{v}</div>
                      </div>
                    ))}
                    {brief.key_controls?.length > 0 && (
                      <div>
                        <div style={{ fontSize: 10.5, fontWeight: 700, color: "#999",
                          textTransform: "uppercase", letterSpacing: "0.4px", marginBottom: 5 }}>Key controls</div>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {brief.key_controls.map((c, i) => (
                            <li key={i} style={{ fontSize: 12.5, color: "#333", lineHeight: 1.5, marginBottom: 2 }}>{c}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div>
                      <div style={{ fontSize: 10.5, fontWeight: 700, color: "#085041",
                        textTransform: "uppercase", letterSpacing: "0.4px", marginBottom: 5 }}>
                        Changed during sensitisation
                      </div>
                      {brief.change_summary?.length > 0 ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                          {brief.change_summary.map((c, i) => (
                            <div key={i} style={{ fontSize: 12, color: "#0B5C48", lineHeight: 1.5,
                              padding: "6px 10px", background: "#E7F5F0", borderRadius: 8,
                              border: "0.5px solid #9FD9C8" }}>{c}</div>
                          ))}
                        </div>
                      ) : (
                        <div style={{ fontSize: 12, color: "#999" }}>No amendments recorded.</div>
                      )}
                    </div>
                    <button onClick={loadAiAssessment} style={{ fontSize: 11, color: "#888",
                      background: "none", border: "none", cursor: "pointer", padding: 0,
                      textDecoration: "underline", alignSelf: "flex-start" }}>
                      Re-generate brief
                    </button>
                  </div>
                )}
                {aiAssessmentHook.suggestion?.error && (
                  <div style={{ fontSize: 12, color: "#888" }}>
                    {aiAssessmentHook.suggestion.error}
                    <button onClick={loadAiAssessment} style={{ display: "block", marginTop: 6,
                      fontSize: 11, color: "#888", background: "none", border: "none",
                      cursor: "pointer", padding: 0, textDecoration: "underline" }}>Try again</button>
                  </div>
                )}
              </div>
            );
          })()}
        </div>

        {/* Right column: decision */}
        <div>
          {/* Decision panel */}
          {canDecide && (
            <div style={{
              background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12, padding: 20,
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
                Your decision
              </div>
              <div style={{ fontSize: 12, color: "#666", marginBottom: 16, lineHeight: 1.5 }}>
                As the designated approver, only you can approve or reject this document.
              </div>

              {!showApproveConfirm ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <button
                    onClick={() => setShowApproveConfirm(true)}
                    style={{
                      width: "100%", padding: "11px", fontSize: 13, fontWeight: 600,
                      borderRadius: 8, border: "none", background: "#1D9E75",
                      color: "#fff", cursor: "pointer",
                    }}
                  >
                    Approve document
                  </button>
                  <button
                    onClick={() => setShowRejectModal(true)}
                    style={{
                      width: "100%", padding: "11px", fontSize: 13,
                      borderRadius: 8, border: "1.5px solid #F09595",
                      background: "#fff", color: "#791F1F", cursor: "pointer",
                    }}
                  >
                    Reject — return to Review
                  </button>
                </div>
              ) : (
                <div>
                  {/* Cascade impact — what approving will create/update (DINT §5.3.1) */}
                  <div style={{ marginBottom: 12 }}>
                    <CascadeImpactPreview
                      impactUrl={`/api/v1/lifecycle/documents/${id}/approval-impact`}
                      onImpact={setApprovalImpact}
                    />
                  </div>
                  <label style={{ display: "block", fontSize: 12, color: "#555", marginBottom: 5 }}>
                    Approval notes (optional)
                  </label>
                  <textarea
                    value={approveNotes}
                    onChange={(e) => setApproveNotes(e.target.value)}
                    rows={3}
                    placeholder="Any conditions, notes, or observations for the record…"
                    style={{
                      width: "100%", padding: "9px 10px", fontSize: 12, borderRadius: 8,
                      border: "1.5px solid #D0D0D0", resize: "vertical",
                      boxSizing: "border-box", fontFamily: "inherit", marginBottom: 12,
                    }}
                  />
                  {approveMutation.isError && (
                    <div style={{
                      background: "#FCEBEB", border: "1px solid #F09595", borderRadius: 8,
                      padding: "8px 12px", marginBottom: 10, fontSize: 12, color: "#791F1F",
                    }}>
                      Failed to approve. Please try again.
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      onClick={() => setShowApproveConfirm(false)}
                      style={{
                        flex: 1, padding: "9px", fontSize: 12, borderRadius: 8,
                        border: "1px solid #C0C0C0", background: "#fff", cursor: "pointer",
                      }}
                    >
                      Back
                    </button>
                    <button
                      onClick={() => approveMutation.mutate(approveNotes || null)}
                      disabled={approveMutation.isPending || approvalImpact?.blocked}
                      style={{
                        flex: 2, padding: "9px", fontSize: 13, fontWeight: 600,
                        borderRadius: 8, border: "none",
                        background: approveMutation.isPending || approvalImpact?.blocked ? "#E8E8E8" : "#1D9E75",
                        color: approveMutation.isPending || approvalImpact?.blocked ? "#999" : "#fff",
                        cursor: approveMutation.isPending || approvalImpact?.blocked ? "not-allowed" : "pointer",
                      }}
                    >
                      {approveMutation.isPending ? "Approving…" : approvalImpact?.blocked ? "Approval blocked" : "Confirm approval"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Read-only: already decided */}
          {isApproved && (
            <div style={{
              background: "#E1F5EE", border: "1px solid #5DCAA5", borderRadius: 12,
              padding: 20, textAlign: "center",
            }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#085041", marginBottom: 4 }}>
                Document approved
              </div>
              <div style={{ fontSize: 12, color: "#085041" }}>
                Approved by {doc.ApproverName || "the approver"} on {formatDate(doc.ApprovedDate)}.
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
