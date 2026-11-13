import assert from "node:assert/strict";
import test from "node:test";
import { describeEvery, groupUnscheduled } from "../src/components/shared/recordSchedule.js";

test("a schedule in words", () => {
  assert.equal(describeEvery(91), "every quarter");
  assert.equal(describeEvery(30), "every month");
  assert.equal(describeEvery(10), "every 10 days");
  assert.equal(describeEvery(0), "on no schedule");
});

test("accepted controls with unscheduled records, one entry per control", () => {
  const controls = [{ id: "3", ControlId: "ICX-002", ControlName: "Each issue is classified", ControlDocument: "Strategic Context Procedure" },
                    { id: "1", ControlId: "ICX-001", ControlName: "Context analysis runs" }];
  const records = [
    { IsObligation: true, State: "Unscheduled", LinkedControlId: "ICX-002", RecordDescription: "Context Analysis Record" },
    { IsObligation: true, State: "Unscheduled", LinkedControlId: "ICX-002", RecordDescription: "Context Analysis Record" },
    { IsObligation: true, State: "Awaiting first record", LinkedControlId: "ICX-001", RecordDescription: "X" },
    { IsObligation: true, State: "Unscheduled", LinkedControlId: "GONE-1", RecordDescription: "Y" },
  ];
  assert.deepEqual(groupUnscheduled(records, controls), [{
    controlRowId: "3", controlId: "ICX-002", controlName: "Each issue is classified",
    document: "Strategic Context Procedure", records: ["Context Analysis Record"],
  }]);
});
