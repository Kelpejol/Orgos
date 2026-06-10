// =============================================================================
// pages/Extractor/index.jsx
// Document Extractor — SharePoint browser is the primary interface.
// Upload from device is a secondary fallback option.
// Supports recursive folder navigation, EML evidence linking,
// pagination via Load more, and 10 minute React Query cache.
// NEW SCREEN — requires CCO sign-off. DRG-AUTO-BRIEF-GRC-01-26
// =============================================================================

import { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import StatusBadge from "../../components/shared/StatusBadge.jsx";
import { extractorApi, sharePointApi } from "../../api/grcApi.js";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";

// ── Primitives ────────────────────────────────────────────────────────────────

const Field = ({ l, v }) => (
  <div
    style={{
      display: "flex",
      justifyContent: "space-between",
      padding: "5px 0",
      borderBottom: "0.5px solid var(--color-border-tertiary)",
      fontSize: 12,
      gap: 12,
    }}
  >
    <span style={{ color: "var(--color-text-secondary)", flexShrink: 0 }}>
      {l}
    </span>
    <span
      style={{
        color: "var(--color-text-primary)",
        textAlign: "right",
        wordBreak: "break-word",
      }}
    >
      {v ?? "—"}
    </span>
  </div>
);

const ConfidenceBar = ({ score }) => {
  const pct = Math.round(score * 100);
  const color = pct >= 90 ? "#1D9E75" : pct >= 75 ? "#BA7517" : "#A32D2D";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          flex: 1,
          height: 6,
          borderRadius: 3,
          background: "var(--color-border-tertiary)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: color,
            borderRadius: 3,
          }}
        />
      </div>
      <span style={{ fontSize: 11, fontWeight: 600, color, minWidth: 32 }}>
        {pct}%
      </span>
    </div>
  );
};

const FileIcon = ({ ext, type }) => {
  const map = {
    folder: ["▣", "#BA7517"],
    pdf: ["⬡", "#A32D2D"],
    docx: ["◇", "#378ADD"],
    txt: ["◎", "#595959"],
    eml: ["◉", "#7C3AED"],
  };
  const [icon, color] = map[type === "folder" ? "folder" : ext] || [
    "○",
    "#999",
  ];
  return <span style={{ fontSize: 14, color, flexShrink: 0 }}>{icon}</span>;
};

const ActionBadge = ({ action }) => {
  const map = {
    extract: {
      bg: "#E1F5EE",
      color: "#085041",
      bd: "#5DCAA5",
      label: "Extract",
    },
    link_evidence: {
      bg: "#F0EAFF",
      color: "#5B21B6",
      bd: "#C4B5FD",
      label: "Link as evidence",
    },
    browse: {
      bg: "var(--color-background-secondary)",
      color: "var(--color-text-tertiary)",
      bd: "var(--color-border-tertiary)",
      label: "Browse",
    },
    unsupported: {
      bg: "#F1EFE8",
      color: "#999",
      bd: "#B4B2A9",
      label: "Not supported",
    },
  };
  const s = map[action] || map.unsupported;
  return (
    <span
      style={{
        fontSize: 10,
        padding: "2px 7px",
        borderRadius: 4,
        fontWeight: 500,
        background: s.bg,
        color: s.color,
        border: `0.5px solid ${s.bd}`,
        whiteSpace: "nowrap",
      }}
    >
      {s.label}
    </span>
  );
};

