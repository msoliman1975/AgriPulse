import type { MultiPolygon } from "geojson";
import { apiClient } from "./client";
import type { CursorPage } from "./pagination";

// Types mirror backend/app/modules/farms/schemas.py. Keep in lock-step.

export type FarmType = "commercial" | "research" | "contract";
export type OwnershipType = "owned" | "leased" | "partnership" | "other";
export type WaterSource = "well" | "canal" | "nile" | "desalinated" | "rainfed" | "mixed";
export type FarmStatus = "active" | "archived";
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
  status: FarmStatus;
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
  status?: FarmStatus;
  governorate?: string;
  tag?: string;
  include_archived?: boolean;
}

export async function listFarms(params: FarmListParams = {}): Promise<CursorPage<Farm>> {
  const { data } = await apiClient.get<CursorPage<Farm>>("/v1/farms", { params });
  return data;
}

export async function getFarm(farmId: string): Promise<FarmDetail> {
  const { data } = await apiClient.get<FarmDetail>(`/v1/farms/${farmId}`);
  return data;
}

export async function createFarm(payload: FarmCreatePayload): Promise<FarmDetail> {
  const { data } = await apiClient.post<FarmDetail>("/v1/farms", payload);
  return data;
}

export async function updateFarm(farmId: string, payload: FarmUpdatePayload): Promise<FarmDetail> {
  const { data } = await apiClient.patch<FarmDetail>(`/v1/farms/${farmId}`, payload);
  return data;
}

export async function archiveFarm(farmId: string): Promise<void> {
  await apiClient.delete(`/v1/farms/${farmId}`);
}
