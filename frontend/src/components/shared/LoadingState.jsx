// =============================================================================
// components/shared/LoadingState.jsx
// Loading skeleton and error states used on every data-fetching page.
// =============================================================================

/**
 * Full-page loading spinner with message.
 * @param {{ message?: string }} props
 */
export function LoadingState({ message = "Loading..." }) {
  return (
    <div
      style={{
        padding: "48px 0",
        textAlign: "center",
        color: "var(--color-text-tertiary)",
        fontSize: 13,
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          border: "3px solid var(--color-border-tertiary)",
          borderTop: "3px solid #378ADD",
          borderRadius: "50%",
          animation: "spin 0.8s linear infinite",
          margin: "0 auto 12px",
        }}
      />
      {message}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

/**
 * Table skeleton rows shown while data is loading.
 * Matches the table layout in the register pages.
 * @param {{ rows?: number, cols?: number }} props
 */
export function TableSkeleton({ rows = 5, cols = 6 }) {
  return (
    <div style={{ border: "1px solid #D0D0D0", borderRadius: 10, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ background: "var(--color-background-secondary)" }}>
            {Array.from({ length: cols }).map((_, i) => (
              <th key={i} style={{ padding: "7px 8px" }}>
                <div
                  style={{
                    height: 10,
                    borderRadius: 4,
                    background: "#E8E8E8",
                    animation: "pulse 1.5s ease-in-out infinite",
                  }}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, ri) => (
            <tr key={ri} style={{ borderBottom: "1px solid #E8E8E8" }}>
              {Array.from({ length: cols }).map((_, ci) => (
                <td key={ci} style={{ padding: "8px 8px" }}>
                  <div
                    style={{
                      height: 10,
                      borderRadius: 4,
                      background: ri % 2 === 0 ? "#F0F0F0" : "#E8E8E8",
                      width: ci === 0 ? "80%" : ci === cols - 1 ? "40%" : "65%",
                      animation: "pulse 1.5s ease-in-out infinite",
                      animationDelay: `${ci * 0.1}s`,
                    }}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}

/**
 * Error state with retry button.
 * @param {{ error: Error|string, onRetry?: Function, message?: string }} props
 */
export function ErrorState({ error, onRetry, message }) {
  const displayMessage =
    message ||
    (error instanceof Error ? error.message : String(error)) ||
    "Something went wrong";

  return (
    <div
      style={{
        padding: "32px 24px",
        background: "#FCEBEB",
        border: "1px solid #F09595",
        borderRadius: 10,
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: "#791F1F", marginBottom: 6 }}>
        Unable to load data
      </div>
      <div
        style={{
          fontSize: 12,
          color: "#791F1F",
          opacity: 0.8,
          marginBottom: onRetry ? 14 : 0,
          maxWidth: 400,
          margin: "0 auto",
        }}
      >
        {displayMessage}
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            marginTop: 12,
            padding: "7px 16px",
            fontSize: 12,
            borderRadius: 8,
            border: "1px solid #F09595",
            background: "#fff",
            color: "#791F1F",
            cursor: "pointer",
            fontWeight: 500,
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

/**
 * Empty state — shown when a register has no items.
 * @param {{ message?: string, action?: React.ReactNode }} props
 */
export function EmptyState({ message = "No items found.", action }) {
  return (
    <div
      style={{
        padding: "48px 24px",
        textAlign: "center",
        border: "1px dashed var(--color-border-tertiary)",
        borderRadius: 10,
      }}
    >
      <div style={{ fontSize: 13, color: "var(--color-text-tertiary)", marginBottom: action ? 14 : 0 }}>
        {message}
      </div>
      {action}
    </div>
  );
}
