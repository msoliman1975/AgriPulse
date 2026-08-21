// Mirrors backend/app/modules/iam/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export interface UserPreferences {
  language: string;
  numerals: string;
  unit_system: string;
  timezone: string;
  date_format: string;
  notification_channels: string[];
}

/**
 * Which handle actually identifies this person. Field workers sign in with a
 * phone number and carry a synthetic, undeliverable address, so `email` must
 * not be shown or written to for them. Use `displayUser` rather than reading
 * this at each call site.
 */
export type IdentityKind = "email" | "phone";

export interface TenantUser {
  id: string;
  email: string;
  identity_kind: IdentityKind;
  full_name: string;
  phone: string | null;
  avatar_url: string | null;
  status: string;
  last_login_at: string | null;
  keycloak_subject: string | null;
  membership_id: string;
  membership_status: string;
  joined_at: string | null;
  tenant_roles: string[];
  /**
   * Farm-tier roles, one entry per farm. A member holds either this or
   * `tenant_roles`, never both, so a reader that looks only at
   * `tenant_roles` shows every farm-tier member as having no role.
   * Farm names are not included — join them against the farms list.
   */
  farm_roles: FarmRoleGrant[];
  preferences: UserPreferences | null;
}

/** One active row of `public.farm_scopes`. */
export interface FarmRoleGrant {
  farm_id: string;
  role: string;
}

export interface UserInvitePayload {
  email: string;
  full_name: string;
  phone?: string | null;
  /** Any role in `ASSIGNABLE_ROLES`. Platform roles are refused with a 422. */
  role: string;
  /** Required and non-empty for a farm-tier role; must be empty otherwise. */
  farm_ids?: string[];
}

export interface UserRoleAssignPayload {
  role: string;
  farm_ids?: string[];
}

/** What the change took away, so the caller can say what was replaced. */
export interface RevokedRoles {
  tenant_roles: string[];
  farm_roles: FarmRoleGrant[];
}

export interface UserRoleAssignResponse {
  membership_id: string;
  role: string;
  role_tier: "tenant" | "farm";
  farm_ids: string[];
  revoked: RevokedRoles;
}

export interface UserInviteResponse {
  user_id: string;
  membership_id: string;
  keycloak_provisioning: "succeeded" | "pending";
  keycloak_subject: string | null;
  // IH-2: when no welcome email was sent, temporary_password carries a
  // one-time credential to hand off (SMTP-free onboarding).
  keycloak_email_sent: boolean;
  temporary_password: string | null;
}

export interface UserResendInviteResponse {
  keycloak_provisioning: "succeeded" | "pending";
  keycloak_email_sent: boolean;
  temporary_password: string | null;
}

export interface UserUpdatePayload {
  full_name?: string;
  phone?: string | null;
  avatar_url?: string | null;
  preferences?: Partial<UserPreferences>;
}

export async function listTenantUsers(): Promise<TenantUser[]> {
  const { data } = await apiClient.get<TenantUser[]>("/v1/users");
  return data;
}

export async function inviteTenantUser(payload: UserInvitePayload): Promise<UserInviteResponse> {
  const { data } = await apiClient.post<UserInviteResponse>("/v1/users:invite", payload);
  return data;
}

export async function updateTenantUser(userId: string, payload: UserUpdatePayload): Promise<void> {
  await apiClient.patch(`/v1/users/${userId}`, payload);
}

/**
 * Replace a member's role. The server revokes whatever they held first —
 * roles do not stack, so this is a set, not an add.
 */
export async function assignTenantUserRole(
  userId: string,
  payload: UserRoleAssignPayload,
): Promise<UserRoleAssignResponse> {
  const { data } = await apiClient.put<UserRoleAssignResponse>(`/v1/users/${userId}/role`, payload);
  return data;
}

export async function suspendTenantUser(userId: string): Promise<void> {
  await apiClient.post(`/v1/users/${userId}:suspend`);
}

export async function reactivateTenantUser(userId: string): Promise<void> {
  await apiClient.post(`/v1/users/${userId}:reactivate`);
}

export async function deleteTenantUser(userId: string): Promise<void> {
  await apiClient.delete(`/v1/users/${userId}`);
}

export async function resendTenantUserInvite(userId: string): Promise<UserResendInviteResponse> {
  const { data } = await apiClient.post<UserResendInviteResponse>(
    `/v1/users/${userId}:resend-invite`,
  );
  return data;
}
