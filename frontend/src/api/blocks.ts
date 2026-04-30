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

export async function listBlocks(
  farmId: string,
  params: BlockListParams = {},
): Promise<CursorPage<Block>> {
  const { data } = await apiClient.get<CursorPage<Block>>(`/v1/farms/${farmId}/blocks`, { params });
  return data;
}

export async function getBlock(blockId: string): Promise<BlockDetail> {
  const { data } = await apiClient.get<BlockDetail>(`/v1/blocks/${blockId}`);
  return data;
}

export async function createBlock(
  farmId: string,
  payload: BlockCreatePayload,
): Promise<BlockDetail> {
  const { data } = await apiClient.post<BlockDetail>(`/v1/farms/${farmId}/blocks`, payload);
  return data;
}

export async function updateBlock(
  blockId: string,
  payload: BlockUpdatePayload,
): Promise<BlockDetail> {
  const { data } = await apiClient.patch<BlockDetail>(`/v1/blocks/${blockId}`, payload);
  return data;
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
