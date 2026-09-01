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
import { verifySession, redirectToShell } from "./auth/authBridge.js";
import { AuthProvider } from "./context/AuthContext.jsx";
import App from "./App.jsx";
import "./index.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// React Query client — global configuration
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retry failed queries twice before showing an error
      retry: 2,
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

async function bootstrap() {
  const auth = await verifySession();

  if (!auth) {
    redirectToShell();
    return; // browser is navigating away — never render
  }

  ReactDOM.createRoot(document.getElementById("root")).render(
    <React.StrictMode>
      <AuthProvider
        user={{ name: auth.name, email: auth.email, oid: auth.oid }}
        roles={auth.roles}
        refreshToken={async () => {
          // Session expired mid-use — clear it and send the user back to the
          // ERP shell for a fresh one.
          await fetch(`${API_BASE}/api/auth/session`, {
            method: "DELETE",
            credentials: "include",
          });
          redirectToShell();
        }}
      >
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
