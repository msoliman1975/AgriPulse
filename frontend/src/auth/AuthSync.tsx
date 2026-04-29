import { useEffect } from "react";
import { useAuth } from "react-oidc-context";

import { setAccessToken, setSignInRedirect } from "./token";

/**
 * Bridges the OIDC user state into the non-React token registry that
 * the axios interceptor reads. Mount once below <AuthProvider>.
 */
export function AuthSync(): null {
  const auth = useAuth();

  useEffect(() => {
    setAccessToken(auth.user?.access_token ?? null);
  }, [auth.user]);

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
