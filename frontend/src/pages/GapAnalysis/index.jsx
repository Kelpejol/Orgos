// =============================================================================
// pages/GapAnalysis/index.jsx
// Gap Analysis — wired to SharePoint.
// Shows compliance gaps identified by the Gap Analyzer agent or manual entry.
// Each gap has a full remediation package (Bobby's amendment) for human review.
// Decisions: Accept & remediate, Accept risk (→ Strategic Risk Register), Reassign
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

const gapApi = {
  list:   (params = {}) =>
    apiClient.get("/api/v1/gap-analysis", { params }).then(r => r.data),

  updateStatus: (id, body) =>
    apiClient.patch(`/api/v1/gap-analysis/${id}/status`, body).then(r => r.data),

  acceptRisk: (id, rationale) =>
    apiClient.post(`/api/v1/gap-analysis/${id}/accept-risk`, { rationale })
      .then(r => r.data),
};

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

// =============================================================================
//  Severity config
// =============================================================================

const SEV = {
  Critical: { color: "#791F1F", bg: "#FCEBEB", bd: "#F09595",
              desc: "Certification is at risk — auditor will write a major nonconformity" },
  Major:    { color: "#7A4A00", bg: "#FDF0E0", bd: "#F0B860",
              desc: "Significant weakness — likely generates an audit observation" },
  Minor:    { color: "#0C447C", bg: "#E6F1FB", bd: "#85B7EB",
              desc: "Data quality or completeness issue — unlikely to affect certification" },
};

const CAT_LABELS = {
  "Missing artefact":    "No document governs this area",
  "Control gap":         "Document exists but controls are inadequate",
  "Evidence gap":        "Controls exist but evidence is not being collected",
  "Ownership gap":       "Controls exist but the responsible role is unassigned",
  "Standards misalignment": "Controls exist but mapped to incorrect clauses",
  "Obligation gap":      "Regulatory requirement not tracked in Compliance Calendar",
};

// =============================================================================
//  Remediation package viewer (Bobby's amendment — Gap Analyzer outputs full package)
// =============================================================================

