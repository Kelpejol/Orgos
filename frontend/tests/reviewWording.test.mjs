import assert from "node:assert/strict";
import test from "node:test";
import { reviewOutcomeLabel } from "../src/components/shared/reviewWording.js";

test("accepted outcomes describe the result without repeating the action", () => {
  assert.equal(reviewOutcomeLabel("Accepted", "Accept"), "Accepted");
  assert.equal(reviewOutcomeLabel("Accepted", "Edit and Accept"), "Accepted after edits");
  assert.equal(reviewOutcomeLabel("Accepted", ""), "Accepted");
});

test("other outcomes retain their stored status and decision wording", () => {
  assert.equal(reviewOutcomeLabel("Rejected", "Reject"), "Rejected — Reject");
  assert.equal(reviewOutcomeLabel("Pending Second Review", "Request Second Review"),
    "Pending Second Review — Request Second Review");
  assert.equal(reviewOutcomeLabel("False Positive", "Mark False Positive"),
    "False Positive — Mark False Positive");
  assert.equal(reviewOutcomeLabel("Pending Review", ""), "Pending Review");
  assert.equal(reviewOutcomeLabel("", "Accept"), "Accept");
  assert.equal(reviewOutcomeLabel(undefined, undefined), "");
});
