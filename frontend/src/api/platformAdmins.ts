import { apiClient } from "./client";

export interface TenantAdminRow {
  user_id: string;
  email: string;
  full_name: string | null;
  membership_id: string;
  membership_status: string;
  role: "TenantOwner" | "TenantAdmin";
  granted_at: string;
}

export interface InviteAdminPayload {
  email: string;
  full_name: string;
}

export interface InviteAdminResponse {
  user_id: string;
  membership_id: string;
  keycloak_provisioning: "succeeded" | "pending";
  keycloak_subject: string | null;
}

const base = (tenantId: string): string =>
  `/v1/admin/tenants/${tenantId}/admins`;

export async function listTenantAdmins(tenantId: string): Promise<TenantAdminRow[]> {
  const { data } = await apiClient.get<TenantAdminRow[]>(base(tenantId));
  return data;
}

export async function inviteTenantAdmin(
  tenantId: string,
  payload: InviteAdminPayload,
): Promise<InviteAdminResponse> {
  const { data } = await apiClient.post<InviteAdminResponse>(
    `${base(tenantId)}:invite`,
    payload,
  );
  return data;
}

export async function removeTenantAdmin(
  tenantId: string,
  userId: string,
): Promise<void> {
  await apiClient.delete(`${base(tenantId)}/${userId}`);
}

export async function transferTenantOwnership(
  tenantId: string,
  newOwnerUserId: string,
  fromUserId: string,
): Promise<void> {
  await apiClient.post(
    `${base(tenantId)}/${newOwnerUserId}:transfer-ownership`,
    { from_user_id: fromUserId },
  );
}

export type AssignOwnerPayload =
  | { email: string; full_name: string }
  | { user_id: string };

export interface AssignOwnerResponse {
  user_id: string;
  membership_id: string;
  keycloak_provisioning: string;
  keycloak_subject: string | null;
  mode: "invite" | "promote";
}

export async function assignFirstOwner(
  tenantId: string,
  payload: AssignOwnerPayload,
): Promise<AssignOwnerResponse> {
  const { data } = await apiClient.post<AssignOwnerResponse>(
    `${base(tenantId)}:assign-owner`,
    payload,
  );
  return data;
}
