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

export interface TenantUser {
  id: string;
  email: string;
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
  preferences: UserPreferences | null;
}

export interface UserInvitePayload {
  email: string;
  full_name: string;
  phone?: string | null;
  tenant_role: string;
}

export interface UserInviteResponse {
  user_id: string;
  membership_id: string;
  keycloak_provisioning: "succeeded" | "pending";
  keycloak_subject: string | null;
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

export async function suspendTenantUser(userId: string): Promise<void> {
  await apiClient.post(`/v1/users/${userId}:suspend`);
}

export async function reactivateTenantUser(userId: string): Promise<void> {
  await apiClient.post(`/v1/users/${userId}:reactivate`);
}

export async function deleteTenantUser(userId: string): Promise<void> {
  await apiClient.delete(`/v1/users/${userId}`);
}
