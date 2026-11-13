// =============================================================================
// components/shared/recordDue.js — which records are due from me, and how to say it
// Shared by the Dashboard ("Due for me") and the Record Tracker. Pure, so it is tested.
// =============================================================================

// Something to produce now (overdue) or soon. "Current", "Submitted" and "Unscheduled" are not.
export const OVERDUE = new Set(["Missing", "Late", "Stale", "Rejected"]);
export const DUE = new Set([...OVERDUE, "Due soon", "Awaiting first record"]);

const isoDay = (value) => String(value || "").slice(0, 10);

function legacyState(r, today) {
  if (r.Status === "Rejected") return "Rejected";
  if (["Pending", "Due Soon", "Overdue"].includes(r.Status)) {
    const due = isoDay(r.NextDue);
    if (due && due < today) return "Late";
    return due ? "Due soon" : "";
  }
  return "";
}

/** The state that decides whether a record is due: an obligation's state, or an older row's. */
export function dueState(r, today = new Date().toISOString().slice(0, 10)) {
  return r.IsObligation ? r.State : legacyState(r, today);
}

/** My records to produce, overdue first, then by due date. */
export function dueForMe(records, today = new Date().toISOString().slice(0, 10)) {
  return (records || [])
    .filter((r) => r.OwnedByMe === true && DUE.has(dueState(r, today)))
    .sort((a, b) => {
      const oa = OVERDUE.has(dueState(a, today)) ? 0 : 1;
      const ob = OVERDUE.has(dueState(b, today)) ? 0 : 1;
      if (oa !== ob) return oa - ob;
      return (isoDay(a.NextDue) || "9999") < (isoDay(b.NextDue) || "9999") ? -1 : 1;
    });
}

export function formatDay(value) {
  const d = isoDay(value);
  if (!d) return "";
  const [y, m, day] = d.split("-").map(Number);
  return new Date(y, m - 1, day).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** "Was due 13 Nov 2026", "Due 13 Dec 2026", "Out of date", "Rejected — submit again". */
export function dueText(r, today = new Date().toISOString().slice(0, 10)) {
  const state = dueState(r, today);
  const when = formatDay(r.NextDue);
  if (state === "Rejected") return "Rejected — submit it again";
  if (state === "Stale") return "Out of date — submit a newer one";
  if (state === "Missing" || state === "Late") return when ? `Was due ${when}` : "Overdue";
  return when ? `Due ${when}` : "Due";
}

/** What the record proves, in words: the control (not its ID), else the record itself. */
export function controlLine(r) {
  return r.ControlName || r.RecordDescription || r.Title || "Record";
}
