// Mirrors backend/app/modules/recommendations/schemas.py — keep in lock-step.

import { apiClient } from "./client";

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

export interface DecisionTreeVersion {
  id: string;
  tree_id: string;
  version: number;
  tree_yaml: string;
  tree_compiled: Record<string, unknown>;
  compiled_hash: string;
  published_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface DecisionTreeDetail extends DecisionTree {
  versions: DecisionTreeVersion[];
}

export interface DecisionTreeCreatePayload {
  code: string;
  crop_code?: string | null;
  tree_yaml: string;
}

export interface DecisionTreeVersionCreatePayload {
  tree_yaml: string;
  notes?: string | null;
}

export interface DryRunPayload {
  block_id: string;
  // Either evaluate the persisted version OR an unsaved YAML body.
  version?: number;
  tree_yaml?: string;
}

export interface TreePathStepDTO {
  node_id: string;
  matched: boolean | null;
  label_en: string | null;
  label_ar: string | null;
  values: Record<string, unknown>;
}

export interface DryRunResponse {
  matched: boolean;
  outcome: {
    action_type: string;
    severity: string;
    confidence: string;
    parameters: Record<string, unknown>;
    text_en: string;
    text_ar: string | null;
    valid_for_hours: number | null;
  } | null;
  path: TreePathStepDTO[];
  evaluation_snapshot: Record<string, unknown>;
  error: string | null;
}

export async function listDecisionTrees(): Promise<DecisionTree[]> {
  const { data } = await apiClient.get<DecisionTree[]>("/v1/decision-trees");
  return data;
}

export async function getDecisionTree(code: string): Promise<DecisionTreeDetail> {
  const { data } = await apiClient.get<DecisionTreeDetail>(`/v1/decision-trees/${code}`);
  return data;
}

export async function listDecisionTreeVersions(
  code: string,
): Promise<DecisionTreeVersion[]> {
  const { data } = await apiClient.get<DecisionTreeVersion[]>(
    `/v1/decision-trees/${code}/versions`,
  );
  return data;
}

export async function createDecisionTree(
  payload: DecisionTreeCreatePayload,
): Promise<DecisionTreeDetail> {
  const { data } = await apiClient.post<DecisionTreeDetail>(
    "/v1/decision-trees",
    payload,
  );
  return data;
}

export async function appendDecisionTreeVersion(
  code: string,
  payload: DecisionTreeVersionCreatePayload,
): Promise<DecisionTreeDetail> {
  const { data } = await apiClient.post<DecisionTreeDetail>(
    `/v1/decision-trees/${code}/versions`,
    payload,
  );
  return data;
}

export async function publishDecisionTreeVersion(
  code: string,
  version: number,
): Promise<{ code: string; version: number; published_at: string }> {
  const { data } = await apiClient.post<{
    code: string;
    version: number;
    published_at: string;
  }>(`/v1/decision-trees/${code}/versions/${version}:publish`);
  return data;
}

export async function dryRunDecisionTree(
  code: string,
  payload: DryRunPayload,
): Promise<DryRunResponse> {
  const { data } = await apiClient.post<DryRunResponse>(
    `/v1/decision-trees/${code}:dry-run`,
    payload,
  );
  return data;
}
