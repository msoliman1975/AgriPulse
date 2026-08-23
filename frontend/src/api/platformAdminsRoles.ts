import { apiClient } from "./client";

export type PlatformRole = "PlatformAdmin" | "PlatformSupport";

export interface PlatformAdminRow {
  user_id: string;
  email: string;
  full_name: string | null;
  keycloak_subject: string | null;
  role: PlatformRole;
  granted_at: string;
  granted_by: string | null;
  // Whether this person gets the platform-alert email digest. A delivery
  // preference on the role grant, not a capability - nothing about it is
  // in the JWT.
  receives_alert_emails: boolean;
}

export interface InvitePlatformAdminPayload {
  email: string;
  full_name: string;
  role: PlatformRole;
}

export interface InvitePlatformAdminResponse {
  user_id: string;
  keycloak_subject: string | null;
  keycloak_provisioning: "succeeded" | "pending";
  role: PlatformRole;
  keycloak_email_sent: boolean;
  temporary_password: string | null;
}

const base = "/v1/admin/platform-admins";

export async function listPlatformAdmins(): Promise<PlatformAdminRow[]> {
  const { data } = await apiClient.get<PlatformAdminRow[]>(base);
  return data;
}

export async function invitePlatformAdmin(
  payload: InvitePlatformAdminPayload,
): Promise<InvitePlatformAdminResponse> {
  const { data } = await apiClient.post<InvitePlatformAdminResponse>(`${base}:invite`, payload);
  return data;
}

export async function retryPlatformAdminProvisioning(
  userId: string,
  role: PlatformRole,
): Promise<InvitePlatformAdminResponse> {
  const { data } = await apiClient.post<InvitePlatformAdminResponse>(
    `${base}/${userId}:retry-provisioning`,
    null,
    { params: { role } },
  );
  return data;
}

export async function removePlatformAdmin(userId: string, role: PlatformRole): Promise<void> {
  await apiClient.delete(`${base}/${userId}`, { params: { role } });
}

export interface AlertEmailsResponse {
  user_id: string;
  role: PlatformRole;
  receives_alert_emails: boolean;
}

export async function setPlatformAdminAlertEmails(
  userId: string,
  role: PlatformRole,
  enabled: boolean,
): Promise<AlertEmailsResponse> {
  const { data } = await apiClient.patch<AlertEmailsResponse>(`${base}/${userId}/alert-emails`, {
    role,
    enabled,
  });
  return data;
}
