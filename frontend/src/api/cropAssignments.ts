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
