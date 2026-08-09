import { apiClient } from "./client";
import type { BlockCropStatus } from "./cropAssignments";

/**
 * Tenant Settings → Bulk Updates → crop assignment.
 *
 * Three calls, in the order the wizard uses them: candidates fills the block
 * picker, preview says what would happen, apply does it. Preview and apply
 * take the SAME body — a dry run the user approved and an apply that then
 * behaves differently is the failure this surface exists to prevent, so the
 * page builds one payload and sends it to both.
 */

/** What a block carries today. Null on an unassigned block. */
export interface BulkCropCurrent {
  block_crop_id: string;
  crop_path: string;
  season_label: string;
  planting_date: string | null;
  effective_from: string;
  status: BlockCropStatus;
}

export interface BulkCropCandidate {
  block_id: string;
  code: string;
  name: string | null;
  area_value: string;
  area_unit: string;
  unit_type: string;
  current: BulkCropCurrent | null;
}

/** What a block would receive (or did). */
export interface BulkCropPlanned {
  crop_path: string;
  season_label: string;
  planting_date: string | null;
  effective_from: string;
}

export type BulkConflictMode = "skip" | "replace";

/** Future tense — nothing has been written. */
export type BulkPreviewOutcome = "assign" | "replace" | "skip";
/** Past tense — these describe what happened. */
export type BulkApplyOutcome = "assigned" | "replaced" | "skipped" | "failed";

export interface BulkCropTarget {
  block_id: string;
  /** Omit to use the run's shared value. */
  season_label?: string | null;
  planting_date?: string | null;
}

export interface BulkCropAssignmentPayload {
  conflict_mode: BulkConflictMode;
  targets: BulkCropTarget[];
  crop_id: string;
  crop_variety_id?: string | null;
  crop_variety_strain_id?: string | null;
  season_label: string;
  effective_from?: string | null;
  planting_date?: string | null;
  canopy_size_class?: string | null;
  notes?: string | null;
  attributes?: Record<string, unknown>;
}

interface BulkItemBase {
  block_id: string;
  code: string;
  name: string | null;
  before: BulkCropCurrent | null;
  after: BulkCropPlanned | null;
  overridden: boolean;
  detail: string | null;
}

export interface BulkCropPreviewItem extends BulkItemBase {
  outcome: BulkPreviewOutcome;
}

export interface BulkCropApplyItem extends BulkItemBase {
  outcome: BulkApplyOutcome;
  block_crop_id: string | null;
}

export interface BulkCropPreview {
  farm_id: string;
  conflict_mode: BulkConflictMode;
  crop_path: string;
  assign_count: number;
  replace_count: number;
  skip_count: number;
  items: BulkCropPreviewItem[];
}

export interface BulkCropApplyResult {
  farm_id: string;
  conflict_mode: BulkConflictMode;
  crop_path: string;
  applied_count: number;
  skipped_count: number;
  failed_count: number;
  items: BulkCropApplyItem[];
}

export async function listBulkCropCandidates(farmId: string): Promise<BulkCropCandidate[]> {
  const { data } = await apiClient.get<BulkCropCandidate[]>(
    `/v1/farms/${farmId}/bulk/crop-assignment/candidates`,
  );
  return data;
}

export async function previewBulkCropAssignment(
  farmId: string,
  payload: BulkCropAssignmentPayload,
): Promise<BulkCropPreview> {
  const { data } = await apiClient.post<BulkCropPreview>(
    // The colon suffix marks a non-CRUD action on the collection, so the
    // dry run cannot be reached by the same POST that writes.
    `/v1/farms/${farmId}/bulk/crop-assignment:preview`,
    payload,
  );
  return data;
}

export async function applyBulkCropAssignment(
  farmId: string,
  payload: BulkCropAssignmentPayload,
): Promise<BulkCropApplyResult> {
  const { data } = await apiClient.post<BulkCropApplyResult>(
    `/v1/farms/${farmId}/bulk/crop-assignment`,
    payload,
  );
  return data;
}

// ---- Removal (HARD delete) --------------------------------------------------
//
// Permanently erases assignments entered by mistake. There is no undo behind
// this, which is why `previewBulkCropRemoval` exists and why the response
// counts the dependent rows that go with them.

export interface BulkCropRemovalAssignment {
  block_crop_id: string;
  crop_path: string;
  season_label: string;
  effective_from: string;
  effective_to: string | null;
  is_current: boolean;
}

export interface BulkCropRemovalItem {
  block_id: string;
  code: string;
  name: string | null;
  assignments: BulkCropRemovalAssignment[];
  removed_count: number;
  detail: string | null;
}

export interface BulkCropRemoval {
  farm_id: string;
  block_count: number;
  assignment_count: number;
  attribute_value_count: number;
  attribute_value_log_count: number;
  growth_stage_log_count: number;
  recommendation_unlink_count: number;
  /** Assignments a `replace` run auto-closed that this removal un-closes. */
  reopened_count: number;
  items: BulkCropRemovalItem[];
}

/** Exactly one selector. `block_ids` wipes those blocks entirely, history
 *  included; `block_crop_ids` removes only those rows, which is what "undo
 *  this run" needs so it cannot touch the block's earlier seasons. */
export interface BulkCropRemovalPayload {
  block_ids?: string[];
  block_crop_ids?: string[];
}

export async function previewBulkCropRemoval(
  farmId: string,
  payload: BulkCropRemovalPayload,
): Promise<BulkCropRemoval> {
  const { data } = await apiClient.post<BulkCropRemoval>(
    `/v1/farms/${farmId}/bulk/crop-assignment:remove-preview`,
    payload,
  );
  return data;
}

export async function removeBulkCropAssignments(
  farmId: string,
  payload: BulkCropRemovalPayload,
): Promise<BulkCropRemoval> {
  const { data } = await apiClient.post<BulkCropRemoval>(
    `/v1/farms/${farmId}/bulk/crop-assignment:remove`,
    payload,
  );
  return data;
}
