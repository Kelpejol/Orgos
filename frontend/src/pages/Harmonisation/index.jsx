// =============================================================================
// pages/Harmonisation/index.jsx
// Zone 3 — Harmonisation
// Handles two item subtypes:
//   Role variants: same role referenced with different names across documents
//   Control duplicates: near-identical controls found in multiple documents
// Per DRG-QI-REF-DINT-01-26 Section 3.3
// Decisions: Merge, Partial merge, Keep separate, Rename/Standardise
// =============================================================================

import { useState, useMemo } from "react";
import { useMsal } from "@azure/msal-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { Field } from "../../components/shared/Forms.jsx";
import { LoadingState, ErrorState, EmptyState } from "../../components/shared/LoadingState.jsx";
import apiClient from "../../api/grcApi.js";

// =============================================================================
//  Run Classifier button
// =============================================================================

const RunClassifierButton = ({ onComplete }) => {
  const [running,  setRunning]  = useState(false);
  const [result,   setResult]   = useState(null);
  const [error,    setError]    = useState("");

  const handleRun = async () => {
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const resp = await apiClient.post("/api/v1/agents/classify");
      setResult(resp.data);
      onComplete?.();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Classifier failed.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
      <button
        onClick={handleRun}
        disabled={running}
        style={{ padding: "6px 12px", fontSize: 11, borderRadius: 7,
                 border: "none", fontWeight: 500,
                 background: running ? "#E8E8E8" : "#3C3489",
                 color: running ? "#999" : "#fff",
                 cursor: running ? "not-allowed" : "pointer" }}
      >
        {running ? "Running classifier..." : "Run classifier"}
      </button>
      {result && (
        <div style={{ fontSize: 10, color: "#3C3489", textAlign: "right" }}>
          {result.role_variants_written} role variants · {result.duplicates_written} duplicates written
        </div>
      )}
      {error && (
        <div style={{ fontSize: 10, color: "#A32D2D" }}>{error}</div>
      )}
    </div>
  );
};

// =============================================================================
//  API
// =============================================================================

const zone3Api = {
  list: () =>
    apiClient.get("/api/v1/queue/items", { params: { item_type: "Harmonisation" } })
      .then(r => r.data),

  decide: (itemId, decision, rationale, canonicalName) =>
    apiClient.patch(`/api/v1/queue/items/${itemId}/zone3-decide`, {
      decision,
      rationale,
      ...(canonicalName ? { canonical_name: canonicalName } : {}),
    }).then(r => r.data),
};

function useUserRoles() {
  const { accounts } = useMsal();
  const roles = accounts[0]?.idTokenClaims?.roles || [];
  return {
    isCompliance: roles.includes("Compliance.Lead") || roles.includes("OrgOS.Admin"),
  };
}

// =============================================================================
//  Harmonisation decision panel
// =============================================================================

