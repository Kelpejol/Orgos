// =============================================================================
// components/shared/Forms.jsx
// Atomic UI primitives extracted from the approved prototype.
// Field, Btn, InlineLink — used across all detail views and forms.
// =============================================================================

/**
 * Label/value row used in detail views.
 * @param {{ l: string, v: string|React.ReactNode, color?: string }} props
 */
export function Field({ l, v, color }) {
  return (
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
      <span style={{ color: "var(--color-text-secondary)", flexShrink: 0 }}>{l}</span>
      <span
        style={{
          color: color || "var(--color-text-primary)",
          textAlign: "right",
          wordBreak: "break-word",
        }}
      >
        {v ?? "—"}
      </span>
    </div>
  );
}

/**
 * Inline navigation link — used in detail views to jump to related registers.
 * @param {{ label: string, onClick: Function }} props
 */
export function InlineLink({ label, onClick }) {
  return (
    <span
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onClick?.()}
      style={{
        fontSize: 11,
        padding: "3px 8px",
        borderRadius: 5,
        background: "var(--color-background-info)",
        color: "var(--color-text-info)",
        cursor: "pointer",
        border: "0.5px solid var(--color-border-info)",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

/**
 * Standard button — primary (green), danger (red), or default (outlined).
 * @param {{ label: string, primary?: boolean, danger?: boolean, onClick?: Function, disabled?: boolean, type?: string }} props
 */
export function Btn({ label, primary, danger, onClick, disabled, type = "button" }) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "9px 14px",
        fontSize: 12,
        borderRadius: 8,
        border: primary || danger ? "none" : "1.5px solid #C0C0C0",
        background: disabled
          ? "#E8E8E8"
          : primary
          ? "#1D9E75"
          : danger
          ? "#A32D2D"
          : "var(--color-background-primary)",
        color: disabled ? "#999" : primary || danger ? "#fff" : "var(--color-text-primary)",
        cursor: disabled ? "not-allowed" : "pointer",
        fontWeight: primary || danger ? 500 : 400,
        transition: "opacity 0.1s",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {label}
    </button>
  );
}

/**
 * Form input field with label.
 * @param {{ label: string, id: string, value: string, onChange: Function, type?: string, required?: boolean, placeholder?: string }} props
 */
export function FormInput({
  label,
  id,
  value,
  onChange,
  type = "text",
  required,
  placeholder,
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label
        htmlFor={id}
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
        {label}
        {required && <span style={{ color: "#A32D2D", marginLeft: 2 }}>*</span>}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={onChange}
        required={required}
        placeholder={placeholder}
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
        }}
        onFocus={(e) => (e.target.style.borderColor = "#378ADD")}
        onBlur={(e) => (e.target.style.borderColor = "#C0C0C0")}
      />
    </div>
  );
}

/**
 * Form select field with label.
 * @param {{ label: string, id: string, value: string, onChange: Function, options: string[], required?: boolean }} props
 */
export function FormSelect({ label, id, value, onChange, options, required }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label
        htmlFor={id}
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
        {label}
        {required && <span style={{ color: "#A32D2D", marginLeft: 2 }}>*</span>}
      </label>
      <select
        id={id}
        value={value}
        onChange={onChange}
        required={required}
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
        }}
      >
        <option value="">— Select —</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Form error banner — shown when a mutation fails.
 * @param {{ message: string }} props
 */
export function FormError({ message }) {
  if (!message) return null;
  return (
    <div
      style={{
        padding: "8px 12px",
        background: "#FCEBEB",
        border: "1px solid #F09595",
        borderRadius: 8,
        fontSize: 12,
        color: "#791F1F",
        marginBottom: 12,
      }}
    >
      {message}
    </div>
  );
}
