// =============================================================================
// pages/ComplianceCalendar/CalendarForm.jsx
// =============================================================================

import { useState } from "react";
import { FormInput, FormSelect, FormError, Btn } from "../../components/shared/Forms.jsx";
import { useCreateObligation } from "../../hooks/useGrc.js";
import OwnerField from "../../components/shared/OwnerField.jsx";

const TYPES = ["Statutory", "Licensing", "Certification", "Regulatory"];
const RECURRENCES = ["Monthly", "Quarterly", "Annual", "Once"];

export default function CalendarForm({ onSuccess, onCancel }) {
  const create = useCreateObligation();
  const [form, setForm] = useState({
    obligation_name: "",
    type: "",
    authority: "",
    due_date: "",
    recurrence: "",
    owner_id: "",
  });

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

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
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Add compliance obligation</div>

      <div style={{ padding: "10px 14px", background: "var(--color-background-secondary)", borderRadius: 8, marginBottom: 14, fontSize: 12, color: "var(--color-text-secondary)" }}>
        Status (Overdue / Due Soon / Upcoming) is calculated automatically from the due date.
      </div>

      {create.error && <FormError message={create.error.message} />}

      <form onSubmit={handleSubmit}>
        <FormInput label="Obligation name" id="name" value={form.obligation_name}
          onChange={set("obligation_name")} required placeholder="e.g. PAYE Remittance" />
        <FormSelect label="Type" id="type" value={form.type}
          onChange={set("type")} options={TYPES} required />
        <FormInput label="Authority" id="auth" value={form.authority}
          onChange={set("authority")} required placeholder="LIRS, FIRS, PenCom, NDPC..." />
        <FormInput label="Due date" id="due" value={form.due_date}
          onChange={set("due_date")} type="date" required />
        <FormSelect label="Recurrence" id="rec" value={form.recurrence}
          onChange={set("recurrence")} options={RECURRENCES} required />
        <OwnerField onResolve={(oid) => setForm(f => ({ ...f, owner_id: oid }))} />

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Btn label={create.isPending ? "Saving..." : "Save obligation"} primary type="submit"
            disabled={create.isPending} />
          <Btn label="Cancel" onClick={onCancel} />
        </div>
      </form>
    </div>
  );
}
