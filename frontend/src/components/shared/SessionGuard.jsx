// =============================================================================
// components/shared/SessionGuard.jsx — renews the ERP sign-in before and when it ends
// (rules in auth/session.js). Shows a banner while there is still time, and asks first
// only when the person is typing.
// =============================================================================

import { useEffect, useState } from "react";
import { SHELL_URL } from "../../auth/authBridge.js";
import {
  RENEW_BEFORE_MS, dueForEarlyRenewal, isTyping, onSessionEnded, renewEarly, renewSignIn, sessionHasEnded,
} from "../../auth/session.js";

const panel = {
  position: "fixed", right: 16, bottom: 16, zIndex: 3000, maxWidth: 360, padding: "12px 14px",
  borderRadius: 10, background: "#fff", border: "1px solid #FAC775", boxShadow: "0 8px 30px rgba(0,0,0,0.18)",
  fontFamily: "system-ui, -apple-system, sans-serif", fontSize: 12.5, lineHeight: 1.5, color: "#1F1F1F",
};
const primary = {
  padding: "7px 12px", fontSize: 12, fontWeight: 600, borderRadius: 7, border: "none",
  background: "#0C447C", color: "#fff", cursor: "pointer",
};
const secondary = {
  padding: "7px 12px", fontSize: 12, borderRadius: 7, border: "1px solid #C0C0C0",
  background: "transparent", color: "#555", cursor: "pointer",
};

export default function SessionGuard({ expiresOn }) {
  const [state, setState] = useState("");   // "" | "soon" | "ended" | "stuck"

  const renew = (early) => {
    const going = early ? renewEarly(expiresOn) : renewSignIn();
    if (!going) setState("stuck");
  };

  useEffect(() => {
    // The server says the sign-in has ended: renew now, unless the person is typing.
    const stop = onSessionEnded(() => {
      if (document.hidden || !isTyping()) renew(false);
      else setState("ended");
    });

    // A little before it ends: renew if nobody is looking, otherwise offer it.
    let timer;
    if (expiresOn) {
      const wait = expiresOn - RENEW_BEFORE_MS - Date.now();
      const due = () => {
        if (!dueForEarlyRenewal(expiresOn)) return;
        if (document.hidden) renew(true);
        else setState((s) => s || "soon");
      };
      if (wait > 0) timer = setTimeout(due, Math.min(wait, 2 ** 31 - 1));
      else due();
    }

    // Coming back to the tab: nothing is being typed yet, so renew straight away if needed.
    const onVisible = () => {
      if (document.hidden) return;
      if (sessionHasEnded()) renew(false);
      else if (dueForEarlyRenewal(expiresOn)) renew(true);
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      stop();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [expiresOn]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (state === "soon") {
    return (
      <div role="status" style={panel}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Your sign-in ends in a few minutes</div>
        <div style={{ color: "#555", marginBottom: 10 }}>
          Renew it now so nothing stops working. Save anything you are typing first; you come back to this page.
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button style={primary} onClick={() => renew(true)}>Renew now</button>
          <button style={secondary} onClick={() => setState("")}>Later</button>
        </div>
      </div>
    );
  }
  if (state === "ended") {
    return (
      <div role="alertdialog" style={{ ...panel, borderColor: "#F09595" }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Your sign-in has ended</div>
        <div style={{ color: "#555", marginBottom: 10 }}>
          Copy anything you are typing, then sign in again. You come back to this page.
        </div>
        <button style={primary} onClick={() => renew(false)}>Sign in again</button>
      </div>
    );
  }
  if (state === "stuck") {
    return (
      <div role="alertdialog" style={{ ...panel, borderColor: "#F09595" }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>OrgOS could not renew your sign-in</div>
        <div style={{ color: "#555", marginBottom: 10 }}>
          Open the ERP and sign in there, then come back to this page and reload it.
        </div>
        {SHELL_URL && <a href={SHELL_URL} target="_blank" rel="noreferrer" style={{ ...primary, textDecoration: "none", display: "inline-block" }}>Open the ERP</a>}
      </div>
    );
  }
  return null;
}
