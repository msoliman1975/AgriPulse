import { setEffectiveGrants } from "@/rbac/effectiveGrants";

import { apiClient } from "./client";

// Mirrors backend/app/modules/iam/schemas.py::MeResponse exactly. Keep
// the two in lock-step until we generate the client from OpenAPI.

export interface UserPreferences {
  language: string;
  numerals: string;
  unit_system: string;
  timezone: string;
  date_format: string;
  notification_channels: string[];
}

export interface TenantRole {
  role: string;
  granted_at: string;
}

export interface TenantMembership {
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  /** Arabic org name. Null when nobody wrote one — fall back to tenant_name. */
  tenant_name_ar: string | null;
  status: string;
  joined_at: string | null;
  tenant_roles: TenantRole[];
}

export interface FarmScope {
  farm_id: string;
  role: string;
  granted_at: string;
}

export interface PlatformRole {
  role: string;
  granted_at: string;
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  full_name_ar: string | null;
  phone: string | null;
  avatar_url: string | null;
  status: string;
  last_login_at: string | null;
  preferences: UserPreferences;
  platform_roles: PlatformRole[];
  tenant_memberships: TenantMembership[];
  farm_scopes: FarmScope[];
  /**
   * role -> the capabilities it grants right now, for this user's roles only.
   * Includes any runtime override a Platform Admin has applied, which is why
   * `useCapability` prefers this over the bundled mirror in `rbac/capabilities.ts`.
   * A wildcard role arrives as the literal `["*"]`. Absent on an older API.
   */
  capabilities?: Record<string, string[]>;
}

export async function fetchMe(): Promise<Me> {
  const { data } = await apiClient.get<Me>("/v1/me");
  // Published here rather than from a component: this is the only place /v1/me
  // is fetched, so every response — including react-query's background
  // refetches — keeps the capability resolver current. A Platform Admin's
  // change therefore reaches an open tab on its next /me refetch instead of
  // waiting for a redeploy.
  setEffectiveGrants(data.capabilities);
  return data;
}
