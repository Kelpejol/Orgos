// =============================================================================
// pages/DocumentStandards/index.jsx
//
// The document standard, in one place.
//   The standard     what every controlled document must meet — read from the CDI
//                    Procedure itself, so it is what OrgOS enforces.
//   Check a document upload a file and see how it fares. Nothing is saved.
//   Convert to CDT   (Compliance) replace a document's hand-typed header block with
//                    the template cover, with proof that nothing else changed.
// =============================================================================

import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "../../api/grcApi.js";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import { LoadingState, ErrorState } from "../../components/shared/LoadingState.jsx";
import {
  ENFORCEMENT, STATUS, GROUPS, Pill, card, ResultCard, groupResults,
} from "../../components/shared/StandardResults.jsx";

const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// ── API ─────────────────────────────────────────────────────────────────────

// File uploads go through fetch, as elsewhere in OrgOS: the shared client defaults to JSON,
// and axios would turn a FormData body into JSON under that default.
async function postForm(path, form) {
  const resp = await fetch(`${BASE}${path}`, { method: "POST", credentials: "include", body: form });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : d?.message || "The request failed.");
  }
  return body;
}

const api = {
  standard: () => apiClient.get("/api/v1/doc-standards/standard").then((r) => r.data),
  check: (file) => {
    const form = new FormData();
    form.append("file", file);
    return postForm("/api/v1/doc-standards/check", form);
  },
  preview: ({ file, itemId }) => {
    const form = new FormData();
    if (file) form.append("file", file);
    if (itemId) form.append("item_id", itemId);
    return postForm("/api/v1/doc-standards/convert/preview", form);
  },
  apply: (itemId) =>
    apiClient.post("/api/v1/doc-standards/convert/apply", { item_id: itemId }).then((r) => r.data),
  lifecycle: () => apiClient.get("/api/v1/lifecycle/documents").then((r) => r.data),
  download: async (file, kind) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    const resp = await fetch(`${BASE}/api/v1/doc-standards/convert/download`, {
      method: "POST", credentials: "include", body: form,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "The download failed.");
    }
    const blob = await resp.blob();
    const name = /filename="([^"]+)"/.exec(resp.headers.get("content-disposition") || "")?.[1] || "converted.docx";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  },
};

// An apply refusal carries { message, plan }; the shared client stringifies it.
function errorText(err) {
  const raw = err?.message || "Something went wrong.";
  try {
    const parsed = JSON.parse(raw);
    return parsed.message || raw;
  } catch {
    return raw;
  }
}

// ── small pieces ────────────────────────────────────────────────────────────

const Heading = ({ children, hint }) => (
  <div style={{ margin: "20px 0 8px" }}>
    <div style={{ fontSize: 13, fontWeight: 600 }}>{children}</div>
    {hint && <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 2 }}>{hint}</div>}
  </div>
);

