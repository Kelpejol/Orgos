// =============================================================================
// authConfig.js — Microsoft Authentication Library (MSAL) configuration
// Configures Entra ID login for the React frontend.
// All Dragnet staff sign in with their Microsoft 365 account.
// Depends on: @azure/msal-browser, .env.local
// =============================================================================

import { LogLevel } from "@azure/msal-browser";

/**
 * MSAL configuration object.
 * VITE_ prefixed env vars are injected at build time by Vite.
 * They MUST be set in frontend/.env.local before running npm run dev.
 */
export const msalConfig = {
  auth: {
    clientId: import.meta.env.VITE_AZURE_CLIENT_ID,
    authority: `https://login.microsoftonline.com/${import.meta.env.VITE_AZURE_TENANT_ID}`,
    redirectUri: import.meta.env.VITE_AZURE_REDIRECT_URI || window.location.origin,
    postLogoutRedirectUri: window.location.origin,
    navigateToLoginRequestUrl: true,
  },
  cache: {
    // sessionStorage: cleared when browser tab closes (safer for shared machines)
    // localStorage: persists across tabs (better UX for personal machines)
    cacheLocation: "sessionStorage",
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii) return; // Never log PII
        if (import.meta.env.DEV) {
          switch (level) {
            case LogLevel.Error:
              console.error("[MSAL]", message);
              break;
            case LogLevel.Warning:
              console.warn("[MSAL]", message);
              break;
            case LogLevel.Info:
              console.info("[MSAL]", message);
              break;
          }
        }
      },
    },
  },
};

/**
 * Scopes to request when acquiring an access token for the OrgOS API.
 * The API scope must match the scope exposed in the OrgOS app registration.
 * Format: api://{CLIENT_ID}/scope_name
 */

export const apiTokenRequest = {
  scopes: [
    `api://${import.meta.env.VITE_AZURE_CLIENT_ID}/OrgOS.ReadWrite`,
  ],
};

// export const apiTokenRequest = {
//   scopes: [
//     `https://graph.microsoft.com/User.Read`,
//   ],
// };

/**
 * Scopes for reading the user's profile from Microsoft Graph.
 * Used to display the user's name and email in the TopBar.
 */
export const graphTokenRequest = {
  scopes: ["User.Read"],
};

/**
 * Login request — scopes requested at initial login.
 * Combines API access + profile read in one consent prompt.
 */
// export const loginRequest = {
//   scopes: [
//     "openid",
//     "profile",
//     "email",
//     "User.Read",
//   ],
// };

export const loginRequest = {
  scopes: [
    "openid",
    "profile", 
    "email",
    `api://${import.meta.env.VITE_AZURE_CLIENT_ID}/OrgOS.ReadWrite`,
  ],
};
