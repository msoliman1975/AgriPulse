// Platform-admin reads and writes for the block health definition
// (public migration 0095). Two tiers live here: the platform default, one
// row, and one partial row per crop path. See
// `backend/app/modules/health/admin_router.py`.
//
// The platform's rollup rule is not part of the platform body. It is the
// platform default `health.cell_rollup` (and `health.cell_share_pct`), and
// it is written through `updatePlatformDefault` like every other default.

import { apiClient } from "./client";

export type HealthClass = "healthy" | "watch" | "critical";
export type CellRollup = "worst" | "share" | "most_common";

/** Every key a health definition can hold. A crop row holds any subset. */
export interface HealthDefinitionValues {
  severity_map: Record<"critical" | "warning" | "info", HealthClass>;
  counted_statuses: string[];
  snoozed_as: HealthClass | null;
  cell_critical_share: number | null;
  recommendation_floor: number | null;
  stale_after_hours: number;
  no_tree_coverage: "unknown" | "healthy";
  cell_rollup: CellRollup;
}

export type HealthKey = keyof HealthDefinitionValues;
export type HealthBody = Partial<HealthDefinitionValues>;

/** The keys the platform row holds: all of them except the rollup rule. */
export const PLATFORM_HEALTH_KEYS: readonly HealthKey[] = [
  "stale_after_hours",
  "no_tree_coverage",
  "counted_statuses",
  "snoozed_as",
  "severity_map",
  "cell_critical_share",
  "recommendation_floor",
];

/** The keys a crop row may set. */
export const CROP_HEALTH_KEYS: readonly HealthKey[] = [...PLATFORM_HEALTH_KEYS, "cell_rollup"];

export interface PlatformHealthDefinition {
  definition: Omit<HealthDefinitionValues, "cell_rollup">;
  version: number;
  notes: string | null;
  updated_at: string;
  updated_by: string | null;
  rollup: { cell_rollup: CellRollup; cell_share_pct: number | null };
}

export interface CropHealthDefinition {
  crop_path: string;
  definition: HealthBody;
  version: number;
  notes: string | null;
  updated_at: string;
  updated_by: string | null;
}

export interface InheritedValue {
  value: unknown;
  /** "platform", or the crop path whose row set it. */
  source: string;
}

export interface CropPathHealth {
  crop_path: string;
  own: CropHealthDefinition | null;
  inherited: Partial<Record<HealthKey, InheritedValue>>;
}

const BASE = "/v1/admin/health-definitions";

export async function getPlatformHealthDefinition(): Promise<PlatformHealthDefinition> {
  const { data } = await apiClient.get<PlatformHealthDefinition>(`${BASE}/platform`);
  return data;
}

export async function putPlatformHealthDefinition(
  definition: HealthBody,
  notes: string | null,
): Promise<PlatformHealthDefinition> {
  const { data } = await apiClient.put<PlatformHealthDefinition>(`${BASE}/platform`, {
    definition,
    notes,
  });
  return data;
}

export async function listCropHealthDefinitions(): Promise<CropHealthDefinition[]> {
  const { data } = await apiClient.get<CropHealthDefinition[]>(`${BASE}/crops`);
  return data;
}

export async function getCropPathHealth(cropPath: string): Promise<CropPathHealth> {
  const { data } = await apiClient.get<CropPathHealth>(
    `${BASE}/crops/${encodeURIComponent(cropPath)}`,
  );
  return data;
}

/** `{}` removes the row: the path then inherits every key. */
export async function putCropPathHealth(
  cropPath: string,
  definition: HealthBody,
  notes: string | null,
): Promise<CropPathHealth> {
  const { data } = await apiClient.put<CropPathHealth>(
    `${BASE}/crops/${encodeURIComponent(cropPath)}`,
    { definition, notes },
  );
  return data;
}
