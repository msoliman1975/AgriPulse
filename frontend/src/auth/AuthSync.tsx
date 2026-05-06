import { useEffect } from "react";
import { useAuth } from "react-oidc-context";

import { setAccessToken, setSignInRedirect } from "./token";

/**
 * Bridges the OIDC user state into the non-React token registry that
 * the axios interceptor reads. Mount once below <AuthProvider>.
 *
 * The token is mirrored into the registry during render (not in an
 * effect) on purpose: child effects run before parent effects, so an
 * effect-based sync would race with the first API call from any child
 * mounted in the shell — the request would fly out without a Bearer
 * header, hit 401, and trigger a sign-in redirect loop. Writing the
 * registry during render is idempotent (same string on every render
 * for the same user) and safe in StrictMode.
 */
export function AuthSync(): null {
  const auth = useAuth();

  setAccessToken(auth.user?.access_token ?? null);

  useEffect(() => {
    setSignInRedirect(() => {
      // Only one outstanding redirect at a time; react-oidc-context
      // serialises this internally.
      void auth.signinRedirect();
    });
    return () => setSignInRedirect(null);
  }, [auth]);

  return null;
}
