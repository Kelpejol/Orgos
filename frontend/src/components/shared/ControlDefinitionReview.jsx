// =============================================================================
// components/shared/ControlDefinitionReview.jsx
// Reviewing control definitions raised by the library sync
// (control_register/sync.py). They are read from their defining documents —
// not inferred — so they carry no confidence score, can't be edited in the
// queue, and a document's new ones can be accepted together.
// =============================================================================

import { useState, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Field } from "./Forms.jsx";
import { useAlert } from "./AlertModal.jsx";
import apiClient from "../../api/grcApi.js";

const acceptDocument = (document, rationale) =>
  apiClient
    .post("/api/v1/queue/definitions/accept-document", { document, rationale })
    .then((r) => r.data);

export const isDefinition = (item) => Boolean(item?.ControlId) && !item?.ResolutionKey;

// =============================================================================
//  Control definition — items raised by the library sync, keyed by Control ID.
//  Read from the defining document, not inferred, so there is no confidence
//  score; a Changed item shows exactly what the document changed.
// =============================================================================

const DEFINITION_FIELDS = [
  ["requirement", "Requirement"],
  ["trigger", "Trigger"],
  ["responsibility_as_written", "Accountable / Executing"],
  ["evidence_as_written", "Evidence"],
  ["risk", "Risk"],
  ["failure_route", "Failure route"],
  ["exception_route", "Exception route"],
  ["mapping_as_written", "Mapping"],
  ["authority", "Governing authority"],
];

const asText = (v) =>
  v && typeof v === "object"
    ? Object.entries(v).map(([k, x]) => `${k}: ${x}`).join("; ")
    : v || "";

const DiffRow = ({ d }) => (
  <div style={{ marginBottom: 10 }}>
    <div style={{ fontSize: 10, fontWeight: 600, color: "var(--color-text-tertiary)",
                  textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 3 }}>
      {d.label}
    </div>
    {asText(d.before) && (
      <div style={{ fontSize: 12, lineHeight: 1.45, padding: "5px 8px", borderRadius: 6,
                    background: "#FCEBEB", color: "#791F1F", textDecoration: "line-through",
                    marginBottom: 3 }}>
        {asText(d.before)}
      </div>
    )}
    <div style={{ fontSize: 12, lineHeight: 1.45, padding: "5px 8px", borderRadius: 6,
                  background: "#E1F5EE", color: "#085041" }}>
      {asText(d.after) || <em>(no longer stated)</em>}
    </div>
  </div>
);

