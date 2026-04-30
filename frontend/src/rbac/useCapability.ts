import { useMemo } from "react";
import { useAuth } from "react-oidc-context";

import { decodeJwt, type JwtClaims } from "./jwt";
import { roleGrants, type Capability } from "./capabilities";

export interface CapabilityScope {
  farmId?: string;
}

export function useClaims(): JwtClaims | null {
  const auth = useAuth();
  return useMemo(() => decodeJwt(auth.user?.access_token), [auth.user?.access_token]);
}

export function hasCapability(
  claims: JwtClaims | null,
  capability: Capability,
  scope: CapabilityScope = {},
): boolean {
  if (!claims) return false;
  if (claims.platform_role && roleGrants(claims.platform_role, capability)) {
    return true;
  }
  if (claims.tenant_role && roleGrants(claims.tenant_role, capability)) {
    return true;
  }
  if (scope.farmId && claims.farm_scopes) {
    for (const fs of claims.farm_scopes) {
      if (fs.farm_id === scope.farmId && roleGrants(fs.role, capability)) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Capability gate. Returns `true` when the current JWT grants the
 * capability — at the tenant level, or for `farmId` if provided.
 */
export function useCapability(capability: Capability, scope: CapabilityScope = {}): boolean {
  const claims = useClaims();
  const farmId = scope.farmId;
  return useMemo(() => hasCapability(claims, capability, { farmId }), [claims, capability, farmId]);
}
