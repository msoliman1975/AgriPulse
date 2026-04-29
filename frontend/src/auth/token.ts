// Single source of truth for the current access token. Set by AuthSync
// (mounted under <AuthProvider>) whenever the OIDC user changes; read by
// the axios request interceptor in src/api/client.ts.
//
// We intentionally do not pass the token through React context for the
// API layer — interceptors fire from non-component code, and React-side
// re-render for token swaps would invalidate every cached query.

let currentAccessToken: string | null = null;
let signInRedirectHandler: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  currentAccessToken = token;
}

export function getAccessToken(): string | null {
  return currentAccessToken;
}

export function setSignInRedirect(handler: (() => void) | null): void {
  signInRedirectHandler = handler;
}

export function triggerSignInRedirect(): void {
  signInRedirectHandler?.();
}