const RemediationPackage = ({ packageJson, onAccept, onClose, isPending }) => {
  const [rationale, setRationale] = useState("");
  let pkg = null;
  try { pkg = packageJson ? JSON.parse(packageJson) : null; } catch { pkg = null; }

  if (!pkg) return (
    <div style={{ padding: "10px 12px", background: "var(--color-background-secondary)",
                  borderRadius: 8, fontSize: 12, color: "var(--color-text-tertiary)" }}>
      No remediation package generated yet. The Gap Analyzer agent will propose one when it runs.
    </div>
  );

  return (
    <div style={{ padding: "14px 16px", background: "#E1F5EE", borderRadius: 10,
                  border: "1px solid #5DCAA5", marginTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: "#085041", marginBottom: 12 }}>
        Proposed remediation package
      </div>

      {pkg.document && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "#085041",
                        textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 4 }}>
            Document action
          </div>
          <div style={{ fontSize: 12, color: "#085041", lineHeight: 1.5 }}>{pkg.document}</div>
        </div>
      )}

      {pkg.controls?.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "#085041",
                        textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 4 }}>
            Proposed controls
          </div>
          {pkg.controls.map((c, i) => (
            <div key={i} style={{ fontSize: 12, color: "#085041", marginBottom: 4,
                                  padding: "5px 8px", background: "#C8ECD8",
                                  borderRadius: 6, lineHeight: 1.4 }}>
              {c}
            </div>
          ))}
        </div>
      )}

      {pkg.evidence?.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "#085041",
                        textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 4 }}>
            Evidence requirements
          </div>
          {pkg.evidence.map((e, i) => (
            <div key={i} style={{ fontSize: 12, color: "#085041", marginBottom: 4,
                                  padding: "5px 8px", background: "#C8ECD8",
                                  borderRadius: 6 }}>
              {e}
            </div>
          ))}
        </div>
      )}

      {pkg.risk && (
        <div style={{ marginBottom: 10, padding: "7px 10px", background: "#FCEBEB",
                      borderRadius: 6, fontSize: 11, color: "#791F1F" }}>
          Risk if gap stays open: {pkg.risk}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
        {pkg.target_date  && <Field l="Target date"  v={pkg.target_date} />}
        {pkg.verification && <Field l="Verification" v={pkg.verification} />}
        {pkg.standards_mapping && <Field l="Closes clauses" v={pkg.standards_mapping} />}
      </div>

      <textarea
        value={rationale}
        onChange={e => setRationale(e.target.value)}
        placeholder="Reviewer notes (optional) — any edits to the package before accepting..."
        rows={2}
        style={{ width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 8,
                 border: "1.5px solid #5DCAA5", background: "var(--color-background-primary)",
                 color: "var(--color-text-primary)", resize: "vertical",
                 fontFamily: "var(--font-sans)", outline: "none",
                 boxSizing: "border-box", marginBottom: 10 }}
      />

      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={() => onAccept(rationale)} disabled={isPending}
          style={{ flex: 1, padding: "9px", fontSize: 12, borderRadius: 8,
                   border: "none", fontWeight: 600,
                   background: isPending ? "#E8E8E8" : "#085041",
                   color: isPending ? "#999" : "#fff",
                   cursor: isPending ? "not-allowed" : "pointer" }}>
          {isPending ? "Creating lifecycle entry..." : "Approve package → enter Document Lifecycle"}
        </button>
        <button onClick={onClose}
          style={{ padding: "9px 14px", fontSize: 12, borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "transparent",
                   color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Close
        </button>
      </div>
    </div>
  );
};

// =============================================================================
//  Accept risk panel
// =============================================================================

const AcceptRiskPanel = ({ onAccept, onClose, isPending }) => {
  const [rationale, setRationale] = useState("");
  const ratOk = rationale.trim().length >= 20;

  return (
    <div style={{ padding: "14px 16px", background: "#FAEEDA", borderRadius: 10,
                  border: "1px solid #FAC775", marginTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#633806", marginBottom: 6 }}>
        Accept risk — ExCo rationale required
      </div>
      <div style={{ fontSize: 11, color: "#633806", marginBottom: 10, lineHeight: 1.5 }}>
        This gap will be marked as accepted risk and a Strategic Risk Register entry will be created.
        The affected clause on the Standards Map will remain Red with a note: "Risk accepted by ExCo."
        This is visible to auditors.
      </div>
      <textarea
        value={rationale}
        onChange={e => setRationale(e.target.value)}
        placeholder="ExCo rationale — why is this risk being accepted rather than remediated? Minimum 20 characters. This appears on the audit record."
        rows={3}
        style={{ width: "100%", fontSize: 12, padding: "8px 10px", borderRadius: 8,
                 border: `1.5px solid ${ratOk ? "#FAC775" : "#C0C0C0"}`,
                 background: "var(--color-background-primary)",
                 color: "var(--color-text-primary)", resize: "vertical",
                 fontFamily: "var(--font-sans)", outline: "none",
                 boxSizing: "border-box", marginBottom: 10 }}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={() => onAccept(rationale)} disabled={!ratOk || isPending}
          style={{ flex: 1, padding: "9px", fontSize: 12, borderRadius: 8,
                   border: "none", fontWeight: 600,
                   background: !ratOk || isPending ? "#E8E8E8" : "#BA7517",
                   color: !ratOk || isPending ? "#999" : "#fff",
                   cursor: !ratOk || isPending ? "not-allowed" : "pointer" }}>
          {isPending ? "Processing..." : "Confirm — accept this risk"}
        </button>
        <button onClick={onClose}
          style={{ padding: "9px 14px", fontSize: 12, borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "transparent",
                   color: "var(--color-text-secondary)", cursor: "pointer" }}>
          Cancel
        </button>
      </div>
    </div>
  );
};

// =============================================================================
//  Gap card
// =============================================================================

const GapCard = ({ gap, isCompliance, onStatusUpdate, onAcceptRisk, actionId }) => {
  const [expanded,        setExpanded]        = useState(false);
  const [showRemediation, setShowRemediation] = useState(false);
  const [showAcceptRisk,  setShowAcceptRisk]  = useState(false);
  const isPending = actionId === gap.id;

  const sev      = SEV[gap.Severity] || SEV.Minor;
  const isOpen   = gap.Status === "Open" || gap.Status === "In progress";
  const isClosed = gap.Status === "Closed" || gap.Status === "Accepted risk";

  return (
    <div style={{
      border: `1px solid ${sev.bd}`,
      borderLeft: `4px solid ${sev.color}`,
      borderRadius: 12,
      background: isClosed ? "var(--color-background-secondary)" : "var(--color-background-primary)",
      opacity: isClosed ? 0.7 : 1,
      transition: "box-shadow 0.15s",
    }}
      onMouseEnter={e => !isClosed && (e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)")}
      onMouseLeave={e => (e.currentTarget.style.boxShadow = "none")}
    >
      {/* Header */}
      <div
        role="button" tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={e => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "12px 14px", cursor: "pointer" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 6, flexWrap: "wrap", gap: 4 }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 3,
                           fontWeight: 700, background: sev.bg, color: sev.color,
                           border: `0.5px solid ${sev.bd}`,
                           textTransform: "uppercase", letterSpacing: "0.5px" }}>
              {gap.Severity}
            </span>
            {gap.Standard && (
              <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3,
                             background: "var(--color-background-secondary)",
                             color: "var(--color-text-tertiary)", fontWeight: 600 }}>
                {gap.Standard}
              </span>
            )}
            {gap.Clause && (
              <span style={{ fontSize: 10, fontFamily: "var(--font-mono)",
                             color: "var(--color-text-secondary)", fontWeight: 600 }}>
                {gap.Clause}
              </span>
            )}
            <StatusBadge label={gap.Status} />
            {gap.ProposedRemediation && (
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3,
                             background: "#E1F5EE", color: "#085041",
                             border: "0.5px solid #5DCAA5", fontWeight: 600 }}>
                PACKAGE READY
              </span>
            )}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 4 }}>
          {gap.Finding}
        </div>

        {gap.Impact && (
          <div style={{ fontSize: 11, color: sev.color, lineHeight: 1.4, marginBottom: 4 }}>
            {gap.Impact}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between",
                      fontSize: 10, color: "var(--color-text-tertiary)" }}>
          <span>{gap.GapCategory && CAT_LABELS[gap.GapCategory] || gap.GapCategory}</span>
          <span>{gap.TargetDate ? `Target: ${gap.TargetDate.split("T")[0]}` : ""}</span>
        </div>
      </div>

      {/* Expanded */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${sev.bd}`, padding: "12px 14px" }}>

          {/* Severity explanation */}
          <div style={{ padding: "8px 10px", background: sev.bg, borderRadius: 7,
                        fontSize: 11, color: sev.color, marginBottom: 12,
                        border: `0.5px solid ${sev.bd}` }}>
            {sev.desc}
          </div>

          {/* Fields */}
          <Field l="Standard"    v={`${gap.Standard} ${gap.Clause}`} />
          <Field l="Category"    v={gap.GapCategory} />
          {gap.AssignedTo && <Field l="Assigned to"  v={gap.AssignedTo} />}
          {gap.TargetDate && <Field l="Target date"  v={gap.TargetDate.split("T")[0]} />}
          {gap.VerificationMethod && (
            <Field l="Verification"  v={gap.VerificationMethod} />
          )}
          {gap.RemediationHint && (
            <div style={{ padding: "7px 10px", background: "var(--color-background-secondary)",
                          borderRadius: 6, fontSize: 11, color: "var(--color-text-secondary)",
                          marginTop: 6 }}>
              Hint: {gap.RemediationHint}
            </div>
          )}
          {gap.LinkedRiskId && (
            <Field l="Linked risk" v={gap.LinkedRiskId} color="#BA7517" />
          )}
          {gap.ResolutionNotes && (
            <Field l="Resolution notes" v={gap.ResolutionNotes} />
          )}

          {/* Action buttons — compliance only, open gaps only */}
          {isCompliance && isOpen && (
            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              <button
                onClick={() => { setShowRemediation(!showRemediation); setShowAcceptRisk(false); }}
                style={{ padding: "8px 14px", fontSize: 12, borderRadius: 8,
                         border: "none", background: "#085041", color: "#fff",
                         cursor: "pointer", fontWeight: 500 }}>
                {showRemediation ? "Hide package" : "View remediation package"}
              </button>
              <button
                onClick={() => onStatusUpdate(gap.id, "In progress")}
                disabled={gap.Status === "In progress" || isPending}
                style={{ padding: "8px 14px", fontSize: 12, borderRadius: 8,
                         border: "1.5px solid #C0C0C0", background: "transparent",
                         color: "var(--color-text-secondary)",
                         cursor: gap.Status === "In progress" || isPending
                           ? "not-allowed" : "pointer" }}>
                Mark in progress
              </button>
              <button
                onClick={() => { setShowAcceptRisk(!showAcceptRisk); setShowRemediation(false); }}
                style={{ padding: "8px 14px", fontSize: 12, borderRadius: 8,
                         border: "1.5px solid #FAC775", background: "transparent",
                         color: "#BA7517", cursor: "pointer" }}>
                Accept risk
              </button>
              {gap.Status === "In progress" && (
                <button
                  onClick={() => onStatusUpdate(gap.id, "Closed")}
                  disabled={isPending}
                  style={{ padding: "8px 14px", fontSize: 12, borderRadius: 8,
                           border: "none", background: "#0C447C", color: "#fff",
                           cursor: "pointer", fontWeight: 500 }}>
                  Close — gap resolved
                </button>
              )}
            </div>
          )}

          {/* Remediation package */}
          {showRemediation && (
            <RemediationPackage
              packageJson={gap.ProposedRemediation}
              onAccept={async (notes) => {
                await onStatusUpdate(gap.id, "In progress",
                  notes ? `Remediation package approved. Notes: ${notes}` : "Remediation package approved."
                );
                setShowRemediation(false);
              }}
              onClose={() => setShowRemediation(false)}
              isPending={isPending}
            />
          )}

          {/* Accept risk panel */}
          {showAcceptRisk && (
            <AcceptRiskPanel
              onAccept={async (rationale) => {
                await onAcceptRisk(gap.id, rationale);
                setShowAcceptRisk(false);
              }}
              onClose={() => setShowAcceptRisk(false)}
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

export default function GapAnalysis() {
  const [severityFilter, setSeverityFilter] = useState("All");
  const [statusFilter,   setStatusFilter]   = useState("open");
  const [standardFilter, setStandardFilter] = useState("All");
  const [search,         setSearch]         = useState("");
  const [actionId,       setActionId]       = useState(null);

  const { isCompliance } = useCurrentUser();
  const qc = useQueryClient();

  const { data: gaps = [], isLoading, error, refetch } = useQuery({
    queryKey: ["gaps"],
    queryFn:  () => gapApi.list(),
    staleTime: 60_000,
  });

  const filtered = useMemo(() => {
    let list = gaps;
    if (severityFilter !== "All") list = list.filter(g => g.Severity === severityFilter);
    if (statusFilter === "open")  list = list.filter(g => ["Open", "In progress"].includes(g.Status));
    if (statusFilter === "closed") list = list.filter(g => ["Closed", "Accepted risk"].includes(g.Status));
    if (standardFilter !== "All") list = list.filter(g => g.Standard === standardFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(g =>
        (g.Finding   || "").toLowerCase().includes(q) ||
        (g.Clause    || "").toLowerCase().includes(q) ||
        (g.Impact    || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [gaps, severityFilter, statusFilter, standardFilter, search]);

  const counts = useMemo(() => ({
    critical: gaps.filter(g => g.Severity === "Critical" && g.Status === "Open").length,
    major:    gaps.filter(g => g.Severity === "Major"    && g.Status === "Open").length,
    minor:    gaps.filter(g => g.Severity === "Minor"    && g.Status === "Open").length,
    open:     gaps.filter(g => ["Open", "In progress"].includes(g.Status)).length,
  }), [gaps]);

  const handleStatusUpdate = async (id, newStatus, notes) => {
    setActionId(id);
    try {
      await gapApi.updateStatus(id, {
        status: newStatus,
        ...(notes ? { resolution_notes: notes } : {}),
      });
      qc.invalidateQueries({ queryKey: ["gaps"] });
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Update failed.");
    } finally {
      setActionId(null);
    }
  };

  const handleAcceptRisk = async (id, rationale) => {
    setActionId(id);
    try {
      await gapApi.acceptRisk(id, rationale);
      qc.invalidateQueries({ queryKey: ["gaps"] });
      qc.invalidateQueries({ queryKey: ["risks"] });
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Accept risk failed.");
    } finally {
      setActionId(null);
    }
  };

  if (isLoading) return <LoadingState message="Loading gap analysis..." />;
  if (error)     return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>Gap analysis</div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Compliance gaps identified from confirmed register data.
              Each gap has a severity, a finding, and a proposed remediation package.
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {counts.critical > 0 && (
              <div style={{ padding: "3px 10px", borderRadius: 6, fontSize: 11,
                            fontWeight: 700, background: "#FCEBEB", color: "#791F1F",
                            border: "0.5px solid #F09595" }}>
                {counts.critical} Critical
              </div>
            )}
            {counts.major > 0 && (
              <div style={{ padding: "3px 10px", borderRadius: 6, fontSize: 11,
                            fontWeight: 600, background: "#FDF0E0", color: "#7A4A00",
                            border: "0.5px solid #F0B860" }}>
                {counts.major} Major
              </div>
            )}
            <div style={{ padding: "3px 10px", borderRadius: 6, fontSize: 11,
                          fontWeight: 500, background: "#E6F1FB", color: "#0C447C",
                          border: "0.5px solid #85B7EB" }}>
              {counts.open} open
            </div>
          </div>
        </div>
        {!isCompliance && (
          <div style={{ marginTop: 8, padding: "8px 12px", background: "#FAEEDA",
                        borderRadius: 8, fontSize: 12, color: "#633806",
                        border: "0.5px solid #FAC775" }}>
            View only — Compliance Lead role required to take action on gaps.
          </div>
        )}
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {/* Status */}
        {[
          { k: "open",   l: `Open (${counts.open})` },
          { k: "closed", l: "Closed / Accepted" },
          { k: "all",    l: `All (${gaps.length})` },
        ].map(f => (
          <button key={f.k} onClick={() => setStatusFilter(f.k)}
            style={{ padding: "5px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                     fontWeight: statusFilter === f.k ? 600 : 400,
                     border: statusFilter === f.k ? "1px solid var(--color-border-info)" : "1.5px solid #C0C0C0",
                     background: statusFilter === f.k ? "var(--color-background-info)" : "var(--color-background-primary)",
                     color: statusFilter === f.k ? "var(--color-text-info)" : "var(--color-text-secondary)" }}>
            {f.l}
          </button>
        ))}

        <div style={{ width: 1, background: "#D0D0D0", alignSelf: "stretch" }} />

        {/* Severity */}
        {["All", "Critical", "Major", "Minor"].map(s => {
          const sv = SEV[s];
          const active = severityFilter === s;
          return (
            <button key={s} onClick={() => setSeverityFilter(s)}
              style={{ padding: "5px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                       fontWeight: active ? 600 : 400,
                       border: active && sv ? `1.5px solid ${sv.bd}` : "1.5px solid #C0C0C0",
                       background: active && sv ? sv.bg : "var(--color-background-primary)",
                       color: active && sv ? sv.color : "var(--color-text-secondary)" }}>
              {s}
            </button>
          );
        })}

        <div style={{ width: 1, background: "#D0D0D0", alignSelf: "stretch" }} />

        {/* Standard */}
        {["All", "ISO 27001", "ISO 9001", "NDPA"].map(s => (
          <button key={s} onClick={() => setStandardFilter(s)}
            style={{ padding: "5px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                     fontWeight: standardFilter === s ? 600 : 400,
                     border: standardFilter === s ? "1px solid var(--color-border-info)" : "1.5px solid #C0C0C0",
                     background: standardFilter === s ? "var(--color-background-info)" : "var(--color-background-primary)",
                     color: standardFilter === s ? "var(--color-text-info)" : "var(--color-text-secondary)" }}>
            {s}
          </button>
        ))}

        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search findings..."
          style={{ flex: 1, minWidth: 160, fontSize: 12, padding: "6px 12px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {/* Gaps */}
      {filtered.length === 0 ? (
        <EmptyState message={
          gaps.length === 0
            ? "No gap findings yet. The Gap Analyzer agent reads confirmed register data and identifies gaps clause by clause. It will run after the Control Register and Evidence Tracker are sufficiently populated."
            : "No gaps match your filter."
        } />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map(gap => (
            <GapCard
              key={gap.id}
              gap={gap}
              isCompliance={isCompliance}
              onStatusUpdate={handleStatusUpdate}
              onAcceptRisk={handleAcceptRisk}
              actionId={actionId}
            />
          ))}
        </div>
      )}

      {filtered.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 8 }}>
          {filtered.length} of {gaps.length} findings
        </div>
      )}
    </>
  );
}