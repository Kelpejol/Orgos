import assert from "node:assert/strict";
import test from "node:test";
import { controlLine, dueForMe, dueText } from "../src/components/shared/recordDue.js";

const TODAY = "2026-11-13";
const rec = (id, State, NextDue, more = {}) => ({ id, IsObligation: true, State, NextDue, OwnedByMe: true, ...more });

test("due for me: only my records to produce, overdue first, then by due date", () => {
  const list = dueForMe([
    rec("soon", "Due soon", "2026-11-20"),
    rec("first", "Awaiting first record", "2026-11-30"),
    rec("late", "Late", "2026-11-01"),
    rec("ok", "Current", "2027-01-01"),
    rec("sent", "Submitted", "2026-11-20"),
    rec("unsched", "Unscheduled", ""),
    rec("theirs", "Late", "2026-10-01", { OwnedByMe: false }),
    rec("missing", "Missing", "2026-10-15"),
  ], TODAY);
  assert.deepEqual(list.map((r) => r.id), ["missing", "late", "soon", "first"]);
});

test("older one-per-control rows are judged by status and due date", () => {
  const old = { id: "o", IsObligation: false, Status: "Pending", NextDue: "2026-11-01", OwnedByMe: true };
  assert.equal(dueForMe([old], TODAY).length, 1);
  assert.equal(dueText(old, TODAY), "Was due 1 Nov 2026");
});

test("how a due record is described", () => {
  assert.equal(dueText(rec("a", "Due soon", "2026-12-13"), TODAY), "Due 13 Dec 2026");
  assert.equal(dueText(rec("a", "Rejected", ""), TODAY), "Rejected — submit it again");
  assert.equal(controlLine({ ControlName: "Context analysis runs quarterly", RecordDescription: "X" }), "Context analysis runs quarterly");
  assert.equal(controlLine({ ControlName: "", RecordDescription: "Context Analysis Record" }), "Context Analysis Record");
});
