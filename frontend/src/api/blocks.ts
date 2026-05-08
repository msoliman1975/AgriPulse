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
export type BlockStatus = "active" | "fallow" | "abandoned" | "under_preparation" | "archived";

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
  status: BlockStatus;
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
  // Defaults to 'block' on the backend; pivots/sectors require a
  // dedicated creation flow that PR-1 does not yet expose in the UI.
  unit_type?: UnitType;
  parent_unit_id?: string | null;
  irrigation_geometry?: Record<string, unknown> | null;
}

export type BlockUpdatePayload = Partial<BlockCreatePayload>;

export interface BlockListParams {
  cursor?: string;
  limit?: number;
  status?: BlockStatus;
  irrigation_system?: IrrigationSystem;
  include_archived?: boolean;
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

// Backend serializes area_m2 / area_value as Decimal (JSON string). Coerce
// to number at the boundary so render code can call .toFixed() etc.
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

export async function archiveBlock(blockId: string): Promise<void> {
  await apiClient.delete(`/v1/blocks/${blockId}`);
}

export async function autoGrid(farmId: string, cellSizeM: number): Promise<AutoGridResponse> {
  const { data } = await apiClient.post<AutoGridResponse>(`/v1/farms/${farmId}/blocks/auto-grid`, {
    cell_size_m: cellSizeM,
  });
  return data;
}
