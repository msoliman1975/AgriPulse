import { useMemo, useSyncExternalStore } from "react";
import { useAuth } from "react-oidc-context";

import {
  getEffectiveGrants,
  subscribeToEffectiveGrants,
  type EffectiveGrants,
} from "./effectiveGrants";
import { decodeJwt, type JwtClaims } from "./jwt";
import { roleGrants, type Capability } from "./capabilities";

export interface CapabilityScope {
  farmId?: string;
}

export function useClaims(): JwtClaims | null {
  const auth = useAuth();
  return useMemo(() => decodeJwt(auth.user?.access_token), [auth.user?.access_token]);
}

/**
 * Live grants from `/v1/me`, or `null` before the first response.
 *
 * The roles themselves still come from the JWT — only the role -> capability
 * mapping is served. That split matters: a token is reissued on sign-in, but
 * the *policy* it resolves against can change under a running session, so the
 * two have different lifetimes and only one of them can be cached in a token.
 */
export function useServedGrants(): EffectiveGrants | null {
  return useSyncExternalStore(
    subscribeToEffectiveGrants,
    getEffectiveGrants,
    // Server snapshot: SSR and the first client render agree on "not loaded
    // yet", so the bundled mirror answers and hydration does not mismatch.
    () => null,
  );
}

function grantedBy(role: string, capability: Capability, served: EffectiveGrants | null): boolean {
  const caps = served?.[role];
  // Fall back to the compiled-in mirror only when the server has not answered
  // for this role. An empty array is a real answer — "this role grants
  // nothing" — and must not silently reopen the bundled defaults.
  if (caps === undefined) return roleGrants(role, capability);
  return caps.includes("*") || caps.includes(capability);
}

export function hasCapability(
  claims: JwtClaims | null,
  capability: Capability,
  scope: CapabilityScope = {},
  served: EffectiveGrants | null = null,
): boolean {
  if (!claims) return false;
  // Resolution order matches the backend: platform -> tenant -> farm scope,
  // first match wins. See backend/app/shared/rbac/check.py.
  if (claims.platform_role && grantedBy(claims.platform_role, capability, served)) {
    return true;
  }
  if (claims.tenant_role && grantedBy(claims.tenant_role, capability, served)) {
    return true;
  }
  if (scope.farmId && claims.farm_scopes) {
    for (const fs of claims.farm_scopes) {
      if (fs.farm_id === scope.farmId && grantedBy(fs.role, capability, served)) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Capability gate. Returns `true` when the current session grants the
 * capability — at the tenant level, or for `farmId` if provided.
 *
 * Resolves against the effective matrix served by `/v1/me`, falling back to
 * the bundled mirror until that arrives. The fallback is why this is safe to
 * call during first paint and why existing tests, which never fetch `/me`,
 * behave exactly as they did before.
 */
export function useCapability(capability: Capability, scope: CapabilityScope = {}): boolean {
  const claims = useClaims();
  const served = useServedGrants();
  const farmId = scope.farmId;
  return useMemo(
    () => hasCapability(claims, capability, { farmId }, served),
    [claims, capability, farmId, served],
  );
}
