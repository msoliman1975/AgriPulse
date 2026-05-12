import type { MultiPolygon } from "geojson";
import { apiClient } from "./client";
import type { CursorPage } from "./pagination";

// Types mirror backend/app/modules/farms/schemas.py. Keep in lock-step.

export type FarmType = "commercial" | "research" | "contract";
export type OwnershipType = "owned" | "leased" | "partnership" | "other";
export type WaterSource = "well" | "canal" | "nile" | "desalinated" | "rainfed" | "mixed";
export type AreaUnitName = "feddan" | "acre" | "hectare";

export interface Farm {
  id: string;
  code: string;
  name: string;
  description: string | null;
  centroid: GeoJSON.Point;
  area_m2: number;
  area_value: number;
  area_unit: AreaUnitName;
  elevation_m: number | null;
  governorate: string | null;
  district: string | null;
  nearest_city: string | null;
  address_line: string | null;
  farm_type: FarmType;
  ownership_type: OwnershipType | null;
  primary_water_source: WaterSource | null;
  established_date: string | null;
  tags: string[];
  // Lifecycle replaces the old status enum.
  active_from: string; // ISO date
  active_to: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface FarmDetail extends Farm {
  boundary: MultiPolygon;
}

export interface FarmCreatePayload {
  code: string;
  name: string;
  description?: string | null;
  boundary: MultiPolygon;
  elevation_m?: number | null;
  governorate?: string | null;
  district?: string | null;
  nearest_city?: string | null;
  address_line?: string | null;
  farm_type?: FarmType;
  ownership_type?: OwnershipType | null;
  primary_water_source?: WaterSource | null;
  established_date?: string | null;
  tags?: string[];
  active_from?: string | null;
}

export interface FarmUpdatePayload {
  name?: string;
  description?: string | null;
  boundary?: MultiPolygon;
  elevation_m?: number | null;
  governorate?: string | null;
  district?: string | null;
  nearest_city?: string | null;
  address_line?: string | null;
  farm_type?: FarmType;
  ownership_type?: OwnershipType | null;
  primary_water_source?: WaterSource | null;
  established_date?: string | null;
  tags?: string[];
}

export interface FarmListParams {
  cursor?: string;
  limit?: number;
  governorate?: string;
  tag?: string;
  include_inactive?: boolean;
}

export interface FarmInactivationPreview {
  block_count: number;
  alerts_resolved: number;
  irrigation_skipped: number;
  plan_activities_skipped: number;
  weather_subs_deactivated: number;
  imagery_subs_deactivated: number;
}

export interface FarmInactivationResult extends FarmInactivationPreview {
  farm_id: string;
  active_to: string;
}

export interface FarmReactivationResult {
  farm_id: string;
  restored_block_count: number;
}

function normalizeFarm<T extends { area_m2: unknown; area_value: unknown }>(f: T): T {
  return { ...f, area_m2: Number(f.area_m2 ?? 0), area_value: Number(f.area_value ?? 0) };
}

export async function listFarms(params: FarmListParams = {}): Promise<CursorPage<Farm>> {
  const { data } = await apiClient.get<CursorPage<Farm>>("/v1/farms", { params });
  return { ...data, items: data.items.map(normalizeFarm) };
}

export async function getFarm(farmId: string): Promise<FarmDetail> {
  const { data } = await apiClient.get<FarmDetail>(`/v1/farms/${farmId}`);
  return normalizeFarm(data);
}

export async function createFarm(payload: FarmCreatePayload): Promise<FarmDetail> {
  const { data } = await apiClient.post<FarmDetail>("/v1/farms", payload);
  return normalizeFarm(data);
}

export async function updateFarm(farmId: string, payload: FarmUpdatePayload): Promise<FarmDetail> {
  const { data } = await apiClient.patch<FarmDetail>(`/v1/farms/${farmId}`, payload);
  return normalizeFarm(data);
}

export async function getFarmInactivationPreview(
  farmId: string,
): Promise<FarmInactivationPreview> {
  const { data } = await apiClient.get<FarmInactivationPreview>(
    `/v1/farms/${farmId}/inactivate-preview`,
  );
  return data;
}

export async function inactivateFarm(
  farmId: string,
  payload: { reason?: string | null } = {},
): Promise<FarmInactivationResult> {
  const { data } = await apiClient.post<FarmInactivationResult>(
    `/v1/farms/${farmId}/inactivate`,
    payload,
  );
  return data;
}

export async function reactivateFarm(
  farmId: string,
  payload: { restore_blocks?: boolean } = {},
): Promise<FarmReactivationResult> {
  const { data } = await apiClient.post<FarmReactivationResult>(
    `/v1/farms/${farmId}/reactivate`,
    payload,
  );
  return data;
}

// DELETE remains as an alias for backwards-compatibility callers; new code
// should use inactivateFarm directly.
export async function archiveFarm(farmId: string): Promise<FarmInactivationResult> {
  const { data } = await apiClient.delete<FarmInactivationResult>(`/v1/farms/${farmId}`);
  return data;
}
