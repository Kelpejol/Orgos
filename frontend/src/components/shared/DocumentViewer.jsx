// =============================================================================
// DocumentViewer.jsx — read a controlled document in the browser
//
// "View" used to fetch the file and trigger a browser download, which handed
// the reviewer a file named after the SharePoint viewer page (Doc.aspx) or an
// opaque octet-stream. Reading a document should not mean downloading one.
//
// The backend renders the document as a PDF (cover facts merged in, so no raw
// {{ markers }}) and serves it inline; this shows it in an iframe. Downloading
// is still available, as a deliberate action rather than a side effect.
// =============================================================================

import { useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export default function DocumentViewer({ doc, onClose, onDownload }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);


  useEffect(() => {
    let live = true;
    let objectUrl = "";
    (async () => {
      try {
        const resp = await fetch(
          `${BASE}/api/v1/lifecycle/documents/${doc.id}/view.pdf`,
          { credentials: "include" },
        );
        if (!resp.ok) {
          let detail = `Could not open this document (${resp.status}).`;
          try { detail = (await resp.json()).detail || detail; } catch { /**/ }
          throw new Error(detail);
        }
        objectUrl = URL.createObjectURL(await resp.blob());
        if (!live) { URL.revokeObjectURL(objectUrl); return; }
        setUrl(objectUrl);
      } catch (e) {
        if (live) setError(e.message || "Could not open this document.");
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [doc.id]);

  const btn = (bg, fg, bd) => ({
    padding: "7px 14px", fontSize: 12, borderRadius: 8, fontWeight: 600,
    border: bd || "none", background: bg, color: fg, cursor: "pointer",
    textDecoration: "none", display: "inline-block",
  });

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 1100, background: "rgba(17,20,24,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: "3vh 16px",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "100%", maxWidth: 960, height: "94vh", background: "var(--color-background-primary)",
        borderRadius: 14, boxShadow: "0 24px 60px rgba(0,0,0,0.3)",
        display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--color-border-tertiary)",
          display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {doc.Title || doc.DocumentCode || "Document"}
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>
              {doc.DocumentCode || ""}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
            {onDownload && (
              <button onClick={onDownload}
                style={btn("transparent", "var(--color-text-secondary)", "1.5px solid var(--color-border-tertiary)")}>
                Download
              </button>
            )}
            <button onClick={onClose} style={{ fontSize: 22, lineHeight: 1, border: "none",
              background: "transparent", color: "var(--color-text-tertiary)", cursor: "pointer" }}>×</button>
          </div>
        </div>

        <div style={{ flex: 1, background: "#52565B", position: "relative" }}>
          {loading && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center",
              justifyContent: "center", color: "#fff", fontSize: 13 }}>
              Opening the document…
            </div>
          )}
          {error && (
            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: 12, padding: 24, textAlign: "center" }}>
              <div style={{ color: "#fff", fontSize: 13, maxWidth: 420, lineHeight: 1.5 }}>{error}</div>
              {onDownload && (
                <button onClick={onDownload} style={btn("#fff", "#1C1E21")}>Download it instead</button>
              )}
            </div>
          )}
          {url && !error && (
            <iframe title="Document" src={url}
              style={{ width: "100%", height: "100%", border: "none", display: "block" }} />
          )}
        </div>
      </div>
    </div>
  );
}
