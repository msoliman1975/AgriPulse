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
}

const base = "/v1/admin/platform-admins";

export async function listPlatformAdmins(): Promise<PlatformAdminRow[]> {
  const { data } = await apiClient.get<PlatformAdminRow[]>(base);
  return data;
}

export async function invitePlatformAdmin(
  payload: InvitePlatformAdminPayload,
): Promise<InvitePlatformAdminResponse> {
  const { data } = await apiClient.post<InvitePlatformAdminResponse>(
    `${base}:invite`,
    payload,
  );
  return data;
}

export async function removePlatformAdmin(
  userId: string,
  role: PlatformRole,
): Promise<void> {
  await apiClient.delete(`${base}/${userId}`, { params: { role } });
}
