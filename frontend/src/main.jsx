// =============================================================================
// main.jsx — React application entry point
// Wraps the app in:
//   1. MsalProvider — enables MSAL auth hooks throughout the app
//   2. QueryClientProvider — enables React Query hooks throughout the app
// The msalInstance is exported so grcApi.js can call acquireTokenSilent.
// =============================================================================

import React from "react";
import ReactDOM from "react-dom/client";
import { PublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { msalConfig } from "./authConfig.js";
import App from "./App.jsx";
import "./index.css";

// Singleton MSAL instance — exported so grcApi.js can acquire tokens
export const msalInstance = new PublicClientApplication(msalConfig);

// Initialise MSAL before rendering (handles redirect callbacks)
await msalInstance.initialize();

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

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <MsalProvider instance={msalInstance}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MsalProvider>
  </React.StrictMode>
);