const HarmDecisionPanel = ({ item, onDecide, isPending }) => {
  const [rationale,     setRationale]     = useState("");
  const [canonicalName, setCanonicalName] = useState(item.CanonicalName || "");
  const [active, setActive] = useState(null);

  const ratOk = rationale.trim().length >= 10;

  const DECISIONS = [
    { key: "Merge",       label: "Merge",              primary: true,
      desc: "Confirm canonical name and merge all variants to it" },
    { key: "Partial merge", label: "Partial merge",    primary: false,
      desc: "Some variants are the same, others are genuinely different" },
    { key: "Keep separate", label: "Keep separate",    primary: false,
      desc: "These are genuinely different — not variants of each other" },
    { key: "Rename and standardise", label: "Rename / Standardise", primary: false,
      desc: "Standardise the name across all documents without merging" },
  ];

  const handle = async (key) => {
    if (!ratOk) return;
    setActive(key);
    await onDecide(item.id, key, rationale.trim(), canonicalName.trim() || undefined);
    setActive(null);
  };

  return (
    <div style={{ marginTop: 12 }}>
      {/* Canonical name input */}
      <div style={{ marginBottom: 10 }}>
        <label style={{ display: "block", fontSize: 10, fontWeight: 600,
                        color: "var(--color-text-secondary)", marginBottom: 4,
                        textTransform: "uppercase", letterSpacing: "0.5px" }}>
          Canonical name (the one true name going forward)
        </label>
        <input
          type="text"
          value={canonicalName}
          onChange={e => setCanonicalName(e.target.value)}
          placeholder="e.g. Department Head"
          style={{
            width: "100%", fontSize: 13, padding: "9px 12px", borderRadius: 8,
            border: `1.5px solid ${canonicalName.trim() ? "#5DCAA5" : "#C0C0C0"}`,
            background: "var(--color-background-primary)",
            color: "var(--color-text-primary)", outline: "none",
            boxSizing: "border-box", fontWeight: 500,
          }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = canonicalName.trim() ? "#5DCAA5" : "#C0C0C0")}
        />
        <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 3 }}>
          All variant terms will be mapped to this name in the Role Register and Control Register.
        </div>
      </div>

      {/* Rationale */}
      <textarea
        value={rationale}
        onChange={e => setRationale(e.target.value)}
        placeholder="Decision rationale — required (min 10 characters)."
        rows={2}
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

      {/* Decisions — 2 column grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {DECISIONS.map(d => (
          <button
            key={d.key}
            onClick={() => handle(d.key)}
            disabled={!ratOk || isPending}
            title={d.desc}
            style={{
              padding: "10px 12px", fontSize: 12, borderRadius: 8,
              border: d.primary ? "none" : "1.5px solid #C0C0C0",
              background: !ratOk || isPending ? "#E8E8E8"
                : d.primary ? "#3C3489" : "var(--color-background-primary)",
              color: !ratOk || isPending ? "#999"
                : d.primary ? "#fff" : "var(--color-text-primary)",
              cursor: !ratOk || isPending ? "not-allowed" : "pointer",
              fontWeight: d.primary ? 600 : 400,
              textAlign: "left",
            }}
          >
            {active === d.key ? "Processing..." : d.label}
          </button>
        ))}
      </div>
    </div>
  );
};

// =============================================================================
//  Harmonisation card
// =============================================================================

const HarmCard = ({ item, isCompliance, onDecide, isPending }) => {
  const [expanded, setExpanded] = useState(false);
  const isDecided = item.ReviewStatus && item.ReviewStatus !== "Pending Review";

  // Parse variant terms if available
  let variants = [];
  if (item.VariantTerms) {
    try {
      variants = JSON.parse(item.VariantTerms);
    } catch {
      variants = item.VariantTerms.split(",").map(v => v.trim()).filter(Boolean);
    }
  }

  const primaryText = item.Title || item.ControlStatement || item.ResponsibilityStatement || "Untitled";
  const isRole      = !item.ControlStatement;

  return (
    <div style={{
      border: `1px solid #AFA9EC`,
      borderLeft: `4px solid #3C3489`,
      borderRadius: 12,
      background: isDecided ? "var(--color-background-secondary)" : "var(--color-background-primary)",
      opacity: isDecided ? 0.65 : 1,
      transition: "box-shadow 0.15s",
    }}
      onMouseEnter={e => !isDecided && (e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)")}
      onMouseLeave={e => (e.currentTarget.style.boxShadow = "none")}
    >
      <div
        role="button" tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={e => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "12px 14px", cursor: "pointer" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginBottom: 6, flexWrap: "wrap", gap: 4 }}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 3,
                           fontWeight: 600, background: "#EEEDFE", color: "#3C3489",
                           border: "0.5px solid #AFA9EC" }}>
              {isRole ? "Role variant" : "Control duplicate"}
            </span>
            {item.VariantFrequency && (
              <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3,
                             background: "var(--color-background-secondary)",
                             color: "var(--color-text-tertiary)",
                             border: "0.5px solid var(--color-border-tertiary)" }}>
                {item.VariantFrequency}
              </span>
            )}
            {isDecided && <StatusBadge label={item.ReviewStatus} />}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>

        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4, marginBottom: 6 }}>
          {primaryText}
        </div>

        {/* Show variant terms inline */}
        {variants.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {variants.map((v, i) => (
              <span key={i} style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3,
                                     background: "#EEEDFE", color: "#3C3489",
                                     border: "0.5px solid #AFA9EC" }}>
                {v}
              </span>
            ))}
          </div>
        )}

        <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 4 }}>
          {item.SourceDocumentCode}
        </div>
      </div>

      {expanded && (
        <div style={{ borderTop: "1px solid #AFA9EC", padding: "12px 14px" }}>

          {/* Pattern view */}
          <div style={{ padding: "10px 12px", background: "#EEEDFE", borderRadius: 8,
                        marginBottom: 12, border: "0.5px solid #AFA9EC" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#3C3489", marginBottom: 4 }}>
              {isRole
                ? "These terms all refer to what may be the same role"
                : "These controls may be near-duplicates from different documents"}
            </div>
            <div style={{ fontSize: 11, color: "#3C3489", opacity: 0.85, lineHeight: 1.5 }}>
              {isRole
                ? "Confirm which is the canonical name. All other terms will be recorded as variants. Future extractions using variant terms will automatically resolve to the canonical name without creating new orphans."
                : "Confirm whether these should be merged into one master control record, or kept separate as genuinely distinct requirements."}
            </div>
          </div>

          {/* Details */}
          {item.CanonicalName && <Field l="Proposed canonical" v={item.CanonicalName} />}
          {item.VariantTerms  && <Field l="Variant terms"     v={variants.join(", ")} />}
          {item.VariantFrequency && <Field l="Frequency" v={item.VariantFrequency} />}

          {/* Already decided */}
          {isDecided ? (
            <div style={{ marginTop: 10, padding: "10px 12px", background: "#E1F5EE",
                          borderRadius: 8, border: "1px solid #5DCAA5" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#085041" }}>
                {item.ReviewStatus} — {item.Decision}
              </div>
              {item.DecisionRationale && (
                <div style={{ fontSize: 11, color: "#085041", fontStyle: "italic", marginTop: 3 }}>
                  "{item.DecisionRationale}"
                </div>
              )}
            </div>
          ) : isCompliance ? (
            <HarmDecisionPanel item={item} onDecide={onDecide} isPending={isPending} />
          ) : (
            <div style={{ marginTop: 10, padding: "8px 12px",
                          background: "var(--color-background-secondary)",
                          borderRadius: 8, fontSize: 11, color: "var(--color-text-tertiary)",
                          border: "1px dashed var(--color-border-tertiary)" }}>
              Compliance Lead role required to make decisions.
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// =============================================================================
//  Main component
// =============================================================================

export default function Harmonisation() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("pending");
  const [actionState, setActionState] = useState({ pending: false, itemId: null });

  const { isCompliance } = useUserRoles();
  const qc = useQueryClient();
  const { data: items = [], isLoading, error, refetch } = useQuery({
    queryKey: ["zone3"],
    queryFn:  zone3Api.list,
    staleTime: 30_000,
  });

  const pendingCount = items.filter(
    i => !i.ReviewStatus || i.ReviewStatus === "Pending Review"
  ).length;

  const filtered = useMemo(() => {
    let list = filter === "pending"
      ? items.filter(i => !i.ReviewStatus || i.ReviewStatus === "Pending Review")
      : items;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(i =>
        (i.Title || "").toLowerCase().includes(q) ||
        (i.VariantTerms || "").toLowerCase().includes(q) ||
        (i.CanonicalName || "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [items, search, filter]);

  const handleDecide = async (itemId, decision, rationale, canonicalName) => {
    setActionState({ pending: true, itemId });
    try {
      const result = await zone3Api.decide(itemId, decision, rationale, canonicalName);
      qc.invalidateQueries({ queryKey: ["zone3"] });
      return result;
    } catch (err) {
      alert(err.response?.data?.detail || err.message || "Decision failed.");
    } finally {
      setActionState({ pending: false, itemId: null });
    }
  };

  if (isLoading) return <LoadingState message="Loading harmonisation items..." />;
  if (error)     return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
              Harmonisation
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              Zone 3 — Variant role terms and near-duplicate controls across documents.
              Confirm the canonical name. All variants map to it going forward.
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
            <div style={{ padding: "3px 10px", background: "#EEEDFE", borderRadius: 6,
                          fontSize: 11, color: "#3C3489", fontWeight: 600,
                          border: "0.5px solid #AFA9EC", flexShrink: 0 }}>
              {pendingCount} pending
            </div>
            {isCompliance && (
              <RunClassifierButton onComplete={() => qc.invalidateQueries({ queryKey: ["zone3"] })} />
            )}
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

      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {[
          { k: "pending", l: `Pending (${pendingCount})` },
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
          placeholder="Search by term or canonical name..."
          style={{ flex: 1, minWidth: 180, fontSize: 12, padding: "6px 12px", borderRadius: 8,
                   border: "1.5px solid #C0C0C0", background: "var(--color-background-primary)",
                   color: "var(--color-text-primary)", outline: "none" }}
          onFocus={e => (e.target.style.borderColor = "#378ADD")}
          onBlur={e => (e.target.style.borderColor = "#C0C0C0")}
        />
      </div>

      {filtered.length === 0 ? (
        <EmptyState message={
          items.length === 0
            ? "No Zone 3 items yet. Harmonisation items are created by the Classifier agent after it compares extracted role terms against the Role Register and detects near-duplicate controls across documents. The Classifier is built in Phase 11 of the implementation plan."
            : "No items match your search."
        } />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map(item => (
            <HarmCard
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