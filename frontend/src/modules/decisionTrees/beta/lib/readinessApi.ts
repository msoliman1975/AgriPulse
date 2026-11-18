/**
 * Tree readiness (decision D15): what a tree needs, and which blocks have it.
 *
 *   GET /v1/platform/decision-trees/beta/{tree_id}/readiness
 *       per-block view, for a tenant caller (a platform caller gets counts only)
 *   GET /v1/platform/decision-trees/beta/{tree_id}/readiness-summary
 *       counts per tenant, for a platform admin
 *
 * Requirements are read from the tree's own definition by the server, so this
 * screen never keeps a list of its own.
 */

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/api/client";

const BETA_TREES = "/v1/platform/decision-trees/beta";

export type ReadinessKind =
  | "block_field"
  | "crop_attribute"
  | "reference"
  | "heat_units"
  | "signal"
  | "index"
  | "weather"
  | "water_balance"
  | "grid";

export const READINESS_KINDS: readonly ReadinessKind[] = [
  "block_field",
  "crop_attribute",
  "reference",
  "heat_units",
  "signal",
  "water_balance",
  "index",
  "grid",
  "weather",
];

export type ReadinessStatus = "ready" | "partial" | "not_ready";

export const READINESS_STATUSES: readonly ReadinessStatus[] = ["ready", "partial", "not_ready"];

export interface ReadinessRequirement {
  kind: ReadinessKind;
  key: string;
}

export interface ReadinessCounts {
  ready: number;
  partial: number;
  not_ready: number;
}

export interface ReadinessBlock {
  block_id: string;
  block_code: string | null;
  block_name: string | null;
  block_name_ar: string | null;
  farm_id: string | null;
  farm_name: string | null;
  farm_name_ar: string | null;
  status: ReadinessStatus;
  met: number;
  total: number;
  missing: ReadinessRequirement[];
}

interface ReadinessNotes {
  readiness_note_en: string | null;
  readiness_note_ar: string | null;
}

export interface TreeReadiness extends ReadinessNotes {
  tree_id: string;
  tree_code: string;
  version_id: string | null;
  requirements: ReadinessRequirement[];
  blocks_targeted: number;
  blocks_assessed: number;
  counts: ReadinessCounts;
  blocks: ReadinessBlock[];
}

export interface ReadinessTenantCounts {
  tenant_id: string;
  tenant_name: string | null;
  blocks_targeted: number;
  counts: ReadinessCounts;
  error: string | null;
}

export interface TreeReadinessSummary extends ReadinessNotes {
  tree_id: string;
  requirements: ReadinessRequirement[];
  tenants: ReadinessTenantCounts[];
}

export async function getTreeReadiness(treeId: string): Promise<TreeReadiness> {
  const { data } = await apiClient.get<TreeReadiness>(`${BETA_TREES}/${treeId}/readiness`);
  return { ...data, blocks: data.blocks ?? [] };
}

export async function getTreeReadinessSummary(treeId: string): Promise<TreeReadinessSummary> {
  const { data } = await apiClient.get<TreeReadinessSummary>(
    `${BETA_TREES}/${treeId}/readiness-summary`,
  );
  return { ...data, tenants: data.tenants ?? [] };
}

const KEY = ["decision_trees_readiness"] as const;

export function useTreeReadiness(treeId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: [...KEY, "tenant", treeId] as const,
    queryFn: () => getTreeReadiness(treeId!),
    enabled: enabled && Boolean(treeId),
    // Always re-read on mount and on focus. The fix links send the user to
    // another page to set the missing data; with a minute of staleness the
    // list they came back to still said "Missing" for what they just set.
    staleTime: 0,
  });
}

export function useTreeReadinessSummary(treeId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: [...KEY, "summary", treeId] as const,
    queryFn: () => getTreeReadinessSummary(treeId!),
    enabled: enabled && Boolean(treeId),
    staleTime: 60_000,
  });
}

/** Block fields set on the block edit form. `growth_stage` is not one: it
 *  belongs to the current crop assignment, like crop attributes. */
const EDIT_FORM_FIELDS = new Set(["soil_texture", "salinity_class"]);

/**
 * Where a tenant admin fixes a missing item, or null when the block cannot.
 *
 *   * soil texture, salinity class: the block edit form;
 *   * growth stage, crop attributes, heat-unit start: the current crop's
 *     settings on the block page (`#crop-settings`);
 *   * crop reference values: nowhere on the block. They are set per crop in
 *     the platform crop catalogue, so the row says so instead of linking;
 *   * scout records, imagery, weather, water balance, the grid: the block.
 *
 * `returnTo` (the designer's own URL) rides along so the page offers the way
 * back and the edit form returns there on save.
 */
export function readinessFixPath(
  block: ReadinessBlock,
  req: ReadinessRequirement,
  returnTo: string | null = null,
): string | null {
  if (!block.farm_id || req.kind === "reference") return null;
  const base = `/farms/${block.farm_id}/blocks/${block.block_id}`;
  const query = returnTo ? `?returnTo=${encodeURIComponent(returnTo)}` : "";
  if (req.kind === "block_field" && EDIT_FORM_FIELDS.has(req.key)) return `${base}/edit${query}`;
  if (req.kind === "block_field" || req.kind === "crop_attribute" || req.kind === "heat_units") {
    return `${base}${query}#crop-settings`;
  }
  return `${base}${query}`;
}
