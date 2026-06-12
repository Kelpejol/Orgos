// =============================================================================
// LifecycleFeedback/index.jsx — Stakeholder feedback submission page
// Accessible at /lifecycle/feedback/:id
// No sidebar — standalone page for Teams link recipients.
// MSAL auth required. Enforces deadline if set.
// =============================================================================

import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { loginRequest } from "../../authConfig.js";
import { lifecycleApi } from "../../api/grcApi.js";

// =============================================================================
//  Helpers
// =============================================================================

function formatDate(dateStr) {
  if (!dateStr) return null;
  try {
    return new Date(dateStr).toLocaleDateString("en-GB", {
      day: "numeric", month: "long", year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

function deadlineStatus(deadlineStr) {
  if (!deadlineStr) return { expired: false, daysLeft: null, text: null };
  const deadline = new Date(deadlineStr);
  if (Number.isNaN(deadline.getTime())) return { expired: false, daysLeft: null, text: null };
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const deadlineStart = new Date(deadline.getFullYear(), deadline.getMonth(), deadline.getDate());
  const daysLeft = Math.round((deadlineStart - todayStart) / (1000 * 60 * 60 * 24));
  return {
    expired: daysLeft < 0,
    daysLeft: Math.max(0, daysLeft),
    text: daysLeft < 0
      ? "Feedback period has ended"
      : daysLeft === 0
        ? "Feedback closes today"
        : `${daysLeft} day${daysLeft === 1 ? "" : "s"} left to submit`,
  };
}

const CATEGORIES = [
  { value: "General",       label: "General comment" },
  { value: "Concern",       label: "Concern" },
  { value: "Suggestion",    label: "Suggestion" },
  { value: "Factual error", label: "Factual error" },
  { value: "Approval",      label: "I support this document" },
];

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
          Dragnet Solutions — Document Review
        </div>
        <p style={{ fontSize: 13, color: "#444", marginBottom: 28, lineHeight: 1.6 }}>
          You've been invited to review a document. Sign in with your Dragnet Microsoft 365
          account to submit your feedback.
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
//  Main page
// =============================================================================

export default function LifecycleFeedback() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isAuthenticated = useIsAuthenticated();
  const queryClient = useQueryClient();

  const [text, setText] = useState("");
  const [category, setCategory] = useState("General");
  const [submitted, setSubmitted] = useState(false);

  const { data: doc, isLoading, error } = useQuery({
    queryKey: ["lifecycle-doc", id],
    queryFn: () => lifecycleApi.get(id).then((r) => r.data),
    enabled: isAuthenticated && !!id,
  });

  const submitMutation = useMutation({
    mutationFn: ({ text, category }) =>
      lifecycleApi.submitFeedback(id, { text, category }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries(["lifecycle-doc", id]);
      setSubmitted(true);
    },
  });

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
        <div style={{ fontSize: 12, color: "#666" }}>Document Sensitisation Review</div>
      </div>
      <div style={{ maxWidth: 680, margin: "0 auto", padding: "32px 20px" }}>
        {children}
      </div>
    </div>
  );

  if (isLoading) {
    return shell(
      <div style={{ textAlign: "center", padding: "60px 0", color: "#888" }}>
        Loading document…
      </div>
    );
  }

  if (error || !doc) {
    return shell(
      <div style={{
        background: "#fff", border: "1px solid #F09595", borderRadius: 12,
        padding: 24, color: "#791F1F",
      }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Could not load document</div>
        <div style={{ fontSize: 12, color: "#666" }}>
          The document may have been removed or you may not have permission to access it.
        </div>
      </div>
    );
  }

  if (doc.Stage !== "Sensitisation") {
    return shell(
      <div style={{
        background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12, padding: 32,
        textAlign: "center",
      }}>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
          Feedback period has ended
        </div>
        <div style={{ fontSize: 13, color: "#666", lineHeight: 1.6 }}>
          This document is no longer in the review stage.
          {doc.Stage === "Approval" && " It has moved to the approval stage."}
          {doc.ApprovalStatus === "Approved" && " It has been approved."}
        </div>
      </div>
    );
  }

  const dl = deadlineStatus(doc.SensitisationDeadline);

  if (dl.expired) {
    return shell(
      <div style={{
        background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12, padding: 32,
        textAlign: "center",
      }}>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
          Feedback deadline has passed
        </div>
        <div style={{ fontSize: 13, color: "#666", lineHeight: 1.6 }}>
          The sensitisation period closed on {formatDate(doc.SensitisationDeadline)}.
          If you have urgent concerns, contact the document owner directly.
        </div>
      </div>
    );
  }

  if (submitted) {
    return shell(
      <div style={{
        background: "#fff", border: "1px solid #5DCAA5", borderRadius: 12, padding: 32,
        textAlign: "center",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: "50%", background: "#E1F5EE",
          display: "flex", alignItems: "center", justifyContent: "center",
          margin: "0 auto 16px", fontSize: 22,
        }}>✓</div>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8, color: "#085041" }}>
          Feedback submitted
        </div>
        <div style={{ fontSize: 13, color: "#666", lineHeight: 1.6, marginBottom: 20 }}>
          Thank you — your feedback has been sent to the document owner.
          They will consider your input before progressing the document to approval.
        </div>
        <button
          onClick={() => { setSubmitted(false); setText(""); setCategory("General"); }}
          style={{
            padding: "9px 18px", fontSize: 12, borderRadius: 8,
            border: "1px solid #C0C0C0", background: "#fff",
            cursor: "pointer", color: "#444",
          }}
        >
          Submit another comment
        </button>
      </div>
    );
  }

  return shell(
    <>
      {/* Document info */}
      <div style={{
        background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12,
        padding: 24, marginBottom: 20,
      }}>
        <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>
          {doc.DocumentCode || "—"} · {doc.DocumentType || "Document"} · {doc.Department || ""}
        </div>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 10 }}>
          {doc.Title}
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 11, padding: "2px 8px", borderRadius: 4,
            background: "#E6F1FB", color: "#0C447C", border: "0.5px solid #85B7EB",
          }}>
            Sensitisation review
          </span>
          {dl.text && (
            <span style={{
              fontSize: 11, padding: "2px 8px", borderRadius: 4,
              background: dl.daysLeft <= 2 ? "#FCEBEB" : "#FAEEDA",
              color: dl.daysLeft <= 2 ? "#791F1F" : "#633806",
              border: `0.5px solid ${dl.daysLeft <= 2 ? "#F09595" : "#FAC775"}`,
            }}>
              {dl.text}
            </span>
          )}
        </div>

        {doc.SharePointFileUrl && (
          <a
            href={doc.SharePointFileUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "inline-block", marginTop: 14, fontSize: 12,
              color: "#1F4E79", textDecoration: "underline",
            }}
          >
            View document in SharePoint →
          </a>
        )}
      </div>

      {/* Context */}
      <div style={{
        background: "#FFF8E1", border: "1px solid #FAC775", borderRadius: 10,
        padding: "12px 16px", marginBottom: 20, fontSize: 12, color: "#633806",
      }}>
        You have been invited to review this document as part of the sensitisation process.
        Your feedback will be seen by the document owner and may influence revisions
        before the document is submitted for final approval.
      </div>

      {/* Submission form */}
      <div style={{
        background: "#fff", border: "1px solid #E0E0E0", borderRadius: 12, padding: 24,
      }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>
          Submit your feedback
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={{ display: "block", fontSize: 12, color: "#555", marginBottom: 5 }}>
            Feedback type
          </label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            style={{
              width: "100%", padding: "9px 10px", fontSize: 12, borderRadius: 8,
              border: "1.5px solid #D0D0D0", background: "#fff", color: "#333",
            }}
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", fontSize: 12, color: "#555", marginBottom: 5 }}>
            Your feedback <span style={{ color: "#A32D2D" }}>*</span>
          </label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            placeholder="Please describe your concern, suggestion, or comment about this document…"
            style={{
              width: "100%", padding: "9px 10px", fontSize: 12, borderRadius: 8,
              border: "1.5px solid #D0D0D0", resize: "vertical", boxSizing: "border-box",
              fontFamily: "inherit", color: "#333",
            }}
          />
          <div style={{ fontSize: 11, color: "#999", marginTop: 4 }}>
            {text.length} characters
          </div>
        </div>

        {submitMutation.isError && (
          <div style={{
            background: "#FCEBEB", border: "1px solid #F09595", borderRadius: 8,
            padding: "10px 14px", marginBottom: 14, fontSize: 12, color: "#791F1F",
          }}>
            Failed to submit feedback. Please try again.
          </div>
        )}

        <button
          onClick={() => submitMutation.mutate({ text, category })}
          disabled={!text.trim() || submitMutation.isPending}
          style={{
            padding: "10px 24px", fontSize: 13, fontWeight: 600, borderRadius: 8,
            border: "none", background: !text.trim() ? "#CCC" : "#1D9E75",
            color: "#fff", cursor: !text.trim() ? "not-allowed" : "pointer",
            width: "100%",
          }}
        >
          {submitMutation.isPending ? "Submitting…" : "Submit feedback"}
        </button>
      </div>
    </>
  );
}
