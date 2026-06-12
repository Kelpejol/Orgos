// =============================================================================
// components/shared/AlertModal.jsx
// Shared promise-based modal for app alerts and confirmations.
// =============================================================================

import { createContext, useCallback, useContext, useMemo, useState } from "react";

const AlertContext = createContext(null);

const TONES = {
  info: {
    accent: "#378ADD",
    bg: "#E6F1FB",
    border: "#85B7EB",
    title: "Notice",
    symbol: "i",
  },
  danger: {
    accent: "#A32D2D",
    bg: "#FCEBEB",
    border: "#F09595",
    title: "Please confirm",
    symbol: "!",
  },
  success: {
    accent: "#1D9E75",
    bg: "#E1F5EE",
    border: "#5DCAA5",
    title: "Done",
    symbol: "✓",
  },
  warning: {
    accent: "#BA7517",
    bg: "#FAEEDA",
    border: "#FAC775",
    title: "Check this",
    symbol: "!",
  },
};

function AlertModal({ request, onClose }) {
  if (!request) return null;

  const tone = TONES[request.tone] || TONES.info;
  const isConfirm = request.kind === "confirm";

  const close = (value) => {
    request.resolve(value);
    onClose();
  };

  return (
    <div
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !request.locked) close(false);
      }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 5000,
        background: "rgba(25, 28, 33, 0.42)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        role={isConfirm ? "alertdialog" : "dialog"}
        aria-modal="true"
        aria-labelledby="orgos-alert-title"
        aria-describedby="orgos-alert-body"
        style={{
          width: "min(420px, 100%)",
          borderRadius: 12,
          background: "var(--color-background-primary)",
          border: "1px solid var(--color-border-secondary)",
          boxShadow: "0 22px 70px rgba(0,0,0,0.24)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: 4,
            background: tone.accent,
          }}
        />
        <div style={{ padding: "20px 22px 18px" }}>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
            <div
              aria-hidden="true"
              style={{
                width: 28,
                height: 28,
                borderRadius: 14,
                background: tone.bg,
                border: `1px solid ${tone.border}`,
                color: tone.accent,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 14,
                fontWeight: 800,
                flexShrink: 0,
                lineHeight: 1,
              }}
            >
              {tone.symbol}
            </div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div
                id="orgos-alert-title"
                style={{
                  fontSize: 15,
                  fontWeight: 700,
                  color: "var(--color-text-primary)",
                  marginBottom: 6,
                  lineHeight: 1.35,
                }}
              >
                {request.title || tone.title}
              </div>
              {request.message && (
                <div
                  id="orgos-alert-body"
                  style={{
                    fontSize: 13,
                    lineHeight: 1.5,
                    color: "var(--color-text-secondary)",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {request.message}
                </div>
              )}
            </div>
          </div>

          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 8,
              marginTop: 20,
            }}
          >
            {isConfirm && (
              <button
                type="button"
                onClick={() => close(false)}
                style={{
                  padding: "9px 15px",
                  fontSize: 12,
                  borderRadius: 8,
                  border: "1.5px solid #C0C0C0",
                  background: "var(--color-background-primary)",
                  color: "var(--color-text-primary)",
                  cursor: "pointer",
                }}
              >
                {request.cancelLabel || "Cancel"}
              </button>
            )}
            <button
              type="button"
              autoFocus
              onClick={() => close(true)}
              style={{
                padding: "9px 16px",
                fontSize: 12,
                borderRadius: 8,
                border: "none",
                background: tone.accent,
                color: "#fff",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              {request.confirmLabel || (isConfirm ? "Confirm" : "OK")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AlertProvider({ children }) {
  const [request, setRequest] = useState(null);

  const open = useCallback((options) => {
    return new Promise((resolve) => {
      setRequest({
        kind: "alert",
        tone: "info",
        ...options,
        resolve,
      });
    });
  }, []);

  const notify = useCallback(
    (options) => open({ kind: "alert", confirmLabel: "OK", ...options }),
    [open],
  );

  const confirm = useCallback(
    (options) => open({ kind: "confirm", tone: "danger", ...options }),
    [open],
  );

  const value = useMemo(() => ({ notify, confirm }), [notify, confirm]);

  return (
    <AlertContext.Provider value={value}>
      {children}
      <AlertModal request={request} onClose={() => setRequest(null)} />
    </AlertContext.Provider>
  );
}

export function useAlert() {
  const ctx = useContext(AlertContext);
  if (!ctx) {
    throw new Error("useAlert must be used inside AlertProvider");
  }
  return ctx;
}
