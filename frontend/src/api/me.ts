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
  phone: string | null;
  avatar_url: string | null;
  status: string;
  last_login_at: string | null;
  preferences: UserPreferences;
  platform_roles: PlatformRole[];
  tenant_memberships: TenantMembership[];
  farm_scopes: FarmScope[];
}

export async function fetchMe(): Promise<Me> {
  const { data } = await apiClient.get<Me>("/v1/me");
  return data;
}