// ── Breadcrumb ─────────────────────────────────────────────────────────────────
const Breadcrumb = ({ trail, onNavigate }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 4,
      fontSize: 12,
      marginBottom: 10,
      flexWrap: "wrap",
    }}
  >
    <span
      role="button"
      tabIndex={0}
      onClick={() => onNavigate(null, null, true)}
      onKeyDown={(e) => e.key === "Enter" && onNavigate(null, null, true)}
      style={{
        color: "var(--color-text-info)",
        cursor: "pointer",
        fontWeight: 500,
      }}
    >
      GRC MASTERY
    </span>
    {trail.map((crumb, i) => (
      <span
        key={crumb.id}
        style={{ display: "flex", alignItems: "center", gap: 4 }}
      >
        <span style={{ color: "var(--color-text-tertiary)" }}>›</span>
        <span
          role="button"
          tabIndex={0}
          onClick={() =>
            i < trail.length - 1 && onNavigate(crumb.id, crumb.name, false, i)
          }
          onKeyDown={(e) =>
            e.key === "Enter" &&
            i < trail.length - 1 &&
            onNavigate(crumb.id, crumb.name, false, i)
          }
          style={{
            color:
              i === trail.length - 1
                ? "var(--color-text-primary)"
                : "var(--color-text-info)",
            cursor: i === trail.length - 1 ? "default" : "pointer",
            fontWeight: i === trail.length - 1 ? 600 : 400,
          }}
        >
          {crumb.name}
        </span>
      </span>
    ))}
  </div>
);

