// Agri Operation: operation manuals (read views) and saved plans.
// Backend: app/modules/plan_templates (routes under /v1/plan-templates and
// /v1/farms/{farm_id}/plan-allocations). See
// docs/proposals/agri-operation-build-plan.md section 3.4.

import { apiClient } from "./client";
import type { PlanActivityType, PlanTemplateDetail, PlanTemplateSummary } from "./planTemplates";

// ---- Manuals ----------------------------------------------------------------

/** calendar_doy stages carry "MM-DD" bounds; days_from_planting stages carry
 *  day counts. Other modes (gdd, manual) carry neither. */
export interface StageAdvance {
  mode: string;
  start_doy?: string;
  end_doy?: string;
  start_day?: number;
  end_day?: number;
}

export interface PhenologyStage {
  code: string;
  name_en?: string | null;
  name_ar?: string | null;
  advance: StageAdvance;
}

export interface VarietyPhenology {
  /** Crop path, e.g. "mango" (the crop's own calendar) or "mango.keitt". */
  path: string;
  code?: string | null;
  /** Null for the crop's own calendar. */
  name_en: string | null;
  name_ar: string | null;
  is_perennial: boolean;
  stages: PhenologyStage[];
}

export interface OperationManual extends PlanTemplateDetail {
  is_perennial: boolean;
  stages: PhenologyStage[];
  varieties: VarietyPhenology[];
}

export interface ManualCatalogItem extends PlanTemplateSummary {
  activity_count: number;
}

export async function listManualCatalog(
  farmId: string,
  crop?: string,
): Promise<ManualCatalogItem[]> {
  const { data } = await apiClient.get<ManualCatalogItem[]>("/v1/plan-templates/catalog", {
    params: { farm_id: farmId, ...(crop ? { crop } : {}) },
  });
  return data;
}

export async function getFarmManual(farmId: string, templateId: string): Promise<OperationManual> {
  const { data } = await apiClient.get<OperationManual>(`/v1/plan-templates/${templateId}/manual`, {
    params: { farm_id: farmId },
  });
  return data;
}

export async function getAuthoringManual(templateId: string): Promise<OperationManual> {
  const { data } = await apiClient.get<OperationManual>(
    `/v1/plan-templates/${templateId}/authoring-view`,
  );
  return data;
}

// ---- Manual revisions -------------------------------------------------------

export interface ManualChangeItem {
  code: string;
  title: string | null;
  title_ar: string | null;
  activity_type: string | null;
  fields: string[];
}

export interface ManualDiff {
  comparable: boolean;
  added: ManualChangeItem[];
  removed: ManualChangeItem[];
  changed: ManualChangeItem[];
}

export interface PublishImpact extends ManualDiff {
  template_id: string;
  revision: number;
  published_at: string | null;
  farms: number;
  saved_plans: number;
}

export interface ManualChanges extends ManualDiff {
  allocation_id: string;
  template_id: string;
  applied_revision: number;
  current_revision: number;
  manual_updated: boolean;
}

export async function getPublishImpact(templateId: string): Promise<PublishImpact> {
  const { data } = await apiClient.get<PublishImpact>(
    `/v1/plan-templates/${templateId}/publish-impact`,
  );
  return data;
}

// ---- Saved plans (allocations) ----------------------------------------------

export type StartMode = "same" | "per_block";

export interface AllocationBlock {
  block_id: string;
  start_date: string;
}

export interface AllocationActivityEdit {
  product_name?: string | null;
  dosage?: string | null;
  notes?: string | null;
  product_name_ar?: string | null;
  dosage_ar?: string | null;
  notes_ar?: string | null;
}

export interface AllocationCustomActivity {
  /** "custom:<id>" */
  key: string;
  activity_type: PlanActivityType;
  title: string;
  title_ar?: string | null;
  anchor: "week" | "stage";
  week?: number | null;
  stage_code?: string | null;
  offset_days?: number;
  duration_days?: number;
  product_name?: string | null;
  dosage?: string | null;
  notes?: string | null;
}

export interface AllocationWriteRequest {
  template_id: string;
  season_label: string;
  season_year: number;
  start_mode: StartMode;
  blocks: AllocationBlock[];
  excluded_codes: string[];
  activity_edits: Record<string, AllocationActivityEdit>;
  custom_activities: AllocationCustomActivity[];
  /** {block_id: {activity_key: "YYYY-MM-DD"}} */
  date_overrides: Record<string, Record<string, string>>;
}

export interface SavedPlan extends AllocationWriteRequest {
  id: string;
  farm_id: string;
  plan_id: string;
  template_code: string | null;
  template_name: string | null;
  template_name_ar: string | null;
  crop_path: string | null;
  template_revision: number;
  manual_updated: boolean;
  applied_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AllocatedActivityPreview {
  activity_key: string;
  source: "template" | "custom";
  template_activity_id: string | null;
  activity_type: string;
  title: string | null;
  title_ar: string | null;
  scheduled_date: string;
  default_date: string;
  date_overridden: boolean;
  duration_days: number;
  anchored_stage_code: string | null;
  product_name: string | null;
  dosage: string | null;
  notes: string | null;
}

export interface AllocationBlockSchedule {
  block_id: string;
  block_code: string | null;
  crop_path: string | null;
  start_date: string;
  activities: AllocatedActivityPreview[];
  skipped: Record<string, unknown>[];
}

export interface RejectedBlock {
  block_id: string;
  block_code: string | null;
  crop_path: string | null;
  reason: string;
}

export interface AllocationPreview {
  template_id: string;
  blocks: AllocationBlockSchedule[];
  rejected_blocks: RejectedBlock[];
  missing_codes: string[];
  total_activities: number;
}

export interface AllocationApplyResult {
  allocation: SavedPlan;
  activities_created: number;
  activities_kept: number;
  skipped: number;
}

const base = (farmId: string): string => `/v1/farms/${farmId}/plan-allocations`;

export async function listSavedPlans(farmId: string): Promise<SavedPlan[]> {
  const { data } = await apiClient.get<SavedPlan[]>(base(farmId));
  return data;
}

export async function getSavedPlan(farmId: string, id: string): Promise<SavedPlan> {
  const { data } = await apiClient.get<SavedPlan>(`${base(farmId)}/${id}`);
  return data;
}

export async function previewSavedPlan(
  farmId: string,
  body: AllocationWriteRequest,
): Promise<AllocationPreview> {
  const { data } = await apiClient.post<AllocationPreview>(`${base(farmId)}/preview`, body);
  return data;
}

export async function createSavedPlan(
  farmId: string,
  body: AllocationWriteRequest,
): Promise<AllocationApplyResult> {
  const { data } = await apiClient.post<AllocationApplyResult>(base(farmId), body);
  return data;
}

export async function updateSavedPlan(
  farmId: string,
  id: string,
  body: AllocationWriteRequest,
): Promise<AllocationApplyResult> {
  const { data } = await apiClient.put<AllocationApplyResult>(`${base(farmId)}/${id}`, body);
  return data;
}

export async function deleteSavedPlan(farmId: string, id: string): Promise<void> {
  await apiClient.delete(`${base(farmId)}/${id}`);
}

export async function getManualChanges(farmId: string, id: string): Promise<ManualChanges> {
  const { data } = await apiClient.get<ManualChanges>(`${base(farmId)}/${id}/manual-changes`);
  return data;
}
