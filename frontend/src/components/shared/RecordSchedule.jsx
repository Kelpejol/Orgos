// =============================================================================
// components/shared/RecordSchedule.jsx — how often a control's record is due
//
// The schedule comes from the control's document when it states one ("Every quarter").
// Where it is silent, Compliance chooses it in Extraction Review: when accepting the control
// (ScheduleChoice), or later for controls accepted without one (UnscheduledControls). It is
// never changed in the Record tracker. The record's clock starts once someone holds the
// Control owner role; the first record is due one period later. (13 Nov 2026)
// =============================================================================

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "../../api/grcApi.js";
import { describeEvery, groupUnscheduled, SCHEDULE_PRESETS } from "./recordSchedule.js";

const chip = (on) => ({
  padding: "5px 10px", fontSize: 11.5, borderRadius: 7, cursor: "pointer",
  border: `1.5px solid ${on ? "#0C447C" : "#C0C0C0"}`, background: on ? "#E6F1FB" : "transparent",
  color: on ? "#0C447C" : "var(--color-text-secondary)", fontWeight: on ? 600 : 400,
});

/** Pick a schedule: Monthly, Quarterly, Every six months, Annually, or a number of days. */
export function ScheduleSelect({ value, onChange }) {
  const preset = SCHEDULE_PRESETS.some(([, d]) => d === value);
  const [other, setOther] = useState(!preset && value > 0);
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
      {SCHEDULE_PRESETS.map(([label, days]) => (
        <button key={days} type="button" style={chip(!other && value === days)}
          onClick={() => { setOther(false); onChange(days); }}>{label}</button>
      ))}
      <button type="button" style={chip(other)} onClick={() => { setOther(true); onChange(0); }}>Other</button>
      {other && (
        <label style={{ fontSize: 11.5, display: "flex", alignItems: "center", gap: 5 }}>
          every
          <input type="number" min={1} max={3650} value={value || ""} onChange={(e) => onChange(Number(e.target.value) || 0)}
            style={{ width: 64, fontSize: 12, padding: "4px 6px", borderRadius: 6, border: "1.5px solid #C0C0C0" }} />
          days
        </label>
      )}
    </div>
  );
}

/**
 * In a control's accept panel: the schedule its document states, or a required choice.
 * `onChange(days)`; `days` is 0 until chosen. A changed control may keep its earlier schedule.
 */
export function ScheduleChoice({ item, days, onChange }) {
  const s = item.RecordSchedule || {};
  if (!s.names_record) return null;
  const box = { padding: "10px 12px", borderRadius: 8, marginBottom: 12, fontSize: 11.5, lineHeight: 1.5 };
  if (s.document_days) {
    return (
      <div style={{ ...box, background: "var(--color-background-secondary)", border: "0.5px solid var(--color-border-tertiary)" }}>
        <strong>Record due {describeEvery(s.document_days)}</strong>, as its document says (“{s.document_words}”).
        The first is due one period after someone holds the Control owner role.
      </div>
    );
  }
  const changed = item.ChangeKind === "Changed";
  return (
    <div style={{ ...box, background: days ? "#F4F9FE" : "#FAEEDA", border: `0.5px solid ${days ? "#85B7EB" : "#FAC775"}` }}>
      <div style={{ fontWeight: 600, marginBottom: 6, color: days ? "#0C447C" : "#633806" }}>
        How often is its record due?{!changed && " (required)"}
      </div>
      <div style={{ color: "var(--color-text-secondary)", marginBottom: 8 }}>
        The document states no schedule for this control's record, so you set it.
        {changed && " Leave it unchosen to keep the schedule set before."}
      </div>
      <ScheduleSelect value={days} onChange={onChange} />
    </div>
  );
}

/** Whether accepting `item` is waiting for a schedule to be chosen. */
export const needsScheduleChoice = (item, days) => {
  const s = item.RecordSchedule || {};
  return Boolean(s.names_record && !s.document_days && !days && item.ChangeKind !== "Changed");
};

/** Controls already accepted whose records have no schedule (the document is silent). */
export function UnscheduledControls() {
  const qc = useQueryClient();
  const records = useQuery({ queryKey: ["records", "unscheduled"],
    queryFn: () => apiClient.get("/api/v1/records").then((r) => r.data || []), staleTime: 30_000 });
  const controls = useQuery({ queryKey: ["controls"],
    queryFn: () => apiClient.get("/api/v1/controls").then((r) => r.data || []), staleTime: 30_000 });
  const groups = useMemo(() => groupUnscheduled(records.data || [], controls.data || []),
                         [records.data, controls.data]);
  const [choice, setChoice] = useState({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState({});

  if (!groups.length) return null;

  const save = async (g) => {
    setBusy(g.controlRowId); setError((e) => ({ ...e, [g.controlRowId]: "" }));
    try {
      await apiClient.patch(`/api/v1/controls/${g.controlRowId}/record-schedule`, { days: choice[g.controlRowId] });
      await Promise.all([qc.invalidateQueries({ queryKey: ["records"] }), qc.invalidateQueries({ queryKey: ["controls"] })]);
    } catch (err) {
      setError((e) => ({ ...e, [g.controlRowId]: err.message || "Could not save the schedule." }));
    } finally {
      setBusy("");
    }
  };

  return (
    <div style={{ marginBottom: 14, padding: "12px 14px", borderRadius: 10, border: "1px solid #FAC775", background: "#FFFBF2" }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#633806", marginBottom: 2 }}>
        Set record schedules ({groups.length})
      </div>
      <div style={{ fontSize: 11.5, color: "var(--color-text-secondary)", marginBottom: 8 }}>
        These controls are accepted, but their documents state no schedule, so their records are never due.
        Set how often each is due. The first is due one period after someone holds the Control owner role.
      </div>
      {groups.map((g) => {
        const days = choice[g.controlRowId] || 0;
        return (
          <div key={g.controlRowId} style={{ padding: "8px 0", borderTop: "0.5px solid #F0DDB0" }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{g.controlName}</div>
            <div style={{ fontSize: 11.5, color: "var(--color-text-secondary)", marginBottom: 6 }}>
              Record: {g.records.join(", ")}{g.document && ` · ${g.document}`}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <ScheduleSelect value={days} onChange={(d) => setChoice((c) => ({ ...c, [g.controlRowId]: d }))} />
              <button disabled={!days || busy === g.controlRowId} onClick={() => save(g)}
                style={{ padding: "5px 12px", fontSize: 11.5, fontWeight: 600, borderRadius: 7, border: "none",
                         background: !days ? "#E8E8E8" : "#0C447C", color: !days ? "#999" : "#fff",
                         cursor: !days ? "not-allowed" : "pointer" }}>
                {busy === g.controlRowId ? "Saving…" : "Save"}
              </button>
            </div>
            {error[g.controlRowId] && <div style={{ fontSize: 11, color: "#791F1F", marginTop: 4 }}>{error[g.controlRowId]}</div>}
          </div>
        );
      })}
    </div>
  );
}
