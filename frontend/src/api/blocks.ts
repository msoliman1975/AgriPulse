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
  // U-4b: per-block agronomist, referenced by tenant membership_id.
  agronomist_membership_id: string | null;
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
  agronomist_membership_id?: string | null;
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
  // Map clients: get every polygon in this one call instead of following up
  // with a GET /blocks/{id} per row.
  include_boundary?: boolean;
}

/** List row with the optional boundary the map asks for. */
export interface BlockListItem extends Block {
  boundary?: Polygon | null;
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
): Promise<CursorPage<BlockListItem>> {
  const { data } = await apiClient.get<CursorPage<BlockListItem>>(`/v1/farms/${farmId}/blocks`, {
    params,
  });
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

// ---- Bulk block create from uploaded AOI files --------------------------

export interface BulkBlockItem {
  code: string;
  name?: string | null;
  boundary: Polygon;
}

export type BulkBlockStatus =
  | "created"
  | "reused"
  | "replaced_deleted"
  | "replaced_inactivated"
  | "error";

export interface BulkBlockResultRow {
  index: number;
  code: string;
  status: BulkBlockStatus;
  block_id: string | null;
  replaced_block_id: string | null;
  error_code: string | null;
  message: string | null;
}

export interface BulkBlockCreateResult {
  results: BulkBlockResultRow[];
  created: number;
  reused: number;
  replaced: number;
  errors: number;
}

/**
 * Reconcile many AOI-derived candidate blocks against a farm. Identity is the
 * block `code`: new → created, same code + identical geometry → reused, same
 * code + changed geometry → replaced (delete-if-pristine else inactivate).
 * A destructive replace only runs when `allowReplace` is true AND the caller
 * holds the delete capability; otherwise those rows come back as errors.
 */
export async function bulkCreateBlocks(
  farmId: string,
  items: BulkBlockItem[],
  allowReplace: boolean,
): Promise<BulkBlockCreateResult> {
  const { data } = await apiClient.post<BulkBlockCreateResult>(`/v1/farms/${farmId}/blocks:bulk`, {
    items,
    allow_replace: allowReplace,
  });
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
  const { data } = await apiClient.post<PivotCreateResult>(`/v1/farms/${farmId}/pivots`, payload);
  return {
    pivot: normalizeBlock(data.pivot),
    sectors: data.sectors.map(normalizeBlock),
  };
}

/**
 * Compute candidate blocks by tiling the farm. Drive the grid either by cell
 * edge ({@link AutoGridParams.cellSizeM}) or by a per-block max area
 * ({@link AutoGridParams.maxAreaM2}, canonical m² — the caller converts from
 * the user's preferred area unit). When maxAreaM2 is given the backend derives
 * and echoes the effective cell_size_m.
 */
export interface AutoGridParams {
  cellSizeM?: number;
  maxAreaM2?: number;
}

export async function autoGrid(farmId: string, params: AutoGridParams): Promise<AutoGridResponse> {
  const body: Record<string, number> = {};
  if (params.maxAreaM2 != null) body.max_area_m2 = params.maxAreaM2;
  if (params.cellSizeM != null) body.cell_size_m = params.cellSizeM;
  const { data } = await apiClient.post<AutoGridResponse>(
    `/v1/farms/${farmId}/blocks/auto-grid`,
    body,
  );
  return data;
}

/** One handover of a block's responsible member. Append-only; newest first. */
export interface BlockResponsibleLogEntry {
  id: string;
  previous_membership_id: string | null;
  new_membership_id: string | null;
  note: string | null;
  changed_at: string;
  changed_by: string | null;
}

/**
 * Hand a block over to a member.
 *
 * Its own endpoint rather than a field on `updateBlock`: a handover carries a
 * reason and produces history, while the generic block update takes a bag of
 * metadata fields and audits only their names. Returns the refreshed history,
 * so the panel re-renders without a second round trip — and so a no-op save
 * still returns the truth rather than an empty success.
 */
export async function setBlockResponsible(
  blockId: string,
  payload: { membership_id: string | null; note: string | null },
): Promise<BlockResponsibleLogEntry[]> {
  const { data } = await apiClient.put<BlockResponsibleLogEntry[]>(
    `/v1/blocks/${blockId}/responsible`,
    payload,
  );
  return data;
}

export async function listBlockResponsibleHistory(
  blockId: string,
): Promise<BlockResponsibleLogEntry[]> {
  const { data } = await apiClient.get<BlockResponsibleLogEntry[]>(
    `/v1/blocks/${blockId}/responsible/history`,
  );
  return data;
}