// ── SharePoint browser ─────────────────────────────────────────────────────────
const SharePointBrowser = ({ onSelectFile, selectedFile }) => {
  const [currentFolderId, setCurrentFolderId] = useState(null);
  const [trail, setTrail] = useState([]);
  const [search, setSearch] = useState("");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["sp-browse", currentFolderId],
    queryFn: () => sharePointApi.browse(currentFolderId),
    staleTime: 600_000, // 10 minutes
  });

  const handleNavigate = (id, name, toRoot = false, trailIndex = null) => {
    setSearch(""); // clear search on navigation
    if (toRoot) {
      setCurrentFolderId(null);
      setTrail([]);
      return;
    }
    if (trailIndex !== null) {
      setCurrentFolderId(id);
      setTrail((prev) => prev.slice(0, trailIndex + 1));
      return;
    }
    setCurrentFolderId(id);
    setTrail((prev) => [...prev, { id, name }]);
  };

  const handleItemClick = (item) => {
    if (item.type === "folder") handleNavigate(item.id, item.name);
    else if (item.action === "extract" || item.action === "link_evidence")
      onSelectFile(item);
  };

  // Filter items by search
  const visibleItems = data?.items
    ? search.trim()
      ? data.items.filter((i) =>
          i.name.toLowerCase().includes(search.toLowerCase()),
        )
      : data.items
    : [];

  return (
    <div>
      <Breadcrumb trail={trail} onNavigate={handleNavigate} />

      {/* Search */}
      {!isLoading && !error && data && data.items.length > 0 && (
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`Search in ${trail.length > 0 ? trail[trail.length - 1].name : "GRC MASTERY"}...`}
          style={{
            width: "100%",
            fontSize: 13,
            padding: "8px 12px",
            borderRadius: 8,
            border: "1.5px solid #C0C0C0",
            background: "var(--color-background-primary)",
            color: "var(--color-text-primary)",
            marginBottom: 10,
            boxSizing: "border-box",
            outline: "none",
          }}
          onFocus={(e) => (e.target.style.borderColor = "#378ADD")}
          onBlur={(e) => (e.target.style.borderColor = "#C0C0C0")}
        />
      )}

      {isLoading && (
        <div style={{ padding: "24px 0", textAlign: "center" }}>
          <div
            style={{
              width: 20,
              height: 20,
              border: "2px solid var(--color-border-tertiary)",
              borderTop: "2px solid #378ADD",
              borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
              margin: "0 auto 8px",
            }}
          />
          <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
            Loading folder...
          </div>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {error && (
        <div
          style={{
            padding: "12px 14px",
            background: "#FCEBEB",
            borderRadius: 8,
            fontSize: 12,
            color: "#791F1F",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span>Could not load folder: {error.message}</span>
          <button
            onClick={refetch}
            style={{
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 4,
              border: "1px solid #F09595",
              background: "transparent",
              color: "#791F1F",
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !error && data && (
        <>
          {visibleItems.length === 0 ? (
            <div
              style={{
                padding: "24px 0",
                textAlign: "center",
                fontSize: 12,
                color: "var(--color-text-tertiary)",
              }}
            >
              {search ? `No items match "${search}"` : "This folder is empty."}
            </div>
          ) : (
            <div
              style={{
                border: "1px solid #D0D0D0",
                borderRadius: 10,
                overflow: "hidden",
              }}
            >
              {visibleItems.map((item, i) => {
                const clickable =
                  item.type === "folder" ||
                  item.action === "extract" ||
                  item.action === "link_evidence";
                const isSelected = selectedFile?.id === item.id;
                return (
                  <div
                    key={item.id}
                    role={clickable ? "button" : undefined}
                    tabIndex={clickable ? 0 : undefined}
                    onClick={() => clickable && handleItemClick(item)}
                    onKeyDown={(e) =>
                      e.key === "Enter" && clickable && handleItemClick(item)
                    }
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 12px",
                      borderBottom:
                        i < visibleItems.length - 1
                          ? "1px solid #E8E8E8"
                          : "none",
                      cursor: clickable ? "pointer" : "default",
                      background: isSelected
                        ? "#E1F5EE"
                        : i % 2
                          ? "var(--color-background-secondary)"
                          : "transparent",
                      opacity: item.action === "unsupported" ? 0.45 : 1,
                      borderLeft: isSelected
                        ? "3px solid #5DCAA5"
                        : "3px solid transparent",
                    }}
                    onMouseEnter={(e) =>
                      !isSelected &&
                      clickable &&
                      (e.currentTarget.style.background =
                        "var(--color-background-info)")
                    }
                    onMouseLeave={(e) =>
                      !isSelected &&
                      (e.currentTarget.style.background =
                        i % 2
                          ? "var(--color-background-secondary)"
                          : "transparent")
                    }
                  >
                    <FileIcon ext={item.extension} type={item.type} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontSize: 12,
                          fontWeight: item.type === "folder" ? 600 : 400,
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          color: isSelected
                            ? "#085041"
                            : "var(--color-text-primary)",
                        }}
                      >
                        {item.name}
                        {item.type === "folder" && item.child_count > 0 && (
                          <span
                            style={{
                              fontSize: 10,
                              color: "var(--color-text-tertiary)",
                              fontWeight: 400,
                              marginLeft: 6,
                            }}
                          >
                            {item.child_count} items
                          </span>
                        )}
                      </div>
                      {item.modified_by && (
                        <div
                          style={{
                            fontSize: 10,
                            color: "var(--color-text-tertiary)",
                          }}
                        >
                          {item.modified_by} ·{" "}
                          {item.modified
                            ? new Date(item.modified).toLocaleDateString()
                            : ""}
                        </div>
                      )}
                    </div>
                    <ActionBadge
                      action={isSelected ? "extract" : item.action}
                    />
                    {item.type === "folder" && (
                      <span
                        style={{
                          fontSize: 12,
                          color: "var(--color-text-tertiary)",
                        }}
                      >
                        ›
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {search && (
            <div
              style={{
                fontSize: 11,
                color: "var(--color-text-tertiary)",
                marginTop: 6,
              }}
            >
              {visibleItems.length} of {data.items.length} items
            </div>
          )}

          {data.has_more && (
            <button
              onClick={refetch}
              style={{
                marginTop: 8,
                width: "100%",
                padding: "8px",
                fontSize: 12,
                borderRadius: 8,
                border: "1.5px solid #C0C0C0",
                background: "transparent",
                color: "var(--color-text-secondary)",
                cursor: "pointer",
              }}
            >
              Load more
            </button>
          )}
        </>
      )}
    </div>
  );
};

// ── Upload from device ─────────────────────────────────────────────────────────
const UploadFromDevice = ({ onSelectFile }) => {
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef();

  const handleFile = (f) => {
    if (!f) return;
    const ext = f.name.split(".").pop().toLowerCase();
    const action =
      ext === "eml"
        ? "link_evidence"
        : ["pdf", "docx", "txt"].includes(ext)
          ? "extract"
          : "unsupported";
    onSelectFile({
      id: null,
      name: f.name,
      extension: ext,
      action,
      _fileObject: f,
    });
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        handleFile(e.dataTransfer.files[0]);
      }}
      onClick={() => fileRef.current?.click()}
      style={{
        border: `2px dashed ${dragOver ? "#378ADD" : "#C0C0C0"}`,
        borderRadius: 12,
        padding: "32px 20px",
        textAlign: "center",
        cursor: "pointer",
        background: dragOver
          ? "var(--color-background-info)"
          : "var(--color-background-secondary)",
        transition: "all 0.15s",
      }}
    >
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.txt,.eml"
        style={{ display: "none" }}
        onChange={(e) => handleFile(e.target.files[0])}
      />
      <div
        style={{
          fontSize: 13,
          fontWeight: 500,
          color: "var(--color-text-secondary)",
          marginBottom: 4,
        }}
      >
        Drop your document here or click to browse
      </div>
      <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
        PDF, DOCX, TXT, EML — max 10MB
      </div>
    </div>
  );
};

// ── Selected file panel ────────────────────────────────────────────────────────
const SelectedFilePanel = ({
  file,
  docCode,
  setDocCode,
  onExtract,
  onClear,
  loading,
  error,
}) => {
  const isEml = file.action === "link_evidence";
  const isUnsupported = file.action === "unsupported";
  const borderColor = isEml ? "#C4B5FD" : isUnsupported ? "#B4B2A9" : "#5DCAA5";
  const bg = isEml ? "#F0EAFF" : isUnsupported ? "#F1EFE8" : "#E1F5EE";

  return (
    <div
      style={{
        border: `1.5px solid ${borderColor}`,
        borderRadius: 12,
        padding: "14px 16px",
        background: bg,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <FileIcon ext={file.extension} type="file" />
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{file.name}</div>
            <div
              style={{
                fontSize: 10,
                color: "var(--color-text-tertiary)",
                marginTop: 2,
              }}
            >
              {file._fileObject
                ? `${(file._fileObject.size / 1024).toFixed(1)} KB · From device`
                : "From SharePoint"}
            </div>
          </div>
        </div>
        <button
          onClick={onClear}
          style={{
            fontSize: 11,
            padding: "3px 8px",
            borderRadius: 5,
            border: "1px solid #C0C0C0",
            background: "transparent",
            color: "var(--color-text-secondary)",
            cursor: "pointer",
          }}
        >
          Change
        </button>
      </div>

      {isEml && (
        <div
          style={{
            padding: "10px 12px",
            background: "#EDE9FE",
            borderRadius: 8,
            fontSize: 12,
            color: "#5B21B6",
          }}
        >
          EML files are evidence documents. <strong>Link as evidence</strong>{" "}
          connects this file to a control in the Evidence Tracker. This feature
          is coming in Tier 2.
        </div>
      )}

      {isUnsupported && (
        <div
          style={{
            padding: "10px 12px",
            background: "#F1EFE8",
            borderRadius: 8,
            fontSize: 12,
            color: "#444441",
          }}
        >
          File type not supported for extraction. Use PDF, DOCX, or TXT.
        </div>
      )}

      {!isEml && !isUnsupported && (
        <>
          <div style={{ marginBottom: 10 }}>
            <label
              style={{
                display: "block",
                fontSize: 11,
                fontWeight: 500,
                color: "var(--color-text-secondary)",
                marginBottom: 4,
                textTransform: "uppercase",
                letterSpacing: "0.4px",
              }}
            >
              Document code <span style={{ color: "#A32D2D" }}>*</span>
            </label>
            <input
              type="text"
              value={docCode}
              onChange={(e) => setDocCode(e.target.value)}
              placeholder="DRG-ISMS-POL-ACP-01-25"
              style={{
                width: "100%",
                fontSize: 13,
                padding: "8px 10px",
                borderRadius: 8,
                border: "1.5px solid #C0C0C0",
                background: "var(--color-background-primary)",
                color: "var(--color-text-primary)",
                outline: "none",
                boxSizing: "border-box",
                fontFamily: "var(--font-mono)",
              }}
              onFocus={(e) => (e.target.style.borderColor = "#378ADD")}
              onBlur={(e) => (e.target.style.borderColor = "#C0C0C0")}
            />
          </div>
          {error && (
            <div
              style={{
                padding: "8px 10px",
                background: "#FCEBEB",
                border: "1px solid #F09595",
                borderRadius: 8,
                fontSize: 12,
                color: "#791F1F",
                marginBottom: 10,
              }}
            >
              {error}
            </div>
          )}
          <button
            onClick={onExtract}
            disabled={loading || !docCode.trim()}
            style={{
              width: "100%",
              padding: "10px",
              fontSize: 13,
              fontWeight: 600,
              borderRadius: 8,
              border: "none",
              background: loading || !docCode.trim() ? "#E8E8E8" : "#1D9E75",
              color: loading || !docCode.trim() ? "#999" : "#fff",
              cursor: loading || !docCode.trim() ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Extracting — please wait..." : "Extract controls"}
          </button>
          {loading && (
            <div
              style={{
                marginTop: 8,
                fontSize: 11,
                color: "var(--color-text-secondary)",
                textAlign: "center",
              }}
            >
              The local LLM is processing your document. This takes 1-2 minutes.
            </div>
          )}
        </>
      )}
    </div>
  );
};



// ── Extraction result card ─────────────────────────────────────────────────────
const ExtractionCard = ({
  item,
  index,
  onSubmit,
  submitted,
  isComplianceUser,
}) => {
  const [expanded, setExpanded] = useState(false);
  const isComplete = item.completeness_flag === "COMPLETE";
  const borderColor = isComplete ? "#5DCAA5" : "#F09595";

  return (
    <div
      style={{
        border: `1px solid ${borderColor}`,
        borderLeft: `4px solid ${borderColor}`,
        borderRadius: 12,
        background: submitted
          ? "var(--color-background-secondary)"
          : "var(--color-background-primary)",
        opacity: submitted ? 0.6 : 1,
        transition: "box-shadow 0.15s",
      }}
      onMouseEnter={(e) =>
        !submitted &&
        (e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)")
      }
      onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "none")}
    >
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => e.key === "Enter" && setExpanded(!expanded)}
        style={{ padding: "12px 14px", cursor: "pointer" }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 6,
            flexWrap: "wrap",
            gap: 6,
          }}
        >
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <StatusBadge label={isComplete ? "Complete" : "Deficient"} />
            <StatusBadge label={item.control_type} />
            {item.iso_clause && (
              <span
                style={{
                  fontSize: 10,
                  padding: "1px 6px",
                  borderRadius: 3,
                  background: "var(--color-background-secondary)",
                  color: "var(--color-text-tertiary)",
                  border: "0.5px solid var(--color-border-tertiary)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {item.iso_clause}
              </span>
            )}
            {item.source_clause && (
              <span
                style={{
                  fontSize: 10,
                  padding: "1px 6px",
                  borderRadius: 3,
                  background: "var(--color-background-secondary)",
                  color: "var(--color-text-tertiary)",
                  border: "0.5px solid var(--color-border-tertiary)",
                }}
              >
                {item.source_clause}
              </span>
            )}
          </div>
          <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {expanded ? "▲ collapse" : "▼ expand"}
          </span>
        </div>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            lineHeight: 1.4,
            marginBottom: 4,
          }}
        >
          {item.control_statement}
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div style={{ fontSize: 11, color: "#A32D2D", flex: 1 }}>
            Risk: {item.risk_statement}
          </div>
          <div style={{ minWidth: 120 }}>
            <ConfidenceBar score={item.confidence_score} />
          </div>
        </div>
        {item.deficiency_reason && (
          <div
            style={{
              marginTop: 8,
              padding: "6px 10px",
              background: "#FCEBEB",
              borderRadius: 6,
              fontSize: 11,
              color: "#791F1F",
            }}
          >
            Deficiency: {item.deficiency_reason}
          </div>
        )}
      </div>
      {expanded && (
        <div style={{ padding: "0 14px 14px" }}>
          <div
            style={{
              borderTop: "0.5px solid var(--color-border-tertiary)",
              paddingTop: 12,
            }}
          >
            <Field l="Evidence required" v={item.evidence_required} />
            <Field l="Evidence frequency" v={item.evidence_frequency} />
            <Field l="Proposed owner" v={item.proposed_owner_role} />
            <Field l="ISO clause" v={item.iso_clause} />
            <Field l="Source clause" v={item.source_clause} />
          </div>
          {isComplete && !submitted && isComplianceUser && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onSubmit(index);
              }}
              style={{
                marginTop: 12,
                padding: "8px 16px",
                fontSize: 12,
                borderRadius: 8,
                border: "none",
                background: "#534AB7",
                color: "#fff",
                cursor: "pointer",
                fontWeight: 500,
                width: "100%",
              }}
            >
              Submit to AI Review Queue →
            </button>
          )}
          {submitted && (
            <div
              style={{
                marginTop: 12,
                padding: "8px 12px",
                background: "#E1F5EE",
                borderRadius: 8,
                fontSize: 12,
                color: "#085041",
                textAlign: "center",
                fontWeight: 500,
              }}
            >
              Submitted to AI Review Queue
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const SummaryBar = ({ result }) => (
  <div
    style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
      gap: 10,
      marginBottom: 16,
    }}
  >
    {[
      {
        label: "Total extracted",
        value: result.total_extracted,
        color: "#534AB7",
        bg: "#EEEDFE",
        bd: "#AFA9EC",
      },
      {
        label: "Complete",
        value: result.complete_count,
        color: "#085041",
        bg: "#E1F5EE",
        bd: "#5DCAA5",
      },
      {
        label: "Deficient",
        value: result.deficient_count,
        color: "#791F1F",
        bg: "#FCEBEB",
        bd: "#F09595",
      },
    ].map((s) => (
      <div
        key={s.label}
        style={{
          padding: "12px 14px",
          borderRadius: 10,
          background: s.bg,
          border: `1px solid ${s.bd}`,
        }}
      >
        <div
          style={{
            fontSize: 24,
            fontWeight: 700,
            color: s.color,
            letterSpacing: "-1px",
          }}
        >
          {s.value}
        </div>
        <div style={{ fontSize: 11, color: s.color, marginTop: 2 }}>
          {s.label}
        </div>
      </div>
    ))}
  </div>
);

// ── Main ───────────────────────────────────────────────────────────────────────
export default function Extractor() {
  const [mode, setMode] = useState("sharepoint");
  const { isCompliance } = useCurrentUserRole();
  const [selectedFile, setSelectedFile] = useState(null);
  const [docCode, setDocCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState({});

  const handleSelectFile = (file) => {
    setSelectedFile(file);
    setResult(null);
    setError("");
    setSubmitted({});
    const nameWithoutExt = file.name
      .replace(/\.(pdf|docx|txt|eml)$/i, "")
      .toUpperCase();
    setDocCode(nameWithoutExt);
  };

  const handleClear = () => {
    setSelectedFile(null);
    setDocCode("");
    setResult(null);
    setError("");
    setSubmitted({});
  };

  const handleExtract = async () => {
    if (!selectedFile || !docCode.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    setSubmitted({});

    try {
      const data = selectedFile._fileObject
        ? await extractorApi.extractFile(
            selectedFile._fileObject,
            docCode.trim(),
          )
        : await extractorApi.extractFromSharePoint(
            selectedFile.id,
            docCode.trim(),
          );
      setResult(data);
    } catch (err) {
      setError(
        err.message || "Extraction failed. Check that Ollama is running.",
      );
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitToQueue = async (index) => {
    try {
      await extractorApi.submitToQueue(
        result.items[index],
        result.source_document_code,
      );
      setSubmitted((prev) => ({ ...prev, [index]: true }));
    } catch (err) {
      setError(`Failed to submit item ${index + 1}: ${err.message}`);
    }
  };

  return (
    <>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 20,
        }}
      >
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 3 }}>
            Document extractor
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Select a compliance document and extract risks, controls, evidence
            requirements, and ISO clause mappings.
          </div>
        </div>
        <div
          style={{
            fontSize: 10,
            padding: "3px 8px",
            borderRadius: 4,
            background: "#FAEEDA",
            color: "#633806",
            border: "0.5px solid #FAC775",
            fontWeight: 500,
          }}
        >
          Phase 3 — Extractor
        </div>
      </div>

      {/* Mode tabs */}
      <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
        {[
          { k: "sharepoint", label: "Load from SharePoint" },
          { k: "upload", label: "Upload from device" },
        ].map((tab) => (
          <button
            key={tab.k}
            onClick={() => {
              setMode(tab.k);
              handleClear();
            }}
            style={{
              padding: "8px 16px",
              fontSize: 12,
              borderRadius: 8,
              cursor: "pointer",
              fontWeight: mode === tab.k ? 600 : 400,
              border:
                mode === tab.k ? "1.5px solid #378ADD" : "1.5px solid #C0C0C0",
              background:
                mode === tab.k
                  ? "var(--color-background-info)"
                  : "var(--color-background-primary)",
              color:
                mode === tab.k
                  ? "var(--color-text-info)"
                  : "var(--color-text-secondary)",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Selected file panel */}
      {selectedFile && (
        <div style={{ marginBottom: 16 }}>
          <SelectedFilePanel
            file={selectedFile}
            docCode={docCode}
            setDocCode={setDocCode}
            onExtract={handleExtract}
            onClear={handleClear}
            loading={loading}
            error={error}
          />
        </div>
      )}
      {/* Browser / upload — always visible, browser highlights selected file */}
      <div style={{ marginBottom: 16 }}>
        {mode === "sharepoint" ? (
          <SharePointBrowser
            onSelectFile={handleSelectFile}
            selectedFile={selectedFile}
          />
        ) : (
          !selectedFile && <UploadFromDevice onSelectFile={handleSelectFile} />
        )}
      </div>

      {/* Results */}
      {result && !loading && (
        <>
          <SummaryBar result={result} />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600 }}>Extracted items</div>
            <span
              style={{
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                color: "var(--color-text-tertiary)",
              }}
            >
              {result.source_document_code}
            </span>
          </div>
          {result.items.length === 0 ? (
            <div
              style={{
                padding: "32px 24px",
                textAlign: "center",
                border: "1px dashed var(--color-border-tertiary)",
                borderRadius: 12,
                fontSize: 13,
                color: "var(--color-text-tertiary)",
              }}
            >
              No controls extracted. Try a longer policy document.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {result.items.map((item, i) => (
                <ExtractionCard
                  key={i}
                  item={item}
                  index={i}
                  onSubmit={handleSubmitToQueue}
                  submitted={!!submitted[i]}
                  isComplianceUser={isCompliance}
                />
              ))}
            </div>
          )}
          {result.deficient_count > 0 && (
            <div
              style={{
                marginTop: 16,
                padding: "12px 14px",
                background: "#FAEEDA",
                border: "1px solid #FAC775",
                borderRadius: 10,
                fontSize: 12,
                color: "#633806",
              }}
            >
              {result.deficient_count} item
              {result.deficient_count > 1 ? "s are" : " is"} deficient —
              risk-control-evidence chain incomplete. Expand to see what is
              missing.
            </div>
          )}
        </>
      )}
    </>
  );
}
