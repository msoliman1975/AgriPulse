import { apiClient } from "./client";

// ---- Shared types ---------------------------------------------------------

export type TemplateStatus = "draft" | "published" | "archived";
export type ActivityAnchor = "start" | "milestone" | "stage";

// Mirrors the backend ActivityType literal (app/modules/plans/schemas.py).
export type PlanActivityType =
  | "planting"
  | "fertilizing"
  | "spraying"
  | "pruning"
  | "harvesting"
  | "irrigation"
  | "soil_prep"
  | "observation";

export const ACTIVITY_TYPES: readonly PlanActivityType[] = [
  "planting",
  "fertilizing",
  "spraying",
  "pruning",
  "harvesting",
  "irrigation",
  "soil_prep",
  "observation",
];

export interface PlanTemplateMilestone {
  id: string;
  code: string;
  name: string;
  day_from_start: number;
  sort_order: number;
}

export interface PlanTemplateActivity {
  id: string;
  activity_type: string;
  anchor: ActivityAnchor;
  milestone_id: string | null;
  stage_code: string | null;
  offset_days: number;
  duration_days: number;
  product_name: string | null;
  dosage: string | null;
  notes: string | null;
  start_time: string | null;
  sort_order: number;
}

export interface PlanTemplateSummary {
  id: string;
  code: string;
  name: string;
  crop_path: string;
  crop_id: string | null;
  country: string | null;
  region: string | null;
  description: string | null;
  status: TemplateStatus;
  created_at: string;
  updated_at: string;
}

export interface PlanTemplateDetail extends PlanTemplateSummary {
  milestones: PlanTemplateMilestone[];
  activities: PlanTemplateActivity[];
}

// ---- Authoring (whole-tree write) -----------------------------------------

export interface MilestoneInput {
  code: string;
  name: string;
  day_from_start: number;
  sort_order: number;
}

export interface ActivityInput {
  activity_type: PlanActivityType;
  anchor: ActivityAnchor;
  // milestone-anchored: the milestone's *code* (resolved to an id on write).
  milestone_code?: string | null;
  stage_code?: string | null;
  offset_days: number;
  duration_days: number;
  product_name?: string | null;
  dosage?: string | null;
  notes?: string | null;
  sort_order: number;
}

export interface PlanTemplateWriteRequest {
  code: string;
  name: string;
  crop_path: string;
  country?: string | null;
  region?: string | null;
  description?: string | null;
  milestones: MilestoneInput[];
  activities: ActivityInput[];
}

// ---- Phenology resolution (authoring stage-picker) ------------------------

export interface PhenologyStage {
  code: string;
  name_en?: string;
  name_ar?: string;
  order?: number;
  advance?: Record<string, unknown>;
}

export interface ResolvedPhenology {
  crop_path: string;
  is_perennial: boolean;
  stages: PhenologyStage[];
}

// ---- Platform API (cap plan_template.manage) ------------------------------

export async function listPlanTemplates(status?: TemplateStatus): Promise<PlanTemplateSummary[]> {
  const { data } = await apiClient.get<PlanTemplateSummary[]>("/v1/plan-templates", {
    params: status ? { status } : undefined,
  });
  return data;
}

export async function getPlanTemplate(id: string): Promise<PlanTemplateDetail> {
  const { data } = await apiClient.get<PlanTemplateDetail>(`/v1/plan-templates/${id}`);
  return data;
}

export async function createPlanTemplate(
  body: PlanTemplateWriteRequest,
): Promise<PlanTemplateDetail> {
  const { data } = await apiClient.post<PlanTemplateDetail>("/v1/plan-templates", body);
  return data;
}

export async function updatePlanTemplate(
  id: string,
  body: PlanTemplateWriteRequest,
): Promise<PlanTemplateDetail> {
  const { data } = await apiClient.put<PlanTemplateDetail>(`/v1/plan-templates/${id}`, body);
  return data;
}

export async function publishPlanTemplate(id: string): Promise<PlanTemplateDetail> {
  const { data } = await apiClient.post<PlanTemplateDetail>(`/v1/plan-templates/${id}/publish`);
  return data;
}

export async function archivePlanTemplate(id: string): Promise<PlanTemplateDetail> {
  const { data } = await apiClient.post<PlanTemplateDetail>(`/v1/plan-templates/${id}/archive`);
  return data;
}

export async function deletePlanTemplate(id: string): Promise<void> {
  await apiClient.delete(`/v1/plan-templates/${id}`);
}

export async function resolveTemplatePhenology(cropPath: string): Promise<ResolvedPhenology> {
  const { data } = await apiClient.get<ResolvedPhenology>("/v1/plan-templates/phenology", {
    params: { crop_path: cropPath },
  });
  return data;
}
