// REST bindings for tenant parameter overrides (PR-C consumer).
//
// Mirrors backend/app/modules/recommendations/schemas.py:
//   * TreeParameterDeclaration
//   * TreeParameterOverridesResponse
//   * TreeParameterOverrideUpsertRequest
//   * TreeParameterOverrideResponse
//
// One file per resource keeps the API surface flat — `decisionTrees.ts`
// holds tree CRUD; this file holds the parameter-override CRUD that
// PR-C exposed.

import { apiClient } from "./client";

export interface TreeParameterDeclaration {
  type: string;
  default: unknown;
  description?: string | null;
  min?: number | null;
  max?: number | null;
  values?: unknown[] | null; // only set for enum types
}

export interface TreeParameterOverridesResponse {
  code: string;
  tree_id: string;
  declarations: Record<string, TreeParameterDeclaration>;
  overrides: Record<string, unknown>;
}

export interface TreeParameterOverrideResponse {
  code: string;
  param_name: string;
  value: unknown;
}

export async function getTreeParameterOverrides(
  code: string,
): Promise<TreeParameterOverridesResponse> {
  const { data } = await apiClient.get<TreeParameterOverridesResponse>(
    `/v1/decision-trees/${code}/parameter-overrides`,
  );
  return data;
}

export async function upsertTreeParameterOverride(
  code: string,
  paramName: string,
  value: unknown,
): Promise<TreeParameterOverrideResponse> {
  const { data } = await apiClient.put<TreeParameterOverrideResponse>(
    `/v1/decision-trees/${code}/parameter-overrides/${encodeURIComponent(paramName)}`,
    { value },
  );
  return data;
}

export async function deleteTreeParameterOverride(
  code: string,
  paramName: string,
): Promise<void> {
  await apiClient.delete(
    `/v1/decision-trees/${code}/parameter-overrides/${encodeURIComponent(paramName)}`,
  );
}
