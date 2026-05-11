// =============================================================================
// pages/ContractRegister/ContractForm.jsx
// =============================================================================

import { useState } from "react";
import { FormInput, FormSelect, FormError, Btn } from "../../components/shared/Forms.jsx";
import { useCreateContract } from "../../hooks/useGrc.js";
import OwnerField from "../../components/shared/OwnerField.jsx";

const TYPES = ["Client", "Vendor", "Partner", "Employment", "NDA", "Other"];
const STANDARDS = ["ISO 9001", "ISO 27001", "NDPA", "Internal"];

export default function ContractForm({ onSuccess, onCancel }) {
  const create = useCreateContract();
  const [form, setForm] = useState({
    contract_reference: "",
    title: "",
    counterparty: "",
    contract_type: "",
    owner_id: "",
    start_date: "",
    end_date: "",
    review_date: "",
    applicable_standards: [],
  });

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));
  const toggleStd = (std) => setForm((f) => ({
    ...f,
    applicable_standards: f.applicable_standards.includes(std)
      ? f.applicable_standards.filter((s) => s !== std)
      : [...f.applicable_standards, std],
  }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await create.mutateAsync(form);
      onSuccess();
    } catch { /* shown via create.error */ }
  };

  return (
    <div style={{ maxWidth: 480 }}>
      <button onClick={onCancel}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}>
        ← Cancel
      </button>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Add contract record</div>

      {create.error && <FormError message={create.error.message} />}

      <form onSubmit={handleSubmit}>
        <FormInput label="Reference code" id="ref" value={form.contract_reference}
          onChange={set("contract_reference")} required placeholder="BGV-MTN-2027" />
        <FormInput label="Title" id="title" value={form.title}
          onChange={set("title")} required />
        <FormInput label="Counterparty" id="cp" value={form.counterparty}
          onChange={set("counterparty")} required />
        <FormSelect label="Type" id="type" value={form.contract_type}
          onChange={set("contract_type")} options={TYPES} required />
        <OwnerField onResolve={(oid) => setForm(f => ({ ...f, owner_id: oid }))} />
        <FormInput label="Start date" id="start" value={form.start_date}
          onChange={set("start_date")} type="date" />
        <FormInput label="Expiry date" id="end" value={form.end_date}
          onChange={set("end_date")} type="date" />
        <FormInput label="Review date" id="review" value={form.review_date}
          onChange={set("review_date")} type="date" />

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.4px" }}>
            Applicable standards
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {STANDARDS.map((std) => (
              <label key={std} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, cursor: "pointer" }}>
                <input type="checkbox" checked={form.applicable_standards.includes(std)}
                  onChange={() => toggleStd(std)} />
                {std}
              </label>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Btn label={create.isPending ? "Saving..." : "Save contract"} primary type="submit"
            disabled={create.isPending} />
          <Btn label="Cancel" onClick={onCancel} />
        </div>
      </form>
    </div>
  );
}
