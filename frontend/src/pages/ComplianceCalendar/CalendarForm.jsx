// =============================================================================
// pages/ComplianceCalendar/CalendarForm.jsx — Create / edit obligation
// =============================================================================

import { useState } from "react";
import { FormInput, FormSelect, FormError, Btn } from "../../components/shared/Forms.jsx";
import { useCreateObligation, useUpdateObligation } from "../../hooks/useGrc.js";
import OwnerField from "../../components/shared/OwnerField.jsx";

const TYPES       = ["Statutory", "Licensing", "Certification", "Regulatory"];
const RECURRENCES = ["Monthly", "Quarterly", "Annual", "Once"];

export default function CalendarForm({ initial, onSuccess, onCancel }) {
  const isEdit = !!initial?.id;
  const create = useCreateObligation();
  const update = useUpdateObligation();

  const [form, setForm] = useState({
    obligation_name:      initial?.obligation_name      || "",
    type:                 initial?.type                 || "",
    authority:            initial?.authority             || "",
    due_date:             initial?.due_date              || "",
    recurrence:           initial?.recurrence            || "",
    owner_id:             initial?.owner?.oid            || "",
    source_document_code: initial?.source_document_code || "",
    notes:                initial?.notes                || "",
  });

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      if (isEdit) {
        await update.mutateAsync({ id: initial.id, updates: form });
      } else {
        await create.mutateAsync(form);
      }
      onSuccess();
    } catch { /* errors shown via mutation.error */ }
  };

  const mutation  = isEdit ? update : create;
  const isPending = mutation.isPending;

  return (
    <div style={{ maxWidth: 500 }}>
      <button
        onClick={onCancel}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 14 }}>
        ← Cancel
      </button>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 16 }}>
        {isEdit ? "Edit obligation" : "Add compliance obligation"}
      </div>

      <div style={{
        padding: "10px 14px", background: "var(--color-background-secondary)",
        borderRadius: 8, marginBottom: 16, fontSize: 12, color: "var(--color-text-secondary)",
      }}>
        Status (Overdue / Due Soon / Upcoming) is calculated automatically from the due date — no manual selection needed.
      </div>

      {mutation.error && <FormError message={mutation.error.message} />}

      <form onSubmit={handleSubmit}>
        <FormInput
          label="Obligation name"
          id="name"
          value={form.obligation_name}
          onChange={set("obligation_name")}
          required
          placeholder="e.g. PAYE Remittance, ISO Surveillance Audit"
        />
        <FormSelect
          label="Type"
          id="type"
          value={form.type}
          onChange={set("type")}
          options={TYPES}
          required
        />
        <FormInput
          label="Authority"
          id="auth"
          value={form.authority}
          onChange={set("authority")}
          required
          placeholder="LIRS, FIRS, PenCom, NDPC, Cert Body…"
        />
        <FormInput
          label="Due date"
          id="due"
          value={form.due_date}
          onChange={set("due_date")}
          type="date"
          required
        />
        <FormSelect
          label="Recurrence"
          id="rec"
          value={form.recurrence}
          onChange={set("recurrence")}
          options={RECURRENCES}
          required
        />

        <OwnerField
          initialOid={form.owner_id}
          onResolve={(oid) => setForm((f) => ({ ...f, owner_id: oid }))}
        />

        <FormInput
          label="Source document code (optional)"
          id="src_doc"
          value={form.source_document_code}
          onChange={set("source_document_code")}
          placeholder="DRG-ISMS-POL-…"
        />

        <div style={{ marginBottom: 14 }}>
          <label
            htmlFor="notes"
            style={{ display: "block", fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", marginBottom: 4 }}>
            Notes (optional)
          </label>
          <textarea
            id="notes"
            value={form.notes}
            onChange={set("notes")}
            placeholder="Penalty information, context, or external reference…"
            rows={3}
            style={{
              width: "100%", boxSizing: "border-box", padding: "10px 12px",
              fontSize: 13, border: "1.5px solid #C0C0C0", borderRadius: 8,
              resize: "vertical", background: "var(--color-background-secondary)",
              color: "var(--color-text-primary)",
            }}
          />
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          <Btn
            label={isPending ? "Saving…" : isEdit ? "Save changes" : "Add obligation"}
            primary
            type="submit"
            disabled={isPending}
          />
          <Btn label="Cancel" onClick={onCancel} />
        </div>
      </form>
    </div>
  );
}
