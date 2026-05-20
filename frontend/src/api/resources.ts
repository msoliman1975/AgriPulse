// Mirrors backend/app/modules/resources/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export type ResourceKind = "worker" | "equipment";
export type WorkerRole =
  | "agronomist"
  | "operator"
  | "scout"
  | "field_worker"
  | "manager";
export type EquipmentType =
  | "tractor"
  | "sprayer"
  | "irrigation_pump"
  | "harvester"
  | "other";

export interface Resource {
  id: string;
  farm_id: string;
  kind: ResourceKind;
  name: string;
  role: WorkerRole | null;
  equipment_type: EquipmentType | null;
  phone: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResourceCreatePayload {
  kind: ResourceKind;
  name: string;
  role?: WorkerRole | null;
  equipment_type?: EquipmentType | null;
  phone?: string | null;
}

export interface ResourceUpdatePayload {
  name?: string;
  role?: WorkerRole | null;
  equipment_type?: EquipmentType | null;
  phone?: string | null;
  archive?: boolean;
}

export async function listResources(
  farmId: string,
  options: { kind?: ResourceKind; include_archived?: boolean } = {},
): Promise<Resource[]> {
  const { data } = await apiClient.get<Resource[]>(
    `/v1/farms/${farmId}/resources`,
    { params: options },
  );
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
  const { data } = await apiClient.post<Resource>(
    `/v1/farms/${farmId}/resources`,
    payload,
  );
  return data;
}

export async function updateResource(
  resourceId: string,
  payload: ResourceUpdatePayload,
): Promise<Resource> {
  const { data } = await apiClient.patch<Resource>(
    `/v1/resources/${resourceId}`,
    payload,
  );
  return data;
}

export async function attachResource(
  activityId: string,
  resourceId: string,
): Promise<Resource> {
  const { data } = await apiClient.post<Resource>(
    `/v1/activities/${activityId}/resources/${resourceId}`,
  );
  return data;
}

export async function detachResource(
  activityId: string,
  resourceId: string,
): Promise<void> {
  await apiClient.delete(`/v1/activities/${activityId}/resources/${resourceId}`);
}
