// =============================================================================
// auth/session.js — keeping the ERP sign-in alive without "Unable to load data"
//
// The erp_auth cookie is an Entra ID token the ERP issues; it lasts about an hour and OrgOS
// cannot extend it. When it runs out, the ERP issues a new one on a round trip through the
// ERP shell (what a page reload used to do, by hand). So:
//
//   • a little before it runs out, if the tab is in the background or the person comes back
//     to it, OrgOS renews it straight away (nothing is being typed at that moment);
//   • while the person is looking at the page, a banner offers "Renew now" instead of
//     taking the page away from them;
//   • when the server says the sign-in has ended (a 401 marked X-OrgOS-Session), OrgOS renews
//     at once, unless the person is typing in a field: then it asks first, so nothing typed
//     is lost without warning.
//
// A renewal returns to the same page. A renewal that keeps coming back with the same expired
// sign-in is stopped after a few tries, with a message, rather than bouncing for ever.
// =============================================================================

// How to reach the ERP shell; main.jsx passes authBridge's redirectToShell. (Not imported here
// so these rules can be tested without a browser build.)
let goToShell = () => { throw new Error("configureSession() was not called"); };
export function configureSession({ redirect }) {
  goToShell = redirect;
}

export const SESSION_HEADER = "x-orgos-session";
export const RENEW_BEFORE_MS = 3 * 60 * 1000;     // renew this long before the sign-in ends

const BOUNCES_KEY = "orgos.signInRenewals";
const RENEWED_FOR_KEY = "orgos.renewedForExpiry";
const MAX_BOUNCES = 3;
const BOUNCE_WINDOW_MS = 2 * 60 * 1000;

const listeners = new Set();
let ended = false;

function store() {
  try { return window.sessionStorage; } catch { return null; }
}

/** Is this response the server saying the person's sign-in has ended? */
export function isSessionEnded(status, headerValue) {
  return status === 401 && String(headerValue || "").toLowerCase() === "ended";
}

export function sessionHasEnded() {
  return ended;
}

export function onSessionEnded(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function reportSessionEnded() {
  if (ended) return;
  ended = true;
  listeners.forEach((fn) => fn());
}

/** Renewals in the last couple of minutes; more than a few means the ERP is not renewing. */
export function recentRenewals(now = Date.now(), raw = store()?.getItem(BOUNCES_KEY)) {
  try {
    return (JSON.parse(raw || "[]") || []).filter((t) => now - t < BOUNCE_WINDOW_MS);
  } catch {
    return [];
  }
}

export function canRenew(now = Date.now()) {
  return recentRenewals(now).length < MAX_BOUNCES;
}

/** Go through the ERP for a fresh sign-in and come back to this page. */
export function renewSignIn() {
  const now = Date.now();
  const s = store();
  if (!canRenew(now)) return false;
  try { s?.setItem(BOUNCES_KEY, JSON.stringify([...recentRenewals(now), now])); } catch { /* private mode */ }
  goToShell();
  return true;
}

/**
 * Whether to renew ahead of time for a sign-in that ends at `expiresOn` — once per sign-in:
 * if the ERP hands back the same one, OrgOS waits for it to end instead of asking again.
 */
export function dueForEarlyRenewal(expiresOn, now = Date.now(), renewedFor = store()?.getItem(RENEWED_FOR_KEY)) {
  if (!expiresOn) return false;                                  // no expiry known (development)
  if (String(renewedFor) === String(expiresOn)) return false;     // already tried for this one
  return now >= expiresOn - RENEW_BEFORE_MS;
}

export function renewEarly(expiresOn) {
  try { store()?.setItem(RENEWED_FOR_KEY, String(expiresOn)); } catch { /* private mode */ }
  return renewSignIn();
}

/** Is the person typing in a field right now (so a page change would cost them their text)? */
export function isTyping(doc = document) {
  const el = doc.activeElement;
  if (!el) return false;
  const tag = (el.tagName || "").toLowerCase();
  return tag === "textarea" || (tag === "input" && !["button", "checkbox", "radio", "submit"].includes(el.type))
    || el.isContentEditable === true;
}

// fetch() calls outside the API client (file previews, uploads) report an ended sign-in too.
let fetchWatched = false;
export function watchFetch() {
  if (fetchWatched || typeof window === "undefined" || !window.fetch) return;
  fetchWatched = true;
  const original = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const resp = await original(...args);
    if (isSessionEnded(resp.status, resp.headers?.get?.(SESSION_HEADER))) reportSessionEnded();
    return resp;
  };
}
