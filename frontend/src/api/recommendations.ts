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
export type RecommendationActions = Partial<Record<ActionHorizon, RecommendationActionItem[]>>;

export interface Recommendation {
  id: string;
  block_id: string;
  // Sub-block grid cell for cell-scoped recommendations (per-cell P2); null
  // for block-scoped. cell_row/cell_col give a readable zone label.
  cell_id: string | null;
  cell_row: number | null;
  cell_col: number | null;
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
  /**
   * Aggregation + recurrence (tenant migration 0079).
   *
   * A cell-scoped tree that fires on many cells of one block produces ONE row
   * here — the group — standing for `member_count` cells; the members are
   * never listed. `day_streak` is how many consecutive days it has fired.
   */
  is_group: boolean;
  member_count: number;
  occurrence_count: number;
  day_streak: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
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

// ---- Read-only tree explain (Farm Console "Conditions" tab) ---------------
// Re-walks every visible tree against a block's current signals and reports
// why each did or didn't fire. Writes nothing — unlike `:evaluate` (POST).

export type ExplainStatus = "fired" | "clear" | "per_cell" | "skipped" | "error";

/** One comparison in the dialect the condition evaluator speaks. */
export interface ExplainCondition {
  op?: string;
  left?: unknown;
  right?: unknown;
  low?: unknown;
  high?: unknown;
  values?: unknown[];
  all_of?: ExplainCondition[];
  any_of?: ExplainCondition[];
  not?: ExplainCondition;
}

export interface ExplainStep {
  node_id: string;
  /** null on leaf nodes — those are the verdict, not a check. */
  matched: boolean | null;
  label_en: string | null;
  label_ar: string | null;
  /** Resolved values keyed by dotted ref, e.g. `indices.ndvi.mean`. */
  values: Record<string, string>;
  /** The predicate the value was compared against; null on leaves. */
  condition: ExplainCondition | null;
}

export interface ExplainTree {
  tree_id: string;
  code: string;
  name_en: string | null;
  name_ar: string | null;
  version: number | null;
  scope: string;
  status: ExplainStatus;
  steps: ExplainStep[];
  kind: string | null;
  action_type: RecommendationActionType | null;
  severity: RecommendationSeverity | null;
  confidence: number | null;
  text_en: string | null;
  text_ar: string | null;
  error: string | null;
}

export interface ExplainBlockResponse {
  block_id: string;
  evaluated_at: string;
  crop_path: string | null;
  trees: ExplainTree[];
}

// `farmId` is required: it is what the request is authorized against, so a
// farm-scoped user (Agronomist, Scout, Viewer) resolves. The server verifies
// the block actually belongs to it.
export async function explainBlock(blockId: string, farmId: string): Promise<ExplainBlockResponse> {
  const { data } = await apiClient.get<ExplainBlockResponse>(
    `/v1/blocks/${blockId}/decision-trees:explain`,
    { params: { farm_id: farmId } },
  );
  return data;
}
