// =============================================================================
// LifecycleApprove/index.jsx — Approver review page
// Accessible at /lifecycle/approve/:id
// No sidebar — standalone page for Teams link recipients.
// Only the designated approver can Approve or Reject. Others get a read-only view.
// =============================================================================

import { useState } from "react";
import { useParams } from "react-router-dom";
import { useIsAuthenticated, useMsal, useAccount } from "@azure/msal-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { loginRequest } from "../../authConfig.js";
import { lifecycleApi } from "../../api/grcApi.js";
import { useAiSuggestion } from "../../hooks/useAiSuggestion.js";

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
//  Login gate
// =============================================================================

function LoginGate() {
  const { instance } = useMsal();
  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center",
      justifyContent: "center", background: "#F5F5F5",
      fontFamily: "system-ui, -apple-system, sans-serif",
    }}>
      <div style={{
        background: "#fff", padding: "40px 36px", borderRadius: 16,
        border: "1px solid #E0E0E0", textAlign: "center", maxWidth: 380, width: "100%",
      }}>
        <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>OrgOS</div>
        <div style={{ fontSize: 13, color: "#666", marginBottom: 24 }}>
          Dragnet Solutions — Document Approval
        </div>
        <p style={{ fontSize: 13, color: "#444", marginBottom: 28, lineHeight: 1.6 }}>
          You've been designated as the approver for a document. Sign in to review
          the document and stakeholder feedback.
        </p>
        <button
          onClick={() => instance.loginPopup(loginRequest)}
          style={{
            width: "100%", padding: "12px", fontSize: 13, fontWeight: 600,
            borderRadius: 10, border: "none", background: "#1F4E79",
            color: "#fff", cursor: "pointer",
          }}
        >
          Sign in with Microsoft 365
        </button>
      </div>
    </div>
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
  const isAuthenticated = useIsAuthenticated();
  const { accounts } = useMsal();
  const queryClient = useQueryClient();

  const currentAccount = accounts?.[0] || null;
  const currentOid = currentAccount?.idTokenClaims?.oid || "";

  const [showRejectModal, setShowRejectModal] = useState(false);
  const [showApproveConfirm, setShowApproveConfirm] = useState(false);
  const [approveNotes, setApproveNotes] = useState("");
  const aiAssessmentHook = useAiSuggestion(
    id,
    'ai_assessment',
    () => lifecycleApi.aiAssessment(id).then(r => r.data),
  );

  const { data: doc, isLoading, error } = useQuery({
    queryKey: ["lifecycle-approve", id],
    queryFn: () => lifecycleApi.get(id).then((r) => r.data),
    enabled: isAuthenticated && !!id,
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

  if (!isAuthenticated) return <LoginGate />;

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

          {/* Stakeholder feedback */}
          <div style={{
            background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12,
            padding: 20,
          }}>
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              marginBottom: 14,
            }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                Stakeholder feedback
              </div>
              <span style={{
                fontSize: 11, padding: "2px 8px", borderRadius: 10,
                background: "#F0F0F0", color: "#666",
              }}>
                {feedbackList.length} {feedbackList.length === 1 ? "comment" : "comments"}
              </span>
            </div>

            {feedbackList.length === 0 ? (
              <div style={{
                textAlign: "center", padding: "32px 0", color: "#AAA", fontSize: 12,
              }}>
                No feedback submitted during sensitisation.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {feedbackList.map((f, i) => (
                  <div key={i} style={{
                    border: "1px solid #EEE", borderRadius: 10,
                    padding: "12px 14px", background: "#FAFAFA",
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <div style={{
                          width: 28, height: 28, borderRadius: "50%", background: "#E6F1FB",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: 12, fontWeight: 600, color: "#0C447C", flexShrink: 0,
                        }}>
                          {(f.submittedBy || "?")[0].toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 500 }}>
                            {f.submittedBy || "Unknown"}
                          </div>
                          <div style={{ fontSize: 10, color: "#999" }}>
                            {formatDatetime(f.submittedAt)}
                          </div>
                        </div>
                      </div>
                      <CategoryBadge cat={f.category || "General"} />
                    </div>
                    <div style={{ fontSize: 12, color: "#333", lineHeight: 1.5 }}>
                      {f.text}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right column: AI assessment + decision */}
        <div>
          {/* AI assessment */}
          <div style={{
            background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12,
            padding: 20, marginBottom: 16,
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>AI assessment</div>
            {!aiAssessmentHook.hasSuggestion && !aiAssessmentHook.loading && (
              <>
                <div style={{ fontSize: 12, color: "#666", lineHeight: 1.6, marginBottom: 12 }}>
                  Get an AI analysis of whether the document appears to address
                  stakeholder concerns and is ready for approval.
                </div>
                <button
                  onClick={loadAiAssessment}
                  style={{
                    width: "100%", padding: "9px", fontSize: 12, fontWeight: 500,
                    borderRadius: 8, border: "1px solid #C0C0C0", background: "#fff",
                    cursor: "pointer", color: "#333",
                  }}
                >
                  Run AI assessment
                </button>
              </>
            )}
            {aiAssessmentHook.loading && (
              <div style={{ textAlign: "center", padding: "20px 0", color: "#888", fontSize: 12 }}>
                Analysing document…
              </div>
            )}
            {aiAssessmentHook.hasSuggestion && !aiAssessmentHook.suggestion?.error && (
              <div>
                <div style={{
                  display: "flex", gap: 8, alignItems: "center", marginBottom: 12,
                }}>
                  <span style={{
                    fontSize: 11, padding: "2px 8px", borderRadius: 4,
                    background: aiAssessmentHook.suggestion?.assessment?.ready_for_approval ? "#E1F5EE" : "#FCEBEB",
                    color: aiAssessmentHook.suggestion?.assessment?.ready_for_approval ? "#085041" : "#791F1F",
                    border: `0.5px solid ${aiAssessmentHook.suggestion?.assessment?.ready_for_approval ? "#5DCAA5" : "#F09595"}`,
                  }}>
                    {aiAssessmentHook.suggestion?.assessment?.ready_for_approval ? "Ready for approval" : "Not yet ready"}
                  </span>
                  {aiAssessmentHook.suggestion?.assessment?.confidence && (
                    <span style={{ fontSize: 11, color: "#888" }}>
                      {aiAssessmentHook.suggestion.assessment.confidence} confidence
                    </span>
                  )}
                  {aiAssessmentHook.isFromCache && (
                    <span style={{ fontSize: 10, color: "#9ca3af" }}>(cached)</span>
                  )}
                </div>
                {aiAssessmentHook.suggestion?.assessment?.approver_note && (
                  <div style={{
                    fontSize: 12, color: "#333", lineHeight: 1.6, marginBottom: 10,
                    padding: "10px 12px", background: "#F8F8F8", borderRadius: 8,
                  }}>
                    {aiAssessmentHook.suggestion.assessment.approver_note}
                  </div>
                )}
                {aiAssessmentHook.suggestion?.assessment?.unresolved_concerns?.length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "#791F1F", marginBottom: 6 }}>
                      Unresolved concerns
                    </div>
                    {aiAssessmentHook.suggestion.assessment.unresolved_concerns.map((c, i) => (
                      <div key={i} style={{
                        fontSize: 11, color: "#791F1F", padding: "3px 0",
                        borderBottom: "0.5px solid #F0F0F0",
                      }}>
                        · {c}
                      </div>
                    ))}
                  </div>
                )}
                <button
                  onClick={loadAiAssessment}
                  style={{
                    fontSize: 11, color: "#888", background: "none", border: "none",
                    cursor: "pointer", padding: 0, textDecoration: "underline",
                  }}
                >
                  Re-run assessment
                </button>
              </div>
            )}
            {aiAssessmentHook.suggestion?.error && (
              <div style={{ fontSize: 12, color: "#888" }}>
                {aiAssessmentHook.suggestion.error}
                <button
                  onClick={loadAiAssessment}
                  style={{
                    display: "block", marginTop: 6, fontSize: 11, color: "#888",
                    background: "none", border: "none", cursor: "pointer",
                    padding: 0, textDecoration: "underline",
                  }}
                >
                  Try again
                </button>
              </div>
            )}
          </div>

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
                      disabled={approveMutation.isPending}
                      style={{
                        flex: 2, padding: "9px", fontSize: 13, fontWeight: 600,
                        borderRadius: 8, border: "none", background: "#1D9E75",
                        color: "#fff", cursor: "pointer",
                      }}
                    >
                      {approveMutation.isPending ? "Approving…" : "Confirm approval"}
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
