import type { ReactNode } from "react";
import { AuthProvider as OidcAuthProvider } from "react-oidc-context";

import { oidcConfig } from "./config";

interface Props {
  children: ReactNode;
}

/**
 * Thin wrapper around react-oidc-context's provider. Exists so the rest
 * of the app imports a single named provider; swapping to a different
 * OIDC client later is a one-file change.
 */
export function AuthProvider({ children }: Props): ReactNode {
  return <OidcAuthProvider {...oidcConfig}>{children}</OidcAuthProvider>;
}
