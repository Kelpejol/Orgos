// =============================================================================
// components/shared/recordSchedule.js — record schedules in words, and which controls lack one
// Pure, so it is tested (tests/recordSchedule.test.mjs).
// =============================================================================

export const SCHEDULE_PRESETS = [["Monthly", 30], ["Quarterly", 91], ["Every six months", 182], ["Annually", 365]];

const NAMED = { 1: "every day", 7: "every week", 14: "every two weeks", 30: "every month",
                91: "every quarter", 182: "every six months", 365: "every year" };

/** 91 → "every quarter", 10 → "every 10 days". */
export function describeEvery(days) {
  const d = Number(days) || 0;
  if (!d) return "on no schedule";
  return NAMED[d] || `every ${d} days`;
}

/**
 * Accepted controls whose records are Unscheduled, one entry per control:
 * { controlRowId, controlId, controlName, document, records: [record names] }.
 * A control whose row can't be found is left out (it can't be saved against).
 */
export function groupUnscheduled(records, controls) {
  const rowFor = new Map((controls || []).filter((c) => c.ControlId).map((c) => [c.ControlId, c]));
  const out = new Map();
  for (const r of records || []) {
    if (!r.IsObligation || r.State !== "Unscheduled") continue;
    const control = rowFor.get(r.LinkedControlId);
    if (!control) continue;
    const g = out.get(control.id) || {
      controlRowId: control.id, controlId: control.ControlId,
      controlName: control.ControlName || r.ControlName || control.ControlId,
      document: control.ControlDocument || r.ControlDocument || "", records: [],
    };
    const name = r.RecordDescription || r.RecordId;
    if (name && !g.records.includes(name)) g.records.push(name);
    out.set(control.id, g);
  }
  return [...out.values()].sort((a, b) => a.controlName.localeCompare(b.controlName));
}