export const DefinitionPanel = ({ item }) => {
  const c = item.Candidate || {};
  const where = c.defined_in || {};
  const changed = item.ChangeKind === "Changed";
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 10 }}>
        Defined in <strong>{c.defined_in_label || item.SourceDocumentCode}</strong>
        {where.section ? ` · ${where.section}` : ""}
        {where.version ? ` · v${where.version}` : ""}
      </div>

      {changed && (item.Diff || []).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
            What the document changed
          </div>
          {item.Diff.map((d) => <DiffRow key={d.field} d={d} />)}
        </div>
      )}

      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
        {changed ? "Full definition after the change" : "Definition as stated"}
      </div>
      {DEFINITION_FIELDS.map(([key, label]) =>
        c[key] ? <Field key={key} l={label} v={c[key]} /> : null
      )}
      {(c.evidence || []).some((e) => e.record_id) && (
        <Field l="Records" v={c.evidence.filter((e) => e.record_id)
          .map((e) => `${e.record_id}${e.name ? ` ${e.name}` : ""}`).join("; ")} />
      )}
      {c.responsibility_ambiguous && (
        <div style={{ padding: "8px 10px", background: "#FAEEDA", borderRadius: 6,
                      fontSize: 11, color: "#633806", marginTop: 8 }}>
          “{c.responsibility_as_written}” could be one role or two. Until the Role
          Catalogue settles it, accepting will record this control as Blocked.
        </div>
      )}
      {item.DeficiencyReason && (
        <div style={{ padding: "8px 10px", background: "#FCEBEB", borderRadius: 6,
                      fontSize: 11, color: "#791F1F", marginTop: 8 }}>
          {item.DeficiencyReason} Fix it in the document; accepting records the control as stated.
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Accept a document's new control definitions together (Compliance)
//  Each control is still accepted on its own — its own Control Register row,
//  status and Audit Log record. Changed definitions stay for one-by-one review.
// =============================================================================

export const DocumentBatches = ({ items }) => {
  const [open, setOpen] = useState(null);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const { notify } = useAlert();
  const queryClient = useQueryClient();

  const groups = useMemo(() => {
    const by = {};
    items
      .filter((i) => i.ControlId && !i.ResolutionKey && i.ChangeKind !== "Changed"
                     && (!i.ReviewStatus || i.ReviewStatus === "Pending Review"))
      .forEach((i) => { (by[i.SourceDocumentCode] = by[i.SourceDocumentCode] || []).push(i); });
    return Object.entries(by).sort((a, b) => b[1].length - a[1].length);
  }, [items]);

  if (groups.length === 0) return null;

  const accept = async (doc) => {
    setBusy(true);
    try {
      const r = await acceptDocument(doc, rationale.trim());
      notify({ tone: r.failed?.length ? "warning" : "success", title: "Controls accepted", message: r.message });
      setOpen(null);
      setRationale("");
    } catch (err) {
      notify({ tone: "danger", title: "Not accepted", message: err.message || "Could not accept." });
    } finally {
      setBusy(false);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
      queryClient.invalidateQueries({ queryKey: ["zone1"] });
    }
  };

  return (
    <div style={{ marginBottom: 14, padding: "12px 14px", borderRadius: 10,
                  border: "1px solid #85B7EB", background: "#F4F9FE" }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#0C447C", marginBottom: 2 }}>
        New controls by document
      </div>
      <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginBottom: 8 }}>
        Read a document's controls below, then accept them together with one rationale. Each is
        still recorded individually. Changed controls are reviewed one by one.
      </div>
      {groups.map(([doc, list]) => (
        <div key={doc} style={{ padding: "7px 0", borderTop: "0.5px solid #D4E8FA" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 12 }}>
              <strong>{doc || "Document without a code"}</strong>
              <span style={{ color: "var(--color-text-tertiary)" }}> · {list.length} new</span>
            </span>
            {open !== doc && (
              <button onClick={() => { setOpen(doc); setRationale(""); }}
                style={{ padding: "4px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                         border: "1px solid #0C447C", background: "transparent", color: "#0C447C" }}>
                Accept all {list.length}
              </button>
            )}
          </div>
          {open === doc && (
            <div style={{ marginTop: 8 }}>
              <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} rows={2}
                placeholder={`Why these ${list.length} controls are right as stated (e.g. "Matches the approved Standard, v06")`}
                style={{ width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 8, boxSizing: "border-box",
                         border: "1.5px solid #C0C0C0", fontFamily: "var(--font-sans)", resize: "vertical" }} />
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <button disabled={busy || !rationale.trim()} onClick={() => accept(doc)}
                  style={{ padding: "7px 14px", fontSize: 12, fontWeight: 600, borderRadius: 8, border: "none",
                           background: busy || !rationale.trim() ? "#E8E8E8" : "#1D9E75",
                           color: busy || !rationale.trim() ? "#999" : "#fff",
                           cursor: busy || !rationale.trim() ? "not-allowed" : "pointer" }}>
                  {busy ? `Accepting ${list.length}…` : `Accept ${list.length} controls`}
                </button>
                <button onClick={() => setOpen(null)} disabled={busy}
                  style={{ padding: "7px 12px", fontSize: 12, borderRadius: 8, border: "1.5px solid #C0C0C0",
                           background: "transparent", color: "var(--color-text-secondary)", cursor: "pointer" }}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

