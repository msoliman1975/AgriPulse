import { apiClient } from "./client";

export type FarmMemberRole = "FarmManager" | "Agronomist" | "FieldOperator" | "Scout" | "Viewer";

export interface FarmMember {
  id: string;
  membership_id: string;
  farm_id: string;
  role: FarmMemberRole;
  granted_at: string;
  revoked_at: string | null;
}

export async function listFarmMembers(farmId: string): Promise<FarmMember[]> {
  const { data } = await apiClient.get<FarmMember[]>(`/v1/farms/${farmId}/members`);
  return data;
}

export async function assignFarmMember(
  farmId: string,
  membershipId: string,
  role: FarmMemberRole,
): Promise<FarmMember> {
  const { data } = await apiClient.post<FarmMember>(`/v1/farms/${farmId}/members`, {
    membership_id: membershipId,
    role,
  });
  return data;
}

export async function revokeFarmMember(farmId: string, farmScopeId: string): Promise<FarmMember> {
  const { data } = await apiClient.delete<FarmMember>(`/v1/farms/${farmId}/members/${farmScopeId}`);
  return data;
}
