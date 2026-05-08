// Mirrors backend/app/modules/tenancy/schemas.py — keep in lock-step.
// All endpoints sit at `/api/v1/admin/tenants/*` and require the
// `platform.manage_tenants` capability.

import { apiClient } from "./client";

export type TenantStatus =
  | "active"
  | "suspended"
  | "pending_delete"
  | "pending_provision"
  | "archived";

export type TenantTier = "free" | "standard" | "premium" | "enterprise";

export interface AdminTenant {
  id: string;
  slug: string;
  name: string;
  legal_name: string | null;
  tax_id: string | null;
  contact_email: string;
  contact_phone: string | null;
  schema_name: string;
  status: TenantStatus;
  default_locale: string;
  default_unit_system: string;
  default_timezone: string;
  default_currency: string;
  country_code: string;
  suspended_at: string | null;
  deleted_at: string | null;
  last_status_reason: string | null;
  purge_eligible_at: string | null;
  keycloak_group_id: string | null;
  pending_owner_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminTenantList {
  items: AdminTenant[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminTenantSettings {
  cloud_cover_threshold_visualization_pct: number;
  cloud_cover_threshold_analysis_pct: number;
  imagery_refresh_cadence_hours: number;
  alert_notification_channels: string[];
  webhook_endpoint_url: string | null;
  dashboard_default_indices: string[];
}

export interface AdminTenantSubscription {
  id: string;
  tier: TenantTier;
  plan_type: string | null;
  started_at: string;
  expires_at: string | null;
  is_current: boolean;
  trial_start: string | null;
  trial_end: string | null;
  feature_flags: Record<string, unknown>;
}

export interface AdminTenantArchiveEvent {
  id: string;
  occurred_at: string;
  event_type: string;
  actor_user_id: string | null;
  actor_kind: string;
  details: Record<string, unknown>;
  correlation_id: string | null;
}

export interface AdminTenantSidecar {
  tenant_id: string;
  settings: AdminTenantSettings | null;
  subscription: AdminTenantSubscription | null;
  active_member_count: number;
  recent_events: AdminTenantArchiveEvent[];
}

export interface AdminTenantMeta {
  statuses: TenantStatus[];
  tiers: TenantTier[];
  locales: string[];
  unit_systems: string[];
  purge_grace_days: number;
}

export interface ListAdminTenantsParams {
  status?: TenantStatus;
  search?: string;
  include_deleted?: boolean;
  limit?: number;
  offset?: number;
}

export interface CreateAdminTenantPayload {
  slug: string;
  name: string;
  contact_email: string;
  legal_name?: string | null;
  tax_id?: string | null;
  contact_phone?: string | null;
  default_locale?: "en" | "ar";
  default_unit_system?: "feddan" | "acre" | "hectare";
  initial_tier?: TenantTier;
  owner_email?: string | null;
  owner_full_name?: string | null;
}

export interface CreateAdminTenantResponse {
  id: string;
  slug: string;
  name: string;
  schema_name: string;
  contact_email: string;
  default_locale: string;
  default_unit_system: string;
  status: TenantStatus;
  created_at: string;
  provisioning_failed: boolean;
  owner_user_id: string | null;
}

export async function listAdminTenants(
  params: ListAdminTenantsParams = {},
): Promise<AdminTenantList> {
  const { data } = await apiClient.get<AdminTenantList>("/v1/admin/tenants", {
    params,
  });
  return data;
}

export async function getAdminTenant(tenantId: string): Promise<AdminTenant> {
  const { data } = await apiClient.get<AdminTenant>(`/v1/admin/tenants/${tenantId}`);
  return data;
}

export async function getAdminTenantSidecar(
  tenantId: string,
  auditLimit = 20,
): Promise<AdminTenantSidecar> {
  const { data } = await apiClient.get<AdminTenantSidecar>(
    `/v1/admin/tenants/${tenantId}/sidecar`,
    { params: { audit_limit: auditLimit } },
  );
  return data;
}

export async function getAdminTenantMeta(): Promise<AdminTenantMeta> {
  const { data } = await apiClient.get<AdminTenantMeta>("/v1/admin/tenants/_meta");
  return data;
}

export async function createAdminTenant(
  payload: CreateAdminTenantPayload,
): Promise<CreateAdminTenantResponse> {
  const { data } = await apiClient.post<CreateAdminTenantResponse>(
    "/v1/admin/tenants",
    payload,
  );
  return data;
}

export async function suspendAdminTenant(
  tenantId: string,
  reason: string | null,
): Promise<AdminTenant> {
  const { data } = await apiClient.post<AdminTenant>(
    `/v1/admin/tenants/${tenantId}/suspend`,
    { reason },
  );
  return data;
}

export async function reactivateAdminTenant(tenantId: string): Promise<AdminTenant> {
  const { data } = await apiClient.post<AdminTenant>(
    `/v1/admin/tenants/${tenantId}/reactivate`,
    {},
  );
  return data;
}

export async function requestDeleteAdminTenant(
  tenantId: string,
  reason: string | null,
): Promise<AdminTenant> {
  const { data } = await apiClient.post<AdminTenant>(
    `/v1/admin/tenants/${tenantId}/delete`,
    { reason },
  );
  return data;
}

export async function cancelDeleteAdminTenant(tenantId: string): Promise<AdminTenant> {
  const { data } = await apiClient.post<AdminTenant>(
    `/v1/admin/tenants/${tenantId}/cancel-delete`,
    {},
  );
  return data;
}

export interface PurgeAdminTenantPayload {
  slug_confirmation: string;
  force?: boolean;
}

export async function purgeAdminTenant(
  tenantId: string,
  payload: PurgeAdminTenantPayload,
): Promise<void> {
  await apiClient.post(`/v1/admin/tenants/${tenantId}/purge`, payload);
}

export async function retryProvisioningAdminTenant(
  tenantId: string,
): Promise<AdminTenant> {
  const { data } = await apiClient.post<AdminTenant>(
    `/v1/admin/tenants/${tenantId}/retry-provisioning`,
    {},
  );
  return data;
}
