// =============================================================================
// pages/RoleRegister/RoleForm.jsx — Create a new role mapping
// =============================================================================

import { useState } from "react";
import { FormInput, FormSelect, FormError, Btn } from "../../components/shared/Forms.jsx";
import { useCreateRole } from "../../hooks/useGrc.js";
import OwnerField from "../../components/shared/OwnerField.jsx";

const DEPARTMENTS = ["QI", "ISMS", "HR", "Finance", "Software Dev", "Cloud Infra", "IT Support", "Executive", "Operations"];
const SOURCES = ["Entra ID", "SeamlessHR", "BitWiseFlow", "Manual"];

export default function RoleForm({ onSuccess, onCancel }) {
  const createRole = useCreateRole();
  const [form, setForm] = useState({
    role_title: "",
    department: "",
    jd_reference: "",
    current_holder_id: "",
    source_system: "Entra ID",
    variant_terms: "",
  });

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await createRole.mutateAsync(form);
      onSuccess();
    } catch { /* shown via createRole.error */ }
  };

  return (
    <div style={{ maxWidth: 480 }}>
      <button onClick={onCancel}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 12 }}>
        ← Cancel
      </button>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Add role mapping</div>

      {createRole.error && <FormError message={createRole.error.message} />}

      <form onSubmit={handleSubmit}>
        <FormInput label="Role title (canonical)" id="role_title" value={form.role_title}
          onChange={set("role_title")} required placeholder="e.g. ISMS Lead" />
        <FormSelect label="Department" id="dept" value={form.department}
          onChange={set("department")} options={DEPARTMENTS} required />
        <FormInput label="JD reference" id="jd_ref" value={form.jd_reference}
          onChange={set("jd_reference")} required placeholder="DRG-JD-ISMS-IL-01" />
        <OwnerField onResolve={(oid) => setForm(f => ({ ...f, current_holder_id: oid }))} />
        <FormSelect label="Source system" id="source" value={form.source_system}
          onChange={set("source_system")} options={SOURCES} />
        <FormInput label="Variant terms (optional)" id="variants" value={form.variant_terms}
          onChange={set("variant_terms")} placeholder="Line Manager, Department Head, ..." />

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Btn label={createRole.isPending ? "Saving..." : "Save role"} primary type="submit"
            disabled={createRole.isPending} />
          <Btn label="Cancel" onClick={onCancel} />
        </div>
      </form>
    </div>
  );
}
