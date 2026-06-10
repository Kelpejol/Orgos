// =============================================================================
// pages/ContractRegister/ContractForm.jsx — Create / edit contract
// =============================================================================

import { useState } from "react";
import { FormInput, FormSelect, FormError, Btn } from "../../components/shared/Forms.jsx";
import { useCreateContract, useUpdateContract } from "../../hooks/useGrc.js";
import OwnerField from "../../components/shared/OwnerField.jsx";

const CONTRACT_TYPES     = ["Client", "Vendor", "Partner", "Employment", "NDA", "Other"];
const LIFECYCLE_STATUSES = ["Active", "Under Review", "Terminated", "Superseded"];
const STANDARDS          = ["ISO 9001", "ISO 27001", "NDPA", "Internal"];

export default function ContractForm({ initial, onSuccess, onCancel }) {
  const isEdit = !!initial?.id;
  const create = useCreateContract();
  const update = useUpdateContract();

  const [form, setForm] = useState({
    contract_reference:   initial?.contract_reference   || "",
    title:                initial?.title                || "",
    counterparty:         initial?.counterparty         || "",
    contract_type:        initial?.contract_type        || "",
    owner_id:             initial?.owner?.oid           || "",
    start_date:           initial?.start_date           || "",
    end_date:             initial?.end_date             || "",
    renewal_notice_date:  initial?.renewal_notice_date  || "",
    review_date:          initial?.review_date          || "",
    notice_period_days:   initial?.notice_period_days   != null ? String(initial.notice_period_days) : "",
    auto_renewal:         initial?.auto_renewal         ?? false,
    lifecycle_status:     initial?.lifecycle_status     || "Active",
    applicable_standards: initial?.applicable_standards || [],
    sharepoint_url:       initial?.sharepoint_url       || "",
    source_document_code: initial?.source_document_code || "",
    notes:                initial?.notes               || "",
  });

  const set = (field) => (e) =>
    setForm((f) => ({ ...f, [field]: e.target.value }));

  const toggleStd = (std) =>
    setForm((f) => ({
      ...f,
      applicable_standards: f.applicable_standards.includes(std)
        ? f.applicable_standards.filter((s) => s !== std)
        : [...f.applicable_standards, std],
    }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    const payload = {
      ...form,
      notice_period_days: form.notice_period_days ? parseInt(form.notice_period_days, 10) : null,
      start_date:          form.start_date || null,
      end_date:            form.end_date   || null,
      renewal_notice_date: form.renewal_notice_date || null,
      review_date:         form.review_date || null,
      sharepoint_url:      form.sharepoint_url || null,
      source_document_code: form.source_document_code || null,
      notes:               form.notes || null,
    };
    try {
      if (isEdit) {
        await update.mutateAsync({ id: initial.id, updates: payload });
      } else {
        await create.mutateAsync(payload);
      }
      onSuccess();
    } catch { /* shown via mutation.error */ }
  };

  const mutation  = isEdit ? update : create;
  const isPending = mutation.isPending;

  return (
    <div style={{ maxWidth: 560 }}>
      <button
        onClick={onCancel}
        style={{ fontSize: 12, color: "var(--color-text-info)", background: "none", border: "none", cursor: "pointer", padding: 0, marginBottom: 14 }}>
        ← Cancel
      </button>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 18 }}>
        {isEdit ? "Edit contract" : "Add contract record"}
      </div>

      {mutation.error && <FormError message={mutation.error.message} />}

      <form onSubmit={handleSubmit}>
        {/* Core identification */}
        <FormInput
          label="Reference code"
          id="ref"
          value={form.contract_reference}
          onChange={set("contract_reference")}
          required
          placeholder="BGV-MTN-2027"
        />
        <FormInput
          label="Title / description"
          id="title"
          value={form.title}
          onChange={set("title")}
          required
        />
        <FormInput
          label="Counterparty"
          id="cp"
          value={form.counterparty}
          onChange={set("counterparty")}
          required
        />
        <FormSelect
          label="Contract type"
          id="type"
          value={form.contract_type}
          onChange={set("contract_type")}
          options={CONTRACT_TYPES}
          required
        />

        <OwnerField
          initialOid={form.owner_id}
          onResolve={(oid) => setForm((f) => ({ ...f, owner_id: oid }))}
        />

        {/* Dates */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>
              Start date
            </label>
            <input
              type="date"
              value={form.start_date}
              onChange={set("start_date")}
              style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", fontSize: 13, borderRadius: 8, border: "1.5px solid #C0C0C0", background: "var(--color-background-secondary)", color: "var(--color-text-primary)" }}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>
              Expiry date
            </label>
            <input
              type="date"
              value={form.end_date}
              onChange={set("end_date")}
              style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", fontSize: 13, borderRadius: 8, border: "1.5px solid #C0C0C0", background: "var(--color-background-secondary)", color: "var(--color-text-primary)" }}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>
              Renewal notice deadline
            </label>
            <input
              type="date"
              value={form.renewal_notice_date}
              onChange={set("renewal_notice_date")}
              style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", fontSize: 13, borderRadius: 8, border: "1.5px solid #C0C0C0", background: "var(--color-background-secondary)", color: "var(--color-text-primary)" }}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>
              Review date
            </label>
            <input
              type="date"
              value={form.review_date}
              onChange={set("review_date")}
              style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", fontSize: 13, borderRadius: 8, border: "1.5px solid #C0C0C0", background: "var(--color-background-secondary)", color: "var(--color-text-primary)" }}
            />
          </div>
        </div>

        {/* Renewal settings */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>
              Notice period (days)
            </label>
            <input
              type="number"
              min="0"
              value={form.notice_period_days}
              onChange={set("notice_period_days")}
              placeholder="e.g. 90"
              style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", fontSize: 13, borderRadius: 8, border: "1.5px solid #C0C0C0", background: "var(--color-background-secondary)", color: "var(--color-text-primary)" }}
            />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, paddingTop: 22 }}>
            <input
              type="checkbox"
              id="auto_renewal"
              checked={form.auto_renewal}
              onChange={(e) => setForm((f) => ({ ...f, auto_renewal: e.target.checked }))}
              style={{ width: 16, height: 16, cursor: "pointer" }}
            />
            <label htmlFor="auto_renewal" style={{ fontSize: 13, cursor: "pointer" }}>
              Auto-renews unless cancelled
            </label>
          </div>
        </div>

        {/* Lifecycle status */}
        {isEdit && (
          <FormSelect
            label="Lifecycle status"
            id="lifecycle"
            value={form.lifecycle_status}
            onChange={set("lifecycle_status")}
            options={LIFECYCLE_STATUSES}
          />
        )}

        {/* Applicable standards */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", marginBottom: 6 }}>
            Applicable standards
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {STANDARDS.map((std) => (
              <label key={std} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 13, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={form.applicable_standards.includes(std)}
                  onChange={() => toggleStd(std)}
                />
                {std}
              </label>
            ))}
          </div>
        </div>

        {/* Traceability */}
        <FormInput
          label="SharePoint file URL (optional)"
          id="sp_url"
          value={form.sharepoint_url}
          onChange={set("sharepoint_url")}
          placeholder="https://…"
        />
        <FormInput
          label="Source document code (optional)"
          id="src_doc"
          value={form.source_document_code}
          onChange={set("source_document_code")}
          placeholder="DRG-ISMS-POL-…"
        />

        <div style={{ marginBottom: 16 }}>
          <label
            htmlFor="notes"
            style={{ display: "block", fontSize: 12, fontWeight: 500, color: "var(--color-text-secondary)", marginBottom: 4 }}>
            Notes (optional)
          </label>
          <textarea
            id="notes"
            value={form.notes}
            onChange={set("notes")}
            placeholder="Key terms, obligations, or context…"
            rows={3}
            style={{
              width: "100%", boxSizing: "border-box", padding: "10px 12px",
              fontSize: 13, border: "1.5px solid #C0C0C0", borderRadius: 8,
              resize: "vertical", background: "var(--color-background-secondary)",
              color: "var(--color-text-primary)",
            }}
          />
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <Btn
            label={isPending ? "Saving…" : isEdit ? "Save changes" : "Add contract"}
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
