// =============================================================================
// pages/DocumentRegister/DocumentForm.jsx
// Form for registering a new approved document.
// Rule: Only approved documents enter this register (Document Lifecycle enforces this).
// =============================================================================

import { useState } from "react";
import { FormInput, FormSelect, FormError, Btn } from "../../components/shared/Forms.jsx";
import { useCreateDocument } from "../../hooks/useGrc.js";
import OwnerField from "../../components/shared/OwnerField.jsx";

const DOC_TYPES = ["Policy", "Procedure", "SOP", "Form", "Guidelines"];
const STANDARDS = ["ISO 9001", "ISO 27001", "NDPA", "Internal"];
const DEPARTMENTS = ["QI", "ISMS", "HR", "Finance", "Software Dev", "Cloud Infra", "IT Support", "Executive", "Operations"];

export default function DocumentForm({ onSuccess, onCancel }) {
  const createDoc = useCreateDocument();
  const [form, setForm] = useState({
    document_code: "",
    title: "",
    type: "",
    department: "",
    current_version: "R01",
    effective_date: "",
    next_review_date: "",
    owner_id: "",
    applicable_standards: [],
    status: "Active",
  });

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const toggleStandard = (std) => {
    setForm((f) => ({
      ...f,
      applicable_standards: f.applicable_standards.includes(std)
        ? f.applicable_standards.filter((s) => s !== std)
        : [...f.applicable_standards, std],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await createDoc.mutateAsync(form);
      onSuccess();
    } catch {
      // error displayed via createDoc.error
    }
  };

  return (
    <div style={{ maxWidth: 520 }}>
      <button
        onClick={onCancel}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}
      >
        ← Cancel
      </button>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>
        Register approved document
      </div>

      <div style={{ padding: "10px 14px", background: "#FAEEDA", borderRadius: 8, marginBottom: 16, fontSize: 12, color: "#633806" }}>
        Only approved documents belong in this register.
        Drafts go through the Document Lifecycle (Tier 2).
      </div>

      {createDoc.error && <FormError message={createDoc.error.message} />}

      <form onSubmit={handleSubmit}>
        <FormInput label="Document code" id="doc_code" value={form.document_code}
          onChange={set("document_code")} required
          placeholder="DRG-[DEPT]-[TYPE]-[REF]-[YY]" />
        <FormInput label="Title" id="title" value={form.title}
          onChange={set("title")} required />
        <FormSelect label="Type" id="type" value={form.type}
          onChange={set("type")} options={DOC_TYPES} required />
        <FormSelect label="Department" id="dept" value={form.department}
          onChange={set("department")} options={DEPARTMENTS} required />
        <FormInput label="Version" id="version" value={form.current_version}
          onChange={set("current_version")} required placeholder="R01" />
        <FormInput label="Effective date" id="eff_date" value={form.effective_date}
          onChange={set("effective_date")} type="date" required />
        <FormInput label="Next review date" id="rev_date" value={form.next_review_date}
          onChange={set("next_review_date")} type="date" />
       <OwnerField onResolve={(oid) => setForm(f => ({ ...f, owner_id: oid }))} />

        {/* Standards multi-select */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.4px" }}>
            Applicable standards
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {STANDARDS.map((std) => (
              <label key={std} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={form.applicable_standards.includes(std)}
                  onChange={() => toggleStandard(std)}
                />
                {std}
              </label>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Btn label={createDoc.isPending ? "Registering..." : "Register document"}
            primary type="submit" disabled={createDoc.isPending} />
          <Btn label="Cancel" onClick={onCancel} />
        </div>
      </form>
    </div>
  );
}
