// =============================================================================
// components/shared/SearchSelect.jsx
// A dropdown you can type into: the list narrows to the options containing every
// word typed. Used where the list is long (Org Roles has hundreds of names).
//
// Props:
//   value, onChange(value)   — the chosen option ("" = none)
//   options                  — array of strings
//   placeholder              — shown when nothing is chosen
//   invalid                  — highlight the border (nothing chosen yet)
// =============================================================================

import { useEffect, useMemo, useRef, useState } from "react";

export default function SearchSelect({ value, onChange, options = [], placeholder = "Search…", invalid = false,
                                       borderColor = "#E5A93C" }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const box = useRef(null);

  useEffect(() => {
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return words.length ? options.filter((o) => words.every((w) => o.toLowerCase().includes(w))) : options;
  }, [options, query]);

  const pick = (o) => { onChange(o); setQuery(""); setOpen(false); };

  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, shown.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter" && open && shown[active]) { e.preventDefault(); pick(shown[active]); }
    else if (e.key === "Escape") setOpen(false);
  };

  return (
    <div ref={box} style={{ position: "relative", marginTop: 10 }}>
      <input
        type="text" role="combobox" aria-expanded={open} aria-label={placeholder}
        value={open ? query : value}
        onChange={(e) => { setQuery(e.target.value); setActive(0); setOpen(true); }}
        onFocus={() => { setQuery(""); setOpen(true); }}
        onKeyDown={onKey}
        placeholder={value || placeholder}
        autoComplete="off"
        style={{ width: "100%", padding: "8px 10px", fontSize: 12.5, borderRadius: 8, boxSizing: "border-box",
                 border: `1.5px solid ${invalid ? borderColor : "var(--color-border-tertiary)"}`,
                 background: "var(--color-background-primary)", color: "var(--color-text-primary)" }}
      />
      {open && (
        <div role="listbox" style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 1200, marginTop: 2,
          maxHeight: 220, overflowY: "auto", borderRadius: 8, background: "var(--color-background-primary)",
          border: "1.5px solid var(--color-border-secondary, #C0C0C0)", boxShadow: "0 8px 24px rgba(0,0,0,0.14)" }}>
          {shown.length === 0 && (
            <div style={{ padding: "9px 12px", fontSize: 12, color: "var(--color-text-tertiary)" }}>
              No match for “{query}”
            </div>
          )}
          {shown.map((o, i) => (
            <div key={o} role="option" aria-selected={o === value}
              onMouseDown={(e) => { e.preventDefault(); pick(o); }}
              onMouseEnter={() => setActive(i)}
              style={{ padding: "8px 12px", fontSize: 12.5, cursor: "pointer",
                       fontWeight: o === value ? 600 : 400,
                       background: i === active ? "var(--color-background-secondary)" : "transparent" }}>
              {o}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
