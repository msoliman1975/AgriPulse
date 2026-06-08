// Mirrors backend/app/modules/recommendations/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export type RecommendationState = "open" | "applied" | "dismissed" | "deferred" | "expired";

export type RecommendationSeverity = "info" | "warning" | "critical";

export type RecommendationActionType =
  | "irrigate"
  | "fertilize"
  | "spray"
  | "scout"
  | "harvest_window"
  | "prune"
  | "no_action"
  | "other";

export interface TreePathStepDTO {
  node_id: string;
  matched: boolean | null;
  label_en: string | null;
  label_ar: string | null;
  values: Record<string, unknown>;
}

// 4-horizon structured guidance (KB P1-B).
export type ActionHorizon = "immediate" | "short_term" | "long_term" | "monitoring";

export interface RecommendationActionItem {
  text_en: string;
  text_ar: string | null;
}

// Horizons with no items are omitted by the server, so every key is optional.
export type RecommendationActions = Partial<
  Record<ActionHorizon, RecommendationActionItem[]>
>;

export interface Recommendation {
  id: string;
  block_id: string;
  farm_id: string;
  tree_id: string;
  tree_code: string;
  tree_version: number;
  block_crop_id: string | null;
  action_type: RecommendationActionType;
  severity: RecommendationSeverity;
  parameters: Record<string, unknown>;
  actions: RecommendationActions;
  // confidence is serialised as a string by Pydantic's Decimal handling.
  confidence: string;
  tree_path: TreePathStepDTO[];
  text_en: string;
  text_ar: string | null;
  valid_until: string | null;
  state: RecommendationState;
  applied_at: string | null;
  applied_by: string | null;
  dismissed_at: string | null;
  dismissed_by: string | null;
  dismissal_reason: string | null;
  deferred_until: string | null;
  outcome_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface DecisionTree {
  id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  description_en: string | null;
  description_ar: string | null;
  crop_id: string | null;
  applicable_regions: string[];
  is_active: boolean;
  current_version: number | null;
}

export interface ListRecommendationsParams {
  farm_id?: string;
  block_id?: string;
  state?: RecommendationState;
  action_type?: RecommendationActionType;
  limit?: number;
}

export async function listRecommendations(
  params: ListRecommendationsParams = {},
): Promise<Recommendation[]> {
  const { data } = await apiClient.get<Recommendation[]>("/v1/recommendations", { params });
  return data;
}

export async function getRecommendation(recommendationId: string): Promise<Recommendation> {
  const { data } = await apiClient.get<Recommendation>(`/v1/recommendations/${recommendationId}`);
  return data;
}

export interface RecommendationTransitionPayload {
  apply?: boolean;
  dismiss?: boolean;
  defer_until?: string | null;
  dismissal_reason?: string | null;
  outcome_notes?: string | null;
}

export async function transitionRecommendation(
  recommendationId: string,
  payload: RecommendationTransitionPayload,
): Promise<Recommendation> {
  const { data } = await apiClient.patch<Recommendation>(
    `/v1/recommendations/${recommendationId}`,
    payload,
  );
  return data;
}

// Board PR-5: drag-rec-to-cell. Spawns a plan_activity with
// recommendation_id set and transitions the rec to applied in one
// server-side transaction.
export interface ScheduleRecommendationPayload {
  scheduled_date?: string | null; // ISO; defaults to today
  activity_type?:
    | "planting"
    | "fertilizing"
    | "spraying"
    | "pruning"
    | "harvesting"
    | "irrigation"
    | "soil_prep"
    | "observation"
    | null;
  block_id?: string | null;
  notes?: string | null;
}

export async function scheduleRecommendation(
  recommendationId: string,
  payload: ScheduleRecommendationPayload = {},
): Promise<import("./plans").PlanActivity> {
  const { data } = await apiClient.post<import("./plans").PlanActivity>(
    `/v1/recommendations/${recommendationId}/schedule`,
    payload,
  );
  return data;
}

export async function listDecisionTrees(): Promise<DecisionTree[]> {
  const { data } = await apiClient.get<DecisionTree[]>("/v1/decision-trees");
  return data;
}
