// =============================================================================
// components/shared/UserSearchField.jsx
// Debounced user search with auto-suggest dropdown.
// Replaces the type-full-email + click "Look up" pattern everywhere.
//
// Props:
//   onSelect(user | null)  — called with {oid, display_name, email, job_title}
//                            or null when selection is cleared
//   label                  — field label (default "Search person")
//   placeholder            — input placeholder
//   accentColor            — border/highlight colour (default #378ADD)
//   clearAfterSelect       — if true, field resets after each selection (for lists)
// =============================================================================

import { useState, useEffect, useRef } from "react";
import apiClient from "../../api/grcApi.js";

function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export default function UserSearchField({
  onSelect,
  label         = "Search person",
  placeholder   = "Type name or email...",
  accentColor   = "#378ADD",
  clearAfterSelect = false,
}) {
  const [query,    setQuery]    = useState("");
  const [results,  setResults]  = useState([]);
  const [loading,  setLoading]  = useState(false);
  const [selected, setSelected] = useState(null);
  const [open,     setOpen]     = useState(false);
  const containerRef = useRef(null);

  const debouncedQuery = useDebounce(query, 280);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Search when debounced query changes
  useEffect(() => {
    if (debouncedQuery.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiClient
      .get("/api/v1/grc/users/search", { params: { q: debouncedQuery } })
      .then((r) => {
        if (!cancelled) {
          setResults(r.data || []);
          setOpen((r.data || []).length > 0);
        }
      })
      .catch(() => { if (!cancelled) setResults([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [debouncedQuery]);

  const handleSelect = (user) => {
    setOpen(false);
    if (clearAfterSelect) {
      setQuery("");
      setResults([]);
      setSelected(null);
    } else {
      setQuery(user.display_name || user.email);
      setSelected(user);
    }
    onSelect(user);
  };

  const handleClear = () => {
    setQuery("");
    setResults([]);
    setSelected(null);
    setOpen(false);
    onSelect(null);
  };

  return (
    <div ref={containerRef} style={{ marginBottom: 12 }}>
      {label && (
        <label style={{
          display: "block", fontSize: 11, fontWeight: 600,
          color: "var(--color-text-secondary)", marginBottom: 5,
          textTransform: "uppercase", letterSpacing: "0.4px",
        }}>
          {label}
        </label>
      )}

      <div style={{ position: "relative" }}>
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (selected) { setSelected(null); onSelect(null); }
          }}
          onFocus={(e) => {
            e.target.style.borderColor = accentColor;
            if (results.length > 0) setOpen(true);
          }}
          onBlur={(e) => {
            e.target.style.borderColor = selected ? accentColor : "#C0C0C0";
          }}
          placeholder={placeholder}
          autoComplete="off"
          style={{
            width: "100%", fontSize: 13, padding: "9px 32px 9px 11px",
            borderRadius: open ? "8px 8px 0 0" : 8,
            border: `1.5px solid ${selected ? accentColor : "#C0C0C0"}`,
            background: "var(--color-background-primary)",
            color: "var(--color-text-primary)", outline: "none",
            boxSizing: "border-box", transition: "border-color 0.15s",
          }}
        />

        {/* Loading / clear indicator */}
        {loading && (
          <span style={{
            position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
            fontSize: 11, color: "var(--color-text-tertiary)", pointerEvents: "none",
          }}>
            ···
          </span>
        )}
        {selected && !loading && (
          <button
            onMouseDown={(e) => { e.preventDefault(); handleClear(); }}
            style={{
              position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
              background: "none", border: "none", cursor: "pointer",
              fontSize: 16, color: "var(--color-text-tertiary)", lineHeight: 1, padding: 2,
            }}
          >
            ×
          </button>
        )}

        {/* Dropdown */}
        {open && results.length > 0 && (
          <div style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 1200,
            background: "var(--color-background-primary)",
            border: `1.5px solid ${accentColor}`,
            borderTop: "none", borderRadius: "0 0 8px 8px",
            boxShadow: "0 8px 24px rgba(0,0,0,0.14)",
            maxHeight: 220, overflowY: "auto",
          }}>
            {results.map((r, i) => (
              <div
                key={r.oid}
                onMouseDown={(e) => { e.preventDefault(); handleSelect(r); }}
                style={{
                  padding: "9px 12px", cursor: "pointer",
                  borderTop: i > 0 ? "0.5px solid var(--color-border-tertiary)" : "none",
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = "var(--color-background-secondary)")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background = "transparent")
                }
              >
                <div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>
                  {r.display_name}
                </div>
                <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 1 }}>
                  {r.email}{r.job_title ? ` · ${r.job_title}` : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Selected person card */}
      {selected && (
        <div style={{
          marginTop: 6, padding: "9px 12px", borderRadius: 8,
          background: `${accentColor}12`,
          border: `1px solid ${accentColor}50`,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-primary)" }}>
              {selected.display_name}
            </div>
            {(selected.job_title || selected.email) && (
              <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 1 }}>
                {selected.job_title && `${selected.job_title} · `}{selected.email}
              </div>
            )}
          </div>
          <span style={{
            fontSize: 10, padding: "2px 7px", borderRadius: 4,
            background: accentColor, color: "#fff", fontWeight: 600, flexShrink: 0,
          }}>
            ✓
          </span>
        </div>
      )}
    </div>
  );
}
