import { apiClient } from "./client";
import type { CropAttributeDefinition } from "./crops";

export type BlockCropStatus = "planned" | "growing" | "harvesting" | "completed" | "aborted";

export interface BlockCropAssignment {
  id: string;
  block_id: string;
  crop_id: string;
  crop_variety_id: string | null;
  crop_variety_strain_id: string | null;
  // Denormalized hierarchical path, e.g. "mango.alphonso.short" or "cotton".
  crop_path: string;
  season_label: string;
  planting_date: string | null;
  actual_harvest_date: string | null;
  growth_stage: string | null;
  growth_stage_updated_at: string | null;
  /** When true the daily phenology sweep leaves this assignment alone, so a
   *  stage someone set by hand survives. */
  growth_stage_locked: boolean;
  /** Valid time, half-open `[from, to)`. `effective_to === null` = ongoing. */
  effective_from: string;
  effective_to: string | null;
  /** Derived server-side from the range against today. Prefer this over
   *  `is_current`, which is a stored flag that only moves when someone assigns
   *  a crop — a finished season still reads as current under it. */
  is_active_now: boolean;
  validity_state: "past" | "current" | "scheduled";
  is_current: boolean;
  status: BlockCropStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface BlockCropAssignPayload {
  crop_id: string;
  crop_variety_id?: string | null;
  crop_variety_strain_id?: string | null;
  season_label: string;
  planting_date?: string | null;
  notes?: string | null;
  /** Defaults to `planting_date`, else today. */
  effective_from?: string | null;
  /** Omit or null for an ongoing assignment (the normal perennial case).
   *  Assigning auto-closes the block's open assignment at `effective_from`. */
  effective_to?: string | null;
  /** Crop fields for the assignment being created, `{code: value}`.
   *
   *  Sent with the assignment, not in a follow-up PUT: the server writes both
   *  in one transaction, so a rejected attribute rolls the assignment back
   *  instead of leaving one half-configured. */
  attributes?: Record<string, unknown>;
  make_current?: boolean;
}

export async function assignBlockCrop(
  blockId: string,
  payload: BlockCropAssignPayload,
): Promise<BlockCropAssignment> {
  const { data } = await apiClient.post<BlockCropAssignment>(
    `/v1/blocks/${blockId}/crop-assignments`,
    payload,
  );
  return data;
}

/** One block's crop on one date, as `GET /v1/farms/{id}/crop-assignments` returns it. */
export interface FarmCropAssignment {
  block_id: string;
  block_crop_id: string;
  crop_id: string;
  crop_path: string;
  crop_name_en: string;
  crop_name_ar: string;
  /** Null at a level the crop's classification depth does not reach. */
  variety_name_en: string | null;
  variety_name_ar: string | null;
  strain_name_en: string | null;
  strain_name_ar: string | null;
  season_label: string;
  effective_from: string;
  effective_to: string | null;
  status: BlockCropStatus;
}

/**
 * The crop each block on a farm carried on `on` (YYYY-MM-DD; omit for today).
 *
 * Farm-wide in one request because the caller is the map label, which needs
 * every block at once and re-asks whenever the reader picks another scene
 * date. Blocks with no assignment covering that date are simply absent.
 */
export async function listFarmCropAssignments(
  farmId: string,
  on?: string | null,
): Promise<FarmCropAssignment[]> {
  const { data } = await apiClient.get<FarmCropAssignment[]>(
    `/v1/farms/${farmId}/crop-assignments`,
    { params: on ? { on } : undefined },
  );
  return data;
}

export async function listBlockCrops(blockId: string): Promise<BlockCropAssignment[]> {
  const { data } = await apiClient.get<BlockCropAssignment[]>(
    `/v1/blocks/${blockId}/crop-assignments`,
  );
  return data;
}

// ---- Crop attributes on an assignment --------------------------------------
//
// Platform-curated typed fields (establishment method, transplant date, age at
// transplant, seed grade, …). The definitions ship *with* the values so the
// form can render, gate and validate from a single response — fetching the
// catalog separately is how the form and the server end up disagreeing about
// which fields are required.

export interface BlockCropAttributes {
  block_crop_id: string;
  crop_path: string;
  definitions: CropAttributeDefinition[];
  /** `{code: value}` — only codes that currently hold a value. */
  values: Record<string, unknown>;
}

export interface BlockCropAttributeHistoryEntry {
  id: string;
  block_crop_id: string;
  definition_id: string;
  definition_code: string;
  value: unknown;
  previous_value: unknown;
  /** `cleared_by_gate` distinguishes a value dropped because its gate closed
   *  from one a user cleared. */
  change_kind: "set" | "updated" | "cleared" | "cleared_by_gate";
  changed_at: string;
  changed_by: string | null;
}

export async function getBlockCropAttributes(blockCropId: string): Promise<BlockCropAttributes> {
  const { data } = await apiClient.get<BlockCropAttributes>(
    `/v1/crop-assignments/${blockCropId}/attributes`,
  );
  return data;
}

/** Replaces the whole visible form. Omitted codes keep their stored value; a
 *  code sent as `null` clears it. */
export async function putBlockCropAttributes(
  blockCropId: string,
  attributes: Record<string, unknown>,
): Promise<BlockCropAttributes> {
  const { data } = await apiClient.put<BlockCropAttributes>(
    `/v1/crop-assignments/${blockCropId}/attributes`,
    { attributes },
  );
  return data;
}

export async function getBlockCropAttributeHistory(
  blockCropId: string,
  code?: string,
): Promise<BlockCropAttributeHistoryEntry[]> {
  const { data } = await apiClient.get<BlockCropAttributeHistoryEntry[]>(
    `/v1/crop-assignments/${blockCropId}/attributes/history`,
    { params: code ? { code } : undefined },
  );
  return data;
}

// --- Growth stage ---------------------------------------------------------
//
// The stage lives on the crop assignment but has its own endpoints, because a
// transition is an event: it appends to the block's phenology timeline rather
// than overwriting a field. The daily `phenology.advance_growth_stages` task
// writes through the same log with `source: "auto"`.

// Mirrors GrowthStageSource in backend/app/modules/farms/schemas.py. The
// daily phenology sweep writes "derived", NOT "auto" — getting this wrong meant
// the timeline rendered a raw i18n key for every automatic transition.
export type GrowthStageSource = "manual" | "derived" | "imported";

export interface GrowthStageLogEntry {
  id: string;
  block_id: string;
  block_crop_id: string | null;
  stage: string;
  source: GrowthStageSource;
  confirmed_by: string | null;
  transition_date: string;
  notes: string | null;
  created_at: string;
}

export interface RecordGrowthStagePayload {
  stage: string;
  source?: GrowthStageSource;
  transition_date?: string | null;
  block_crop_id?: string | null;
  notes?: string | null;
}

export async function listGrowthStages(blockId: string): Promise<GrowthStageLogEntry[]> {
  const { data } = await apiClient.get<GrowthStageLogEntry[]>(
    `/v1/blocks/${blockId}/growth-stages`,
  );
  return data;
}

export async function recordGrowthStage(
  blockId: string,
  payload: RecordGrowthStagePayload,
): Promise<GrowthStageLogEntry> {
  const { data } = await apiClient.post<GrowthStageLogEntry>(
    `/v1/blocks/${blockId}/growth-stages`,
    { source: "manual", ...payload },
  );
  return data;
}

/** Patch the agronomy fields on an assignment. Growth stage itself is
 *  deliberately not settable here — it goes through `recordGrowthStage`. */
export async function updateBlockCrop(
  blockId: string,
  blockCropId: string,
  fields: { growth_stage_locked?: boolean; notes?: string | null },
): Promise<BlockCropAssignment> {
  const { data } = await apiClient.patch<BlockCropAssignment>(
    `/v1/blocks/${blockId}/crop-assignments/${blockCropId}`,
    fields,
  );
  return data;
}
