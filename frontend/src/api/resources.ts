// Mirrors backend/app/modules/resources/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export type ResourceKind = "worker" | "equipment";
// U-2: canonical role vocabulary shared with IAM per-farm roles (FarmRole).
// FarmManager / Agronomist / FieldOperator / Scout mirror FarmRole exactly;
// FieldWorker is the worker-only extra (generic labour, no login).
export type WorkerRole = "FarmManager" | "Agronomist" | "FieldOperator" | "Scout" | "FieldWorker";
export type EquipmentType = "tractor" | "sprayer" | "irrigation_pump" | "harvester" | "other";

export interface Resource {
  id: string;
  /**
   * Gone from the API since tenant migration 0071 — a worker or machine
   * belongs to the tenant, not one farm. Kept optional only so a response
   * cached from an older build still parses.
   * @deprecated read `farm_ids`
   */
  farm_id?: string | null;
  /**
   * The farms this resource may be used on. Populated by the tenant-wide
   * roster (`GET /v1/resources`); empty on the per-farm list, where the farm
   * is already the question being asked.
   */
  farm_ids?: string[];
  kind: ResourceKind;
  name: string;
  /** Arabic display name. Null when nobody wrote one — fall back to `name`. */
  name_ar: string | null;
  role: WorkerRole | null;
  equipment_type: EquipmentType | null;
  phone: string | null;
  // U-3: optional link to a tenant member (membership_id). null = unlinked.
  membership_id: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResourceCreatePayload {
  kind: ResourceKind;
  name: string;
  name_ar?: string | null;
  role?: WorkerRole | null;
  equipment_type?: EquipmentType | null;
  phone?: string | null;
  membership_id?: string | null;
}

export interface ResourceUpdatePayload {
  name?: string;
  name_ar?: string | null;
  role?: WorkerRole | null;
  equipment_type?: EquipmentType | null;
  phone?: string | null;
  // Send a membership_id to link, or explicit null to unlink.
  membership_id?: string | null;
  archive?: boolean;
}

export async function listResources(
  farmId: string,
  options: { kind?: ResourceKind; include_archived?: boolean } = {},
): Promise<Resource[]> {
  const { data } = await apiClient.get<Resource[]>(`/v1/farms/${farmId}/resources`, {
    params: options,
  });
  return data;
}

export async function getResource(resourceId: string): Promise<Resource> {
  const { data } = await apiClient.get<Resource>(`/v1/resources/${resourceId}`);
  return data;
}

export async function createResource(
  farmId: string,
  payload: ResourceCreatePayload,
): Promise<Resource> {
  const { data } = await apiClient.post<Resource>(`/v1/farms/${farmId}/resources`, payload);
  return data;
}

export async function updateResource(
  resourceId: string,
  payload: ResourceUpdatePayload,
): Promise<Resource> {
  const { data } = await apiClient.patch<Resource>(`/v1/resources/${resourceId}`, payload);
  return data;
}

export async function attachResource(activityId: string, resourceId: string): Promise<Resource> {
  const { data } = await apiClient.post<Resource>(
    `/v1/activities/${activityId}/resources/${resourceId}`,
  );
  return data;
}

export async function detachResource(activityId: string, resourceId: string): Promise<void> {
  await apiClient.delete(`/v1/activities/${activityId}/resources/${resourceId}`);
}
