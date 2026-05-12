import type { Polygon } from "geojson";
import { apiClient } from "./client";
import type { AreaUnitName } from "./farms";
import type { CursorPage } from "./pagination";

export type IrrigationSystem =
  | "drip"
  | "micro_sprinkler"
  | "pivot"
  | "furrow"
  | "flood"
  | "surface"
  | "none";
export type IrrigationSource = "well" | "canal" | "nile" | "mixed";
export type SoilTexture =
  | "sandy"
  | "sandy_loam"
  | "loam"
  | "clay_loam"
  | "clay"
  | "silty_loam"
  | "silty_clay";
export type SalinityClass =
  | "non_saline"
  | "slightly_saline"
  | "moderately_saline"
  | "strongly_saline";

// Land-unit polymorphism. A "block" row may represent a plain block, a
// pivot (full-circle, center-pivot irrigation), or a pivot_sector (a
// pie-slice subdivision of a pivot). pivot_sector rows carry
// parent_unit_id; the others must leave it null.
export type UnitType = "block" | "pivot" | "pivot_sector";

export interface Block {
  id: string;
  farm_id: string;
  code: string;
  name: string | null;
  centroid: GeoJSON.Point;
  area_m2: number;
  area_value: number;
  area_unit: AreaUnitName;
  aoi_hash: string;
  elevation_m: number | null;
  irrigation_system: IrrigationSystem | null;
  irrigation_source: IrrigationSource | null;
  soil_texture: SoilTexture | null;
  salinity_class: SalinityClass | null;
  soil_ph: number | null;
  responsible_user_id: string | null;
  notes: string | null;
  tags: string[];
  // Lifecycle replaces the old status enum (active/fallow/abandoned/...).
  active_from: string; // ISO date
  active_to: string | null;
  is_active: boolean;
  unit_type: UnitType;
  parent_unit_id: string | null;
  irrigation_geometry: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface BlockDetail extends Block {
  boundary: Polygon;
}

export interface BlockCreatePayload {
  code: string;
  name?: string | null;
  boundary: Polygon;
  elevation_m?: number | null;
  irrigation_system?: IrrigationSystem | null;
  irrigation_source?: IrrigationSource | null;
  soil_texture?: SoilTexture | null;
  salinity_class?: SalinityClass | null;
  soil_ph?: number | null;
  responsible_user_id?: string | null;
  notes?: string | null;
  tags?: string[];
  unit_type?: UnitType;
  parent_unit_id?: string | null;
  irrigation_geometry?: Record<string, unknown> | null;
  active_from?: string | null;
}

export type BlockUpdatePayload = Partial<BlockCreatePayload>;

export interface BlockListParams {
  cursor?: string;
  limit?: number;
  irrigation_system?: IrrigationSystem;
  include_inactive?: boolean;
}

export interface AutoGridCandidate {
  code: string;
  boundary: Polygon;
  area_m2: number;
}

export interface AutoGridResponse {
  cell_size_m: number;
  candidates: AutoGridCandidate[];
}

export interface BlockInactivationPreview {
  alerts_resolved: number;
  irrigation_skipped: number;
  plan_activities_skipped: number;
  weather_subs_deactivated: number;
  imagery_subs_deactivated: number;
}

export interface BlockInactivationResult extends BlockInactivationPreview {
  block_id: string;
  farm_id: string;
  active_to: string;
}

export interface BlockReactivationResult {
  block_id: string;
  farm_id: string;
}

function normalizeBlock<T extends { area_m2: unknown; area_value: unknown }>(b: T): T {
  return { ...b, area_m2: Number(b.area_m2 ?? 0), area_value: Number(b.area_value ?? 0) };
}

export async function listBlocks(
  farmId: string,
  params: BlockListParams = {},
): Promise<CursorPage<Block>> {
  const { data } = await apiClient.get<CursorPage<Block>>(`/v1/farms/${farmId}/blocks`, { params });
  return { ...data, items: data.items.map(normalizeBlock) };
}

export async function getBlock(blockId: string): Promise<BlockDetail> {
  const { data } = await apiClient.get<BlockDetail>(`/v1/blocks/${blockId}`);
  return normalizeBlock(data);
}

export async function createBlock(
  farmId: string,
  payload: BlockCreatePayload,
): Promise<BlockDetail> {
  const { data } = await apiClient.post<BlockDetail>(`/v1/farms/${farmId}/blocks`, payload);
  return normalizeBlock(data);
}

export async function updateBlock(
  blockId: string,
  payload: BlockUpdatePayload,
): Promise<BlockDetail> {
  const { data } = await apiClient.patch<BlockDetail>(`/v1/blocks/${blockId}`, payload);
  return normalizeBlock(data);
}

export async function getBlockInactivationPreview(
  blockId: string,
): Promise<BlockInactivationPreview> {
  const { data } = await apiClient.get<BlockInactivationPreview>(
    `/v1/blocks/${blockId}/inactivate-preview`,
  );
  return data;
}

export async function inactivateBlock(
  blockId: string,
  payload: { reason?: string | null } = {},
): Promise<BlockInactivationResult> {
  const { data } = await apiClient.post<BlockInactivationResult>(
    `/v1/blocks/${blockId}/inactivate`,
    payload,
  );
  return data;
}

export async function reactivateBlock(blockId: string): Promise<BlockReactivationResult> {
  const { data } = await apiClient.post<BlockReactivationResult>(
    `/v1/blocks/${blockId}/reactivate`,
  );
  return data;
}

// DELETE alias for backwards-compatibility callers.
export async function archiveBlock(blockId: string): Promise<BlockInactivationResult> {
  const { data } = await apiClient.delete<BlockInactivationResult>(`/v1/blocks/${blockId}`);
  return data;
}

export interface PivotCreatePayload {
  code: string;
  name?: string | null;
  center: { lat: number; lon: number };
  radius_m: number;
  sector_count: number;
  irrigation_system?: IrrigationSystem | null;
  active_from?: string | null;
}

export interface PivotCreateResult {
  pivot: BlockDetail;
  sectors: BlockDetail[];
}

export async function createPivot(
  farmId: string,
  payload: PivotCreatePayload,
): Promise<PivotCreateResult> {
  const { data } = await apiClient.post<PivotCreateResult>(
    `/v1/farms/${farmId}/pivots`,
    payload,
  );
  return {
    pivot: normalizeBlock(data.pivot),
    sectors: data.sectors.map(normalizeBlock),
  };
}

export async function autoGrid(farmId: string, cellSizeM: number): Promise<AutoGridResponse> {
  const { data } = await apiClient.post<AutoGridResponse>(`/v1/farms/${farmId}/blocks/auto-grid`, {
    cell_size_m: cellSizeM,
  });
  return data;
}
