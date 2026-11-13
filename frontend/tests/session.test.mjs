import assert from "node:assert/strict";
import test from "node:test";
import {
  RENEW_BEFORE_MS, canRenew, dueForEarlyRenewal, isSessionEnded, isTyping, recentRenewals,
} from "../src/auth/session.js";

test("only a 401 marked by the server counts as an ended sign-in", () => {
  assert.equal(isSessionEnded(401, "ended"), true);
  assert.equal(isSessionEnded(401, undefined), false);      // e.g. a SharePoint failure passed on as 401
  assert.equal(isSessionEnded(403, "ended"), false);
  assert.equal(isSessionEnded(500, "ended"), false);
});

test("a sign-in is renewed early once, a few minutes before it ends", () => {
  const ends = 1_000_000_000;
  assert.equal(dueForEarlyRenewal(ends, ends - RENEW_BEFORE_MS - 1, null), false);
  assert.equal(dueForEarlyRenewal(ends, ends - RENEW_BEFORE_MS, null), true);
  assert.equal(dueForEarlyRenewal(ends, ends + 5, null), true);
  // the ERP handed back the same sign-in: wait for it to end rather than ask again
  assert.equal(dueForEarlyRenewal(ends, ends - 10, String(ends)), false);
  assert.equal(dueForEarlyRenewal(0, ends, null), false);             // no expiry known
});

test("renewals that keep bouncing are stopped", () => {
  const now = 10_000_000;
  const raw = (times) => JSON.stringify(times);
  assert.equal(recentRenewals(now, raw([now - 1000, now - 500_000])).length, 1);   // only the last two minutes count
  assert.equal(recentRenewals(now, "not json").length, 0);
  assert.equal(canRenew(now), true);
});

test("typing is a focused text field, not a button", () => {
  const doc = (el) => ({ activeElement: el });
  assert.equal(isTyping(doc({ tagName: "TEXTAREA" })), true);
  assert.equal(isTyping(doc({ tagName: "INPUT", type: "text" })), true);
  assert.equal(isTyping(doc({ tagName: "INPUT", type: "checkbox" })), false);
  assert.equal(isTyping(doc({ tagName: "BUTTON" })), false);
  assert.equal(isTyping(doc(null)), false);
});
