/** Crop reference values (decisions D18 and D23). Reads open; writes need platform.manage_crops. */

import { apiClient } from "./client";

export type ReferenceGroup = "salinity" | "yield" | "spacing";

export interface ReferenceKey {
  key: string;
  group: ReferenceGroup;
  unit: string;
  lower: number;
  upper: number;
}

/** Decimals arrive as strings from the API. */
type Num = string | number | null;

export interface ReferenceRow {
  crop_path: string;
  key: string;
  value: Num;
  value_min: Num;
  value_max: Num;
  note: string | null;
}

export interface ResolvedReference {
  value: Num;
  value_min: Num;
  value_max: Num;
  note: string | null;
  from_path: string;
}

export interface ReferenceView {
  crop_path: string;
  own: ReferenceRow[];
  resolved: Record<string, ResolvedReference>;
  plants_per_ha: number | null;
}

export interface ReferenceValueInput {
  value: number | null;
  value_min: number | null;
  value_max: number | null;
  note: string | null;
}

export async function listReferenceKeys(): Promise<ReferenceKey[]> {
  const { data } = await apiClient.get<ReferenceKey[]>("/v1/reference-values/keys");
  return Array.isArray(data) ? data : [];
}

export async function getReferenceValues(cropPath: string): Promise<ReferenceView> {
  const { data } = await apiClient.get<ReferenceView>(
    `/v1/reference-values/${encodeURIComponent(cropPath)}`,
  );
  return { ...data, own: data.own ?? [], resolved: data.resolved ?? {} };
}

export async function putReferenceValue(
  cropPath: string,
  key: string,
  input: ReferenceValueInput,
): Promise<ReferenceView> {
  const { data } = await apiClient.put<ReferenceView>(
    `/v1/admin/reference-values/${encodeURIComponent(cropPath)}/${key}`,
    input,
  );
  return data;
}

export async function deleteReferenceValue(cropPath: string, key: string): Promise<void> {
  await apiClient.delete(`/v1/admin/reference-values/${encodeURIComponent(cropPath)}/${key}`);
}

/** "60–72", "20 (18–28)", "4" — how a value reads on screen. */
export function formatReference(v: { value: Num; value_min: Num; value_max: Num }): string {
  const n = (x: Num): string => (x === null || x === undefined ? "" : String(Number(x)));
  const range =
    v.value_min !== null || v.value_max !== null
      ? `${n(v.value_min) || "…"}–${n(v.value_max) || "…"}`
      : "";
  if (v.value !== null && v.value !== undefined)
    return range ? `${n(v.value)} (${range})` : n(v.value);
  return range || "—";
}
