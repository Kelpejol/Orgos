// =============================================================================
// main.jsx — React application entry point
// Standalone Dragnet ERP Tier-1 session resolution: verify the erp_auth
// cookie via OrgOS's own backend before ever rendering the app. No session →
// redirect to the ERP shell to authenticate; the shell bounces back here once
// it's set the cookie. No MSAL, no login page — see docs/ERP_Module-Tier_1.md.
// =============================================================================

import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { redirectToShell, verifySession } from "./auth/authBridge.js";
import { configureSession, renewSignIn, sessionHasEnded, watchFetch } from "./auth/session.js";
import { AuthProvider } from "./context/AuthContext.jsx";
import SessionGuard from "./components/shared/SessionGuard.jsx";
import App from "./App.jsx";
import "./index.css";

// React Query client — global configuration
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retry failed queries twice before showing an error — but not when the sign-in has
      // ended: SessionGuard is renewing it, and retrying only fills the screen with errors.
      retry: (count) => !sessionHasEnded() && count < 2,
      // Show stale data while refetching (better UX)
      staleTime: 30_000,
      // Don't refetch when window regains focus in development
      refetchOnWindowFocus: import.meta.env.PROD,
    },
    mutations: {
      // Don't retry mutations — let the user decide to retry
      retry: 0,
    },
  },
});

function cannotSignIn() {
  document.getElementById("root").innerHTML =
    '<div style="font-family:system-ui,sans-serif;max-width:440px;margin:80px auto;padding:0 16px;line-height:1.5">' +
    "<h2 style=\"font-size:18px\">OrgOS could not sign you in</h2>" +
    "<p>The ERP did not return a valid sign-in after several tries. Open the ERP, sign in there, " +
    "then reload this page.</p></div>";
}

async function bootstrap() {
  configureSession({ redirect: redirectToShell });
  watchFetch();
  const auth = await verifySession();

  if (!auth) {
    // Through the ERP for a sign-in, back to this page; stop if it keeps coming back without one.
    if (!renewSignIn()) cannotSignIn();
    return; // browser is navigating away — never render
  }

  ReactDOM.createRoot(document.getElementById("root")).render(
    <React.StrictMode>
      <AuthProvider
        user={{ name: auth.name, email: auth.email, oid: auth.oid }}
        roles={auth.roles}
        refreshToken={async () => { renewSignIn(); }}
      >
        <SessionGuard expiresOn={auth.expiresOn} />
        <BrowserRouter>
          <QueryClientProvider client={queryClient}>
            <App />
          </QueryClientProvider>
        </BrowserRouter>
      </AuthProvider>
    </React.StrictMode>
  );
}

bootstrap();
