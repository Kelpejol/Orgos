// =============================================================================
// pages/DocumentRegister/DocumentForm.jsx
// Form for registering a new approved document.
// Rule: Only approved documents enter this register (Document Lifecycle enforces this).
// =============================================================================

import { useState } from "react";
import { FormInput, FormSelect, FormError, Btn } from "../../components/shared/Forms.jsx";
import { useCreateDocument, useUpdateDocument } from "../../hooks/useGrc.js";
import OwnerField from "../../components/shared/OwnerField.jsx";

const DOC_TYPES = ["Policy", "Procedure", "SOP", "Form", "Guidelines"];
const STANDARDS = ["ISO 9001", "ISO 27001", "NDPA", "Internal"];
const DEPARTMENTS = ["QI", "ISMS", "HR", "Finance", "Software Dev", "Cloud Infra", "IT Support", "Executive", "Operations"];

function normalizeStandards(value) {
  const raw = Array.isArray(value) ? value : String(value || "").split(/[;,]/);
  const result = [];
  const seen = new Set();
  for (const item of raw) {
    const standard = String(item).trim();
    if (standard && !seen.has(standard)) {
      result.push(standard);
      seen.add(standard);
    }
  }
  return result;
}

export default function DocumentForm({ document, onSuccess, onCancel }) {
  const isEdit = !!document;
  const createDoc = useCreateDocument();
  const updateDoc = useUpdateDocument();
  const [form, setForm] = useState({
    document_code: document?.document_code || "",
    title: document?.title || "",
    type: document?.type || "",
    department: document?.department || "",
    current_version: document?.current_version || "R01",
    effective_date: document?.effective_date || "",
    next_review_date: document?.next_review_date || "",
    owner_id: "",
    applicable_standards: normalizeStandards(document?.applicable_standards),
    status: document?.status || "Active",
  });

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const mutation = isEdit ? updateDoc : createDoc;

  const toggleStandard = (std) => {
    setForm((f) => ({
      ...f,
      applicable_standards: normalizeStandards(f.applicable_standards).includes(std)
        ? normalizeStandards(f.applicable_standards).filter((s) => s !== std)
        : [...normalizeStandards(f.applicable_standards), std],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const payload = { ...form };
      if (!payload.next_review_date) delete payload.next_review_date;
      if (!payload.owner_id) delete payload.owner_id;

      if (isEdit) {
        await updateDoc.mutateAsync({ id: document.id, updates: payload });
      } else {
        await createDoc.mutateAsync(payload);
      }
      onSuccess();
    } catch {
      // error displayed via mutation.error
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
        {isEdit ? "Edit document register entry" : "Register approved document"}
      </div>

      <div style={{ padding: "10px 14px", background: "#FAEEDA", borderRadius: 8, marginBottom: 16, fontSize: 12, color: "#633806" }}>
        Only approved documents belong in this register.
        Drafts go through the Document Lifecycle (Tier 2).
      </div>

      {mutation.error && <FormError message={mutation.error.message} />}

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
       {isEdit && (
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: -6, marginBottom: 12 }}>
            Leave owner unchanged unless you resolve a new Microsoft 365 owner above.
          </div>
        )}

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
          <Btn label={mutation.isPending ? "Saving..." : isEdit ? "Save changes" : "Register document"}
            primary type="submit" disabled={mutation.isPending} />
          <Btn label="Cancel" onClick={onCancel} />
        </div>
      </form>
    </div>
  );
}