const Table = ({ head, rows, widths }) => (
  <div style={{ overflowX: "auto" }}>
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr>
          {head.map((h, i) => (
            <th key={h} style={{ textAlign: "left", padding: "6px 10px", fontSize: 10, fontWeight: 600,
                                 textTransform: "uppercase", letterSpacing: "0.4px",
                                 color: "var(--color-text-tertiary)",
                                 borderBottom: "1px solid var(--color-border-tertiary, #E0E0E0)",
                                 width: widths?.[i] }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((c, j) => (
              <td key={j} style={{ padding: "6px 10px", verticalAlign: "top", lineHeight: 1.45,
                                   borderBottom: "0.5px solid var(--color-border-tertiary, #E8E8E8)" }}>
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const Tab = ({ active, onClick, children }) => (
  <button
    onClick={onClick}
    style={{
      padding: "8px 16px", fontSize: 13, cursor: "pointer", background: "transparent",
      border: "none", borderBottom: active ? "2px solid #0C447C" : "2px solid transparent",
      color: active ? "#0C447C" : "var(--color-text-secondary)", fontWeight: active ? 600 : 400,
    }}
  >
    {children}
  </button>
);

const Button = ({ children, onClick, disabled, kind = "primary" }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    style={{
      padding: "8px 16px", fontSize: 12, fontWeight: 600, borderRadius: 7, cursor: disabled ? "not-allowed" : "pointer",
      border: kind === "primary" ? "none" : "1.5px solid #C0C0C0",
      background: disabled ? "#E8E8E8" : kind === "primary" ? "#1D9E75" : "transparent",
      color: disabled ? "#999" : kind === "primary" ? "#fff" : "var(--color-text-primary)",
    }}
  >
    {children}
  </button>
);

// ── Tab 1: the standard ─────────────────────────────────────────────────────

export function StandardTab() {
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["doc-standard"], queryFn: api.standard, staleTime: 600_000 });
  const [typeCode, setTypeCode] = useState("STD");
  if (isLoading) return <LoadingState message="Loading the standard..." />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  const type = data.types.find((t) => t.code === typeCode) || data.types[0];
  const byId = Object.fromEntries(data.checks.map((c) => [c.id, c]));

  return (
    <div>
      <div style={{ ...card, background: "#E6F1FB", border: "0.5px solid #85B7EB", color: "#0C447C", fontSize: 12, lineHeight: 1.6 }}>
        <strong>Every controlled document must meet this standard before it is approved.</strong>{" "}
        It is the validation section of the CDI Procedure ({data.source.code}), word for word. OrgOS
        enforces {data.built} of its {data.total} checks today; the other {data.total - data.built} are listed
        below so you can see what is <em>not</em> covered yet. A document that passes is never a guarantee about
        the checks that cannot run.
      </div>

      <Heading hint="Pick a document type to see what it must contain and which checks apply.">
        What each type of document is for
      </Heading>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {data.types.map((t) => (
          <button key={t.code} onClick={() => setTypeCode(t.code)}
            style={{
              padding: "5px 12px", fontSize: 12, borderRadius: 6, cursor: "pointer",
              border: t.code === typeCode ? "1px solid #0C447C" : "1.5px solid #C0C0C0",
              background: t.code === typeCode ? "#E6F1FB" : "var(--color-background-primary)",
              color: t.code === typeCode ? "#0C447C" : "var(--color-text-secondary)",
              fontWeight: t.code === typeCode ? 600 : 400,
            }}>
            {t.code}
          </button>
        ))}
      </div>
      <div style={card}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{type.type} <span style={{ fontWeight: 400, color: "var(--color-text-secondary)" }}>· {type.layer}</span></div>
        <div style={{ fontSize: 12, marginTop: 8 }}><strong>Its main content is:</strong> {type.main_content}</div>
        <div style={{ fontSize: 12, marginTop: 6, lineHeight: 1.5 }}><strong>Does it define controls?</strong> {type.defines_controls}</div>
        <div style={{ fontSize: 12, marginTop: 10 }}><strong>Checks that apply:</strong></div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
          {type.applies.map((id) => {
            const c = byId[id];
            return (
              <span key={id} title={`${c.name} — ${c.built ? "enforced by OrgOS" : "not enforced yet: " + c.needs}`}
                style={{ opacity: c.built ? 1 : 0.55 }}>
                <Pill tone={ENFORCEMENT[c.enforcement]}>{id}{c.built ? "" : " · not yet"}</Pill>
              </span>
            );
          })}
        </div>
      </div>

      <Heading hint="CDI Procedure 7.3. Every controlled document has these.">Required sections</Heading>
      <Table head={["Section", "What it holds", "Required"]} widths={["160px", "auto", "130px"]}
        rows={data.required_sections.map((s) => [s.section, s.content, s.required])} />

      <Heading hint="Annex C. Every control a Standard defines must state all of these.">What a control must state</Heading>
      <Table head={["Field", "Rule", "Mandatory"]} widths={["210px", "auto", "190px"]}
        rows={data.control_fields.map((f) => [<strong key={f.field}>{f.field}</strong>, f.rule, f.mandatory])} />

      <Heading hint="Annex A. The facts the Document Register holds about every document.">The document's register card</Heading>
      <details>
        <summary style={{ cursor: "pointer", fontSize: 12, color: "#0C447C" }}>Show all {data.register_fields.length} fields</summary>
        <div style={{ marginTop: 8 }}>
          <Table head={["Field", "Rule", "Mandatory"]} widths={["210px", "auto", "190px"]}
            rows={data.register_fields.map((f) => [<strong key={f.field}>{f.field}</strong>, f.rule, f.mandatory])} />
        </div>
      </details>

      <Heading hint="The CDI Procedure's own validation checks. 'Enforced' means OrgOS runs it today.">
        The {data.total} checks
      </Heading>
      <Table head={["Check", "What it requires", "If it fails", "In OrgOS"]} widths={["56px", "auto", "150px", "230px"]}
        rows={data.checks.map((c) => [
          <strong key={c.id}>{c.id}</strong>, c.name,
          <Pill key="e" tone={ENFORCEMENT[c.enforcement]}>{ENFORCEMENT[c.enforcement].label}</Pill>,
          c.built ? <Pill key="b" tone={STATUS.pass}>Enforced</Pill>
                  : <span key="n" style={{ color: "var(--color-text-secondary)" }}>Not yet — {c.needs}</span>,
        ])} />

      <Heading hint="Annex B. The lists the checks use.">Reference data</Heading>
      <details>
        <summary style={{ cursor: "pointer", fontSize: 12, color: "#0C447C" }}>Function codes, retired codes and approval routes</summary>
        <div style={{ marginTop: 8 }}>
          <Table head={["Function code", "Covers"]} widths={["110px", "auto"]}
            rows={data.reference_data.function_codes.map((f) => [<strong key={f.code}>{f.code}</strong>, f.function])} />
          <Heading>Who approves, by domain</Heading>
          <Table head={["Domain", "First pass", "Final approval"]}
            rows={data.reference_data.domain_routes.map((r) => [r.domain, r.first_pass, r.final_approval])} />
          <Heading>Retired function codes (never use)</Heading>
          <Table head={["Retired", "Was", "Use now"]} widths={["110px", "auto", "110px"]}
            rows={data.reference_data.retired_codes.map((r) => [<strong key={r.code}>{r.code}</strong>, r.former, r.current])} />
        </div>
      </details>
    </div>
  );
}

// ── Tab 2: check a document ─────────────────────────────────────────────────

function CheckTab() {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState(null);
  const input = useRef(null);

  const run = async () => {
    setBusy(true); setError(""); setReport(null);
    try { setReport(await api.check(file)); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };

  const grouped = useMemo(() => groupResults(report?.results), [report]);

  const tone = report && { blocked: STATUS.fail, decision: STATUS.flag, clear: STATUS.pass }[report.verdict];

  return (
    <div>
      <div style={{ ...card, fontSize: 12, lineHeight: 1.6 }}>
        Upload a document (.docx or .pdf) to see how it fares against the standard. <strong>Nothing is saved</strong> —
        this does not create a Lifecycle entry. Use it while you are writing, before you submit.
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", margin: "12px 0", flexWrap: "wrap" }}>
        <input ref={input} type="file" accept=".docx,.pdf" style={{ display: "none" }}
          onChange={(e) => { setFile(e.target.files[0] || null); setReport(null); setError(""); }} />
        <Button kind="secondary" onClick={() => input.current?.click()}>{file ? "Choose another file" : "Choose a file"}</Button>
        {file && <span style={{ fontSize: 12 }}>{file.name}</span>}
        <Button onClick={run} disabled={!file || busy}>{busy ? "Checking..." : "Check this document"}</Button>
      </div>
      {busy && (
        <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
          Checking against the standard and the library. The first check after a restart reads every library
          document and can take a minute or two; later checks are quick.
        </div>
      )}
      {error && <div style={{ ...card, background: "#FCEBEB", border: "1px solid #F09595", color: "#791F1F", fontSize: 12 }}>{error}</div>}

      {report && (
        <div style={{ marginTop: 14 }}>
          <div style={{ ...card, background: tone.bg, border: `1px solid ${tone.bd}`, color: tone.tx }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>
              {report.verdict === "blocked" ? "Not ready for approval" : report.verdict === "decision" ? "Needs a decision" : "No problems found"}
            </div>
            <div style={{ fontSize: 12, marginTop: 4, lineHeight: 1.5 }}>{report.headline}</div>
            <div style={{ fontSize: 11, marginTop: 6, opacity: 0.85 }}>
              {report.checks_run} of {report.checks_total} checks ran
              {!report.cross_document && " · the library was not available, so checks that compare documents could not run"}
            </div>
          </div>

          <div style={{ fontSize: 12, margin: "10px 0", lineHeight: 1.7 }}>
            <strong>{report.document.title || report.document.file}</strong>
            {report.document.code && <> · <code>{report.document.code}</code></>}
            {" · "}reads as {report.document.role.toLowerCase()} · defines {report.document.controls_defined_here} control(s),
            states {report.document.controls_stated}
          </div>

          {report.context_notes?.length > 0 && (
            <div style={{ ...card, background: "#FAEEDA", border: "0.5px solid #FAC775", color: "#633806", fontSize: 12, marginBottom: 10 }}>
              {report.context_notes.map((n, i) => <div key={i}>{n}</div>)}
            </div>
          )}

          {GROUPS.filter((g) => grouped[g.key]?.length).map((g) => (
            <details key={g.key} open={g.open} style={{ marginBottom: 10 }}>
              <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600, margin: "6px 0" }}>
                <Pill tone={STATUS[g.key]}>{grouped[g.key].length}</Pill> {g.title}
              </summary>
              {grouped[g.key].map((r) => <ResultCard key={r.id} r={r} />)}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tab 3: convert to the CDT ───────────────────────────────────────────────

const Rows = ({ rows }) => (
  <Table head={["", ""]} widths={["200px", "auto"]}
    rows={rows.map((r) => [<strong key={r.label}>{r.label}</strong>, r.value || <span style={{ color: "var(--color-text-tertiary)" }}>(blank)</span>])} />
);

export function PlanView({ plan }) {
  return (
    <div>
      <div style={{ ...card, background: plan.ok ? STATUS.pass.bg : STATUS.fail.bg,
                    border: `1px solid ${plan.ok ? STATUS.pass.bd : STATUS.fail.bd}`,
                    color: plan.ok ? STATUS.pass.tx : STATUS.fail.tx }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>
          {plan.ok ? "Ready to convert — every proof holds" : "This document cannot be converted"}
        </div>
        <div style={{ fontSize: 12, marginTop: 4, lineHeight: 1.5 }}>
          {plan.ok
            ? `${plan.title} (${plan.code}) will be built on the ${plan.template} template.`
            : plan.reason}
        </div>
      </div>

      {plan.proofs?.length > 0 && (
        <>
          <Heading hint="Nothing is offered unless all of these hold. They are checked on the converted file itself.">Proofs</Heading>
          {plan.proofs.map((p) => (
            <div key={p.name} style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 12, padding: "4px 0" }}>
              <Pill tone={p.ok ? STATUS.pass : STATUS.fail}>{p.ok ? "Holds" : "FAILS"}</Pill>
              <strong style={{ minWidth: 90 }}>{p.name}</strong>
              <span style={{ color: "var(--color-text-secondary)" }}>{p.detail}</span>
            </div>
          ))}
        </>
      )}

      {plan.warnings?.length > 0 && (
        <div style={{ ...card, background: "#FAEEDA", border: "0.5px solid #FAC775", color: "#633806", fontSize: 12, marginTop: 12 }}>
          <strong>Please read before converting</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{plan.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      {(plan.removed_from_top?.length > 0 || plan.taken_out?.length > 0) && (
        <>
          <Heading hint="The cover regenerates these from the Register, so they come out of the file.">Taken out of the document</Heading>
          {plan.removed_from_top.length > 0 && (
            <div style={{ fontSize: 12, marginBottom: 6 }}>
              Lines above the header block: {plan.removed_from_top.map((t, i) => <code key={i} style={{ background: "#F1EFE8", padding: "0 4px", marginRight: 6 }}>{t}</code>)}
            </div>
          )}
          <Rows rows={plan.taken_out} />
        </>
      )}

      {plan.stays_in_document?.length > 0 && (
        <>
          <Heading hint="The cover has no place for these, and OrgOS reads them from the file, so they stay exactly as they are, right after the cover.">
            Stays in the document, unchanged
          </Heading>
          <Rows rows={plan.stays_in_document} />
        </>
      )}

      <Heading hint="What the cover will say. These come from the document's own header block.">The new cover</Heading>
      <Rows rows={plan.cover} />

      {plan.regenerated?.length > 0 && (
        <>
          <Heading hint="Typed into the document by hand, and not carried across: OrgOS sets these when the document is approved.">Not carried across</Heading>
          <Table head={["Fact", "As typed", "Why"]} widths={["150px", "auto", "280px"]}
            rows={plan.regenerated.map((r) => [<strong key={r.label}>{r.label}</strong>, r.typed, r.why])} />
        </>
      )}

      {plan.page_header_footer_replaced?.length > 0 && (
        <>
          <Heading hint="The template's own header and footer replace these. If any of it is wording you need, put it in the body first.">
            Page header and footer text replaced
          </Heading>
          {plan.page_header_footer_replaced.map((t, i) => <div key={i} style={{ fontSize: 12, padding: "2px 0" }}>“{t}”</div>)}
        </>
      )}

      <Heading hint="Every fact the block stated is kept on the document's record, under the label the document used.">Saved to the Register</Heading>
      <details>
        <summary style={{ cursor: "pointer", fontSize: 12, color: "#0C447C" }}>Show all {plan.kept_in_register?.length || 0} facts</summary>
        <div style={{ marginTop: 8 }}><Rows rows={plan.kept_in_register || []} /></div>
      </details>
    </div>
  );
}

function ConvertTab() {
  const qc = useQueryClient();
  const [source, setSource] = useState("lifecycle");
  const [itemId, setItemId] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [plan, setPlan] = useState(null);
  const [done, setDone] = useState(null);
  const input = useRef(null);

  const { data: items = [] } = useQuery({ queryKey: ["doc-standards-lifecycle"], queryFn: api.lifecycle, staleTime: 30_000 });
  const convertible = items.filter((d) => d.Stage === "Review" && d.ApprovalStatus !== "Approved" && d.SharePointFileUrl);
  const ready = source === "lifecycle" ? !!itemId : !!file;

  const reset = () => { setPlan(null); setError(""); setDone(null); };

  const read = async () => {
    setBusy("reading"); reset();
    try { setPlan(await api.preview(source === "lifecycle" ? { itemId } : { file })); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(""); }
  };

  const apply = async () => {
    if (!window.confirm("Convert this document?\n\nThe converted file becomes the Lifecycle item's own working copy. The original file is not changed or deleted.")) return;
    setBusy("applying"); setError("");
    try {
      setDone(await api.apply(itemId));
      qc.invalidateQueries({ queryKey: ["lifecycle"] });
      qc.invalidateQueries({ queryKey: ["doc-standards-lifecycle"] });
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(""); }
  };

  const download = async (kind) => {
    setBusy("downloading"); setError("");
    try { await api.download(file, kind); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(""); }
  };

  return (
    <div>
      <div style={{ ...card, fontSize: 12, lineHeight: 1.6 }}>
        <strong>Convert a document onto the CDT.</strong> OrgOS reads the facts typed into the document's header
        block, replaces the hand-typed parts with the template cover (filled from the Register), and leaves the
        body untouched. It then <em>proves</em> that the body is identical, nothing was lost, and OrgOS reads the
        same code, title, relationships and controls as before. If any proof fails, nothing is offered.
        Nothing happens until you press <strong>Convert</strong>, and the original file is never changed.
      </div>

      <div style={{ display: "flex", gap: 16, margin: "14px 0 8px", fontSize: 12 }}>
        {[["lifecycle", "A document in Document Lifecycle (Review)"], ["upload", "Upload a file to try it"]].map(([k, label]) => (
          <label key={k} style={{ cursor: "pointer" }}>
            <input type="radio" checked={source === k} onChange={() => { setSource(k); reset(); }} /> {label}
          </label>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        {source === "lifecycle" ? (
          <select value={itemId} onChange={(e) => { setItemId(e.target.value); reset(); }}
            style={{ fontSize: 12, padding: "7px 10px", borderRadius: 7, border: "1.5px solid #C0C0C0", minWidth: 380,
                     background: "var(--color-background-primary)", color: "var(--color-text-primary)" }}>
            <option value="">Choose a document in Review…</option>
            {convertible.map((d) => (
              <option key={d.id} value={d.id}>{d.DocumentCode || "(no code)"} — {d.Title}</option>
            ))}
          </select>
        ) : (
          <>
            <input ref={input} type="file" accept=".docx" style={{ display: "none" }}
              onChange={(e) => { setFile(e.target.files[0] || null); reset(); }} />
            <Button kind="secondary" onClick={() => input.current?.click()}>{file ? "Choose another file" : "Choose a .docx file"}</Button>
            {file && <span style={{ fontSize: 12 }}>{file.name}</span>}
          </>
        )}
        <Button onClick={read} disabled={!ready || !!busy}>{busy === "reading" ? "Reading and proving..." : "Read and prove"}</Button>
      </div>
      {source === "lifecycle" && convertible.length === 0 && (
        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 6 }}>
          There are no documents in Review with a file. Documents still to come through intake appear here once they have a Lifecycle entry.
        </div>
      )}

      {error && <div style={{ ...card, background: "#FCEBEB", border: "1px solid #F09595", color: "#791F1F", fontSize: 12, marginTop: 12 }}>{error}</div>}

      {done && (
        <div style={{ ...card, background: STATUS.pass.bg, border: `1px solid ${STATUS.pass.bd}`, color: STATUS.pass.tx, marginTop: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Converted</div>
          <div style={{ fontSize: 12, marginTop: 4, lineHeight: 1.6 }}>
            The Lifecycle item now has its own working copy with the CDT cover, named as its title. The original
            file is unchanged. The cover facts are saved on the item and the CDI checks were re-run:{" "}
            <strong>{done.item?.CDIStatus || "pending"}</strong>.
          </div>
        </div>
      )}

      {plan && !done && (
        <div style={{ marginTop: 14 }}>
          <PlanView plan={plan} />
          {plan.ok && (
            <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap", alignItems: "center" }}>
              {source === "lifecycle" ? (
                <Button onClick={apply} disabled={!!busy}>{busy === "applying" ? "Converting..." : "Convert this document"}</Button>
              ) : (
                <>
                  <Button onClick={() => download("reading")} disabled={!!busy}>Download reading copy</Button>
                  <Button kind="secondary" onClick={() => download("source")} disabled={!!busy}>Download CDT source</Button>
                  <span style={{ fontSize: 11, color: "var(--color-text-secondary)", maxWidth: 420 }}>
                    The reading copy is filled in, to read and check. The CDT source keeps the cover placeholders,
                    which is the form OrgOS stores. Upload a file here only to try the conversion; to convert a
                    real document, choose it from Document Lifecycle.
                  </span>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── the page ────────────────────────────────────────────────────────────────

export default function DocumentStandards() {
  const { isCompliance } = useCurrentUserRole();
  const [tab, setTab] = useState("standard");
  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Document standards</div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          The standard every controlled document must meet, a way to check a document against it, and the
          conversion of existing documents onto the controlled template.
        </div>
      </div>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--color-border-tertiary, #E0E0E0)", marginBottom: 16 }}>
        <Tab active={tab === "standard"} onClick={() => setTab("standard")}>The standard</Tab>
        <Tab active={tab === "check"} onClick={() => setTab("check")}>Check a document</Tab>
        {isCompliance && <Tab active={tab === "convert"} onClick={() => setTab("convert")}>Convert to CDT</Tab>}
      </div>
      {tab === "standard" && <StandardTab />}
      {tab === "check" && <CheckTab />}
      {tab === "convert" && isCompliance && <ConvertTab />}
    </>
  );
}
