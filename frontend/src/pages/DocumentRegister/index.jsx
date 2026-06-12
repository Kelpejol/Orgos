// =============================================================================
// pages/DocumentRegister/index.jsx
// Document Register — Tier 1. Fully wired to FastAPI backend via React Query.
// Matches prototype layout exactly. Real data from SharePoint via Graph API.
// =============================================================================

import { useState, useMemo } from "react";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field, InlineLink } from "../../components/shared/Forms.jsx";
import { LoadingState, TableSkeleton, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import { useDocuments, useSoftDeleteDocument } from "../../hooks/useGrc.js";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import { useAlert } from "../../components/shared/AlertModal.jsx";
import ReadOnlyBanner from "../../components/shared/ReadOnlyBanner.jsx";
import DocumentForm from "./DocumentForm.jsx";

const COLS = [
  { key: "document_code", label: "Code", mono: true },
  { key: "title",         label: "Title" },
  { key: "type",          label: "Type" },
  { key: "department",    label: "Dept" },
  { key: "owner",         label: "Owner" },
  { key: "current_version", label: "Rev", mono: true },
  { key: "next_review_date", label: "Next review" },
  {
    key: "linked_controls_count",
    label: "Extracted",
    title: "Number of AI-extracted candidate items sent to Extraction Review. This is not the final accepted control count.",
  },
  { key: "status",        label: "Status" },
];

const isOverdue = (d) => {
  if (!d) return false;
  const due = new Date(d);
  due.setHours(0, 0, 0, 0);
  return due < new Date().setHours(0, 0, 0, 0);
};

const getOwnerName = (owner) => {
  if (!owner) return "—";
  return owner.display_name || owner.email || "—";
};

export default function DocumentRegister({ go }) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);

  const { isCompliance } = useCurrentUserRole();
  const { confirm: showConfirm } = useAlert();
  const { data: documents = [], isLoading, error, refetch } = useDocuments();
  const softDelete = useSoftDeleteDocument();

  const filtered = useMemo(() => {
    if (!search.trim()) return documents;
    const q = search.toLowerCase();
    return documents.filter(
      (d) =>
        d.document_code?.toLowerCase().includes(q) ||
        d.title?.toLowerCase().includes(q) ||
        d.department?.toLowerCase().includes(q) ||
        getOwnerName(d.owner).toLowerCase().includes(q)
    );
  }, [documents, search]);

  // ── Detail view ──────────────────────────────────────────────────────────
  if (selected) {
    return (
      <div style={{ maxWidth: 560 }}>
        <button
          onClick={() => setSelected(null)}
          style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}
        >
          ← Back
        </button>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12, lineHeight: 1.4 }}>
          {selected.title}
        </div>
        <Field l="Document code" v={selected.document_code} />
        <Field l="Type"          v={selected.type} />
        <Field l="Department"    v={selected.department} />
        <Field l="Owner"         v={getOwnerName(selected.owner)} />
        <Field l="Version"       v={selected.current_version} />
        <Field l="Effective date"  v={selected.effective_date || "—"} />
        <Field
          l="Next review"
          v={selected.next_review_date || "—"}
          color={isOverdue(selected.next_review_date) ? "#A32D2D" : undefined}
        />
        <Field l="Standards"     v={(selected.applicable_standards || []).join(", ") || "—"} />
        <Field l="Status"        v={<StatusBadge label={selected.status} />} />
        <div style={{ marginTop: 12, display: "flex", gap: 6, flexWrap: "wrap" }}>
          <span
            title="AI-extracted candidate items sent to Extraction Review. Final accepted controls are managed after review decisions."
          >
            <InlineLink label={`${selected.linked_controls_count || 0} extracted candidates`} onClick={() => go("control")} />
          </span>
          {selected.sharepoint_url && (
            <a
              href={selected.sharepoint_url}
              target="_blank"
              rel="noreferrer"
              style={{
                fontSize: 12,
                color: "var(--color-text-info)",
                textDecoration: "underline",
                cursor: "pointer",
              }}
            >
              Open document in SharePoint ↗
            </a>
          )}
        </div>
        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
          <button
            onClick={() => setSelected(null)}
            style={{ padding: "7px 14px", fontSize: 12, borderRadius: 8, border: "1.5px solid #C0C0C0", background: "transparent", cursor: "pointer" }}
          >
            Back
          </button>
          {isCompliance && (
            <button
              onClick={() => {
                setEditing(selected);
                setSelected(null);
              }}
              style={{ padding: "7px 14px", fontSize: 12, borderRadius: 8, border: "none", background: "#378ADD", color: "#fff", cursor: "pointer" }}
            >
              Edit
            </button>
          )}
          {isCompliance && selected.status !== "Withdrawn" && (
            <button
              onClick={async () => {
                const ok = await showConfirm({
                  title: "Withdraw document?",
                  message: `Withdraw "${selected.title}"? It will be marked as Withdrawn and kept for audit history.`,
                  confirmLabel: "Withdraw",
                  cancelLabel: "Keep document",
                });
                if (!ok) return;
                await softDelete.mutateAsync(selected.id);
                setSelected(null);
              }}
              disabled={softDelete.isPending}
              style={{ padding: "7px 14px", fontSize: 12, borderRadius: 8, border: "none", background: "#A32D2D", color: "#fff", cursor: "pointer" }}
            >
              {softDelete.isPending ? "Withdrawing..." : "Withdraw"}
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Form view ────────────────────────────────────────────────────────────
  if (showForm || editing) {
    return (
      <DocumentForm
        document={editing}
        onSuccess={() => {
          setShowForm(false);
          setEditing(null);
          setSelected(null);
          refetch();
        }}
        onCancel={() => {
          setShowForm(false);
          setEditing(null);
        }}
      />
    );
  }

  // ── List view ────────────────────────────────────────────────────────────
  return (
    <>
      {!isCompliance && (
        <ReadOnlyBanner message="You have read-only access to the Document Register. Contact the Compliance team to register or withdraw documents." />
      )}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Document register</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Approved controlled documents.
          </div>
        </div>
        {isCompliance && (
          <button
            onClick={() => {
              setEditing(null);
              setShowForm(true);
            }}
            style={{ padding: "8px 16px", fontSize: 12, borderRadius: 8, border: "none", background: "#378ADD", color: "#fff", cursor: "pointer", fontWeight: 500, flexShrink: 0 }}
          >
            + Register document
          </button>
        )}
      </div>

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search documents..."
        style={{ width: "100%", fontSize: 13, padding: "10px 14px", borderRadius: 8, border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)", color: "var(--color-text-primary)", marginBottom: 10, boxSizing: "border-box", outline: "none" }}
      />

      {isLoading && <TableSkeleton rows={7} cols={COLS.length} />}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {!isLoading && !error && filtered.length === 0 && (
        <EmptyState message={search ? "No documents match your search." : "No documents registered yet."} />
      )}

      {!isLoading && !error && filtered.length > 0 && (
        <>
          <div style={{ border: "1px solid #D0D0D0", borderRadius: 10, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "var(--color-background-secondary)" }}>
                  {COLS.map((c) => (
                    <th key={c.key} title={c.title} style={{ padding: "7px 8px", textAlign: "left", fontWeight: 500, fontSize: 11, color: "var(--color-text-secondary)", whiteSpace: "nowrap" }}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((doc, i) => (
                  <tr
                    key={doc.id}
                    onClick={() => setSelected(doc)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && setSelected(doc)}
                    style={{ borderBottom: "1px solid #E8E8E8", cursor: "pointer", background: i % 2 ? "var(--color-background-secondary)" : "transparent" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-background-info)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = i % 2 ? "var(--color-background-secondary)" : "transparent")}
                  >
                    {COLS.map((col) => {
                      const v = col.key === "owner" ? getOwnerName(doc.owner) : doc[col.key];
                      const od = col.key === "next_review_date" && isOverdue(v);
                      const isSt = col.key === "status";
                      return (
                        <td
                          key={col.key}
                          title={col.title}
                          style={{
                            padding: "6px 8px",
                            color: od ? "#A32D2D" : "var(--color-text-primary)",
                            fontFamily: col.mono ? "var(--font-mono)" : undefined,
                            fontSize: col.mono ? 10 : 12,
                            fontWeight: od ? 500 : 400,
                            whiteSpace: col.key === "title" ? "normal" : "nowrap",
                          }}
                        >
                          {isSt && v ? <StatusBadge label={v} /> : (v ?? "—")}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
            {filtered.length} of {documents.length}
          </div>
        </>
      )}
    </>
  );
}
