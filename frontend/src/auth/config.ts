import type { AuthProviderProps } from "react-oidc-context";
import { WebStorageStateStore } from "oidc-client-ts";

// Read OIDC config from VITE_-prefixed env vars; see .env.example.
function readEnv(name: string, fallback?: string): string {
  const value = import.meta.env[name as keyof ImportMetaEnv] as string | undefined;
  if (value && value.length > 0) {
    return value;
  }
  if (fallback !== undefined) {
    return fallback;
  }
  throw new Error(`Missing required env var ${name}`);
}

export const oidcConfig: AuthProviderProps = {
  authority: readEnv("VITE_OIDC_AUTHORITY"),
  client_id: readEnv("VITE_OIDC_CLIENT_ID"),
  redirect_uri: readEnv("VITE_OIDC_REDIRECT_URI"),
  post_logout_redirect_uri: readEnv("VITE_OIDC_POST_LOGOUT_REDIRECT_URI"),
  scope: readEnv("VITE_OIDC_SCOPE", "openid profile email"),
  response_type: "code",
  // Tokens stay in memory (in-memory state store) per ARCHITECTURE.md
  // intent — no localStorage-of-access-token. Refresh state is persisted
  // to sessionStorage so a hard refresh keeps the user signed in within
  // the same tab without making the access token recoverable from disk.
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  // Silent renew via authorization-code refresh tokens.
  automaticSilentRenew: true,
  // Strip the `code` and `state` query params from the URL after
  // sign-in; otherwise a refresh re-runs the redirect flow.
  onSigninCallback: () => {
    window.history.replaceState({}, document.title, window.location.pathname);
  },
};
