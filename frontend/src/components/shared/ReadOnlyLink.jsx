// =============================================================================
// ReadOnlyLink.jsx — open a document in SharePoint without being able to edit it
//
// A document's stored webUrl opens Word for the web with whatever rights the
// viewer already has, which at Dragnet usually means EDIT. Someone asked to
// review or approve a document could change the controlled source just by
// typing in it, and the change would bypass the CDI check that an upload runs.
//
// So the editable URL is never linked directly. This asks the backend for a
// view-only link at the moment it is clicked, and opens that instead.
// =============================================================================

import { useState } from "react";

const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export default function ReadOnlyLink({ docId, label = "SharePoint (read-only) ↗", style }) {
  const [cached, setCached] = useState("");
  const [state, setState] = useState("idle");   // "idle" | "loading" | error text

  const open = async () => {
    if (cached) { window.open(cached, "_blank", "noreferrer"); return; }
    setState("loading");
    try {
      const resp = await fetch(
        `${BASE}/api/v1/lifecycle/documents/${docId}/view-only-link`,
        { credentials: "include" },
      );
      if (!resp.ok) {
        let detail = "A read-only link could not be created.";
        try { detail = (await resp.json()).detail || detail; } catch { /**/ }
        throw new Error(detail);
      }
      const { url } = await resp.json();
      setCached(url);
      setState("idle");
      window.open(url, "_blank", "noreferrer");
    } catch (e) {
      setState(e.message || "A read-only link could not be created.");
    }
  };

  const failed = state !== "idle" && state !== "loading";

  return (
    <>
      <button onClick={open} disabled={state === "loading"}
        title="Opens a read-only link — the document cannot be edited through it"
        style={{
          padding: "7px 14px", fontSize: 12, borderRadius: 8, fontWeight: 600,
          border: "1.5px solid var(--color-border-tertiary)", background: "transparent",
          color: "var(--color-text-secondary)",
          cursor: state === "loading" ? "default" : "pointer",
          ...style,
        }}>
        {state === "loading" ? "Preparing…" : label}
      </button>
      {failed && (
        <div style={{ marginTop: 6, fontSize: 11.5, color: "#8A5A00" }}>{state}</div>
      )}
    </>
  );
}
