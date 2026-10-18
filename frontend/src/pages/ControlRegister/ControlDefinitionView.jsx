// =============================================================================
// pages/ControlRegister/ControlDefinitionView.jsx
// One confirmed control, as its defining document states it: the requirement,
// who is accountable and who executes, when it runs, what proves it (joined to
// the Records Catalogue), what happens when it fails, the standards it maps to,
// and where it is defined and carried out. Fields the document does not state
// are listed as such — nothing is filled in.
// =============================================================================

import { useQuery } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import OwnerDisplay from "../../components/shared/OwnerDisplay.jsx";
import apiClient from "../../api/grcApi.js";

const Section = ({ title, children }) => (
  <div style={{ marginTop: 18 }}>
    <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.4, textTransform: "uppercase",
                  color: "var(--color-text-tertiary)", marginBottom: 6 }}>
      {title}
    </div>
    {children}
  </div>
);

const Chip = ({ children, mono, tone = "neutral" }) => {
  const tones = {
    neutral: ["var(--color-background-secondary)", "var(--color-text-secondary)", "var(--color-border-tertiary)"],
    warn:    ["#FAEEDA", "#633806", "#FAC775"],
    bad:     ["#FCEBEB", "#791F1F", "#F09595"],
    good:    ["#E1F5EE", "#085041", "#5DCAA5"],
  };
  const [bg, color, bd] = tones[tone];
  return (
    <span style={{ fontSize: 10.5, padding: "2px 7px", borderRadius: 4, background: bg, color,
                   border: `0.5px solid ${bd}`, fontFamily: mono ? "var(--font-mono)" : undefined,
                   display: "inline-block", margin: "0 4px 4px 0" }}>
      {children}
    </span>
  );
};

const CATALOGUE_TONE = { governed: "good", withdrawn: "bad", "not in Catalogue": "bad",
                         "no Record ID": "warn", "not loaded": "neutral" };

const RecordRow = ({ r }) => (
  <div style={{ padding: "9px 11px", borderRadius: 8, marginBottom: 6,
                border: "1px solid var(--color-border-tertiary)" }}>
    <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
      {r.record_id && <Chip mono>{r.record_id}</Chip>}
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{r.name || r.name_as_written}</span>
      <Chip tone={CATALOGUE_TONE[r.catalogue] || "neutral"}>{r.catalogue}</Chip>
    </div>
    {r.catalogue === "governed" && (
      <div style={{ fontSize: 11.5, color: "var(--color-text-secondary)", marginTop: 4, lineHeight: 1.5 }}>
        {r.custodian && <div>Kept by {r.custodian}</div>}
        {r.location && <div>In {r.location}</div>}
        <div>
          Retention {r.retention_rule || "not stated"} · {r.retention_validation || "validation not stated"}
          {r.automated_disposition_allowed === false && " · no automated disposal"}
        </div>
      </div>
    )}
    {r.catalogue === "no Record ID" && (
      <div style={{ fontSize: 11.5, color: "#633806", marginTop: 4 }}>
        The document names this record without a Record ID, so OrgOS can't find it.
      </div>
    )}
  </div>
);

export default function ControlDefinitionView({ control, onBack }) {
  const { data: detail } = useQuery({
    queryKey: ["control", control.id],
    queryFn: () => apiClient.get(`/api/v1/controls/${control.id}`).then((r) => r.data),
    staleTime: 30_000,
  });
  const c = detail || control;
  const d = c.Definition || {};
  const where = d.defined_in || {};
  const split = d.accountable && d.executing && d.accountable !== d.executing;

  return (
    <div style={{ maxWidth: 640 }}>
      <button onClick={onBack}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none",
                 border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}>
        ← Back
      </button>

      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
        <Chip mono>{c.ControlId}</Chip>
        <StatusBadge label={c.Status || "Active"} />
      </div>
      <div style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.35, marginBottom: 10 }}>{d.title}</div>
      <div style={{ fontSize: 13.5, lineHeight: 1.55 }}>{d.requirement || c.ControlStatement}</div>

      {c.Status === "Blocked" && (
        <div style={{ marginTop: 14, padding: "10px 12px", background: "#FCEBEB", borderRadius: 8,
                      fontSize: 12, color: "#791F1F", border: "1px solid #F09595", lineHeight: 1.5 }}>
          <strong>Blocked.</strong> {c.BlockedReason || "The accountable role is not recognised."}
        </div>
      )}

      <Section title="Responsibility">
        {d.accountable ? (
          <>
            <Field l={split ? "Accountable" : "Accountable and executing"} v={d.accountable} />
            {split && <Field l="Executing" v={d.executing} />}
            <Field l="Who holds it" v={<OwnerDisplay item={c} />} />
            {d.responsibility_ambiguous && (
              <div style={{ fontSize: 11.5, color: "#633806", marginTop: 4 }}>
                “{d.responsibility_as_written}” could be one role or two; the Role Catalogue settles it.
              </div>
            )}
          </>
        ) : (
          <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
            The document names no accountable role.
          </div>
        )}
      </Section>

      <Section title="Operation">
        <Field l="Trigger" v={d.trigger || "Not stated"} />
        <Field l="Failure route" v={d.failure_route || "Not stated"} />
        <Field l="Exception route" v={d.exception_route || "Not stated"} />
        {d.authority && <Field l="Governing authority" v={d.authority} />}
        {Object.entries(d.other_fields || {}).map(([k, v]) => <Field key={k} l={k} v={v} />)}
      </Section>

      {d.risk && (
        <Section title="Risk">
          <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "#791F1F" }}>{d.risk}</div>
        </Section>
      )}

      <Section title="Evidence records">
        {(c.Records || []).length > 0
          ? c.Records.map((r, i) => <RecordRow key={r.record_id || i} r={r} />)
          : <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
              {d.evidence_as_written || "The document names no evidence."}
            </div>}
      </Section>

      <Section title="Standards">
        {(d.mapping || []).length > 0
          ? d.mapping.map((m) => <Chip key={`${m.standard} ${m.clause}`} mono>{m.standard} {m.clause}</Chip>)
          : <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
              {d.mapping_as_written || "No mapping stated for this control."}
            </div>}
      </Section>

      <Section title="Where it comes from">
        <Field l="Defined in" v={[d.defined_in_label, where.section, where.version && `v${where.version}`]
          .filter(Boolean).join(" · ")} />
        <Field l="Carried out in" v={(d.implemented_in || []).length
          ? d.implemented_in.map((i) => [i.document, i.section].filter(Boolean).join(" § ")).join("; ")
          : "No procedure cites it yet"} />
        {(d.supported_by || []).length > 0 && <Field l="Supported by" v={d.supported_by.join("; ")} />}
        <Field l="Confirmed" v={c.ConfirmedDate ? `${c.ConfirmedDate}${c.QueueItemId ? ` · queue item ${c.QueueItemId}` : ""}` : "—"} />
      </Section>

      {(d.missing_fields || []).length > 0 && (
        <Section title="Not stated in the document">
          {d.missing_fields.map((m) => <Chip key={m} tone="warn">{m}</Chip>)}
          <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)", marginTop: 2 }}>
            CDI expects every control to state these. The fix belongs in the document.
          </div>
        </Section>
      )}
    </div>
  );
}
