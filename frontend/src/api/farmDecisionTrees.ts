// Which decision trees a farm runs.
//
// Mirrors the two routes in backend/app/modules/recommendations/router.py —
// keep in lock-step. Both need `farm.manage_config` on the farm, the same
// capability the rest of the farm settings drawer needs.
//
// The list is an opt-out: every tree is on until the farm turns it off, so a
// tree published after a farm last opened this screen reaches it anyway.
//
// Only trees that match at least one active block (crop, country, soil) are
// listed, and none until a block carries a crop (`has_crops`). A third route,
// the impact preview, says what a pending crop/soil/country/block change
// would start and stop before it is saved.

import { apiClient } from "./client";

export interface FarmDecisionTree {
  tree_id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  scope: string;
  version: number;
  /** `platform` for a shipped tree, `tenant` for one this tenant authored. */
  source: "platform" | "tenant";
  crop_paths: string[];
  country_codes?: string[];
  soil_textures?: string[];
  /** Active blocks of the farm this tree matches. */
  blocks_matched: number;
  enabled: boolean;
}

export interface FarmDecisionTreesResponse {
  farm_id: string;
  /** False when no active block carries a crop; `trees` is then empty. */
  has_crops: boolean;
  blocks_total: number;
  trees: FarmDecisionTree[];
}

export interface FarmDecisionTreeToggle {
  tree_id: string;
  code: string;
  enabled: boolean;
  /** False when the tree was already in that state; nothing was written. */
  changed: boolean;
}

export async function listFarmDecisionTrees(farmId: string): Promise<FarmDecisionTreesResponse> {
  const { data } = await apiClient.get<FarmDecisionTreesResponse>(
    `/v1/farms/${farmId}/decision-trees`,
  );
  return data;
}

export async function setFarmDecisionTree(
  farmId: string,
  treeId: string,
  enabled: boolean,
): Promise<FarmDecisionTreeToggle> {
  const { data } = await apiClient.put<FarmDecisionTreeToggle>(
    `/v1/farms/${farmId}/decision-trees/${treeId}`,
    { enabled },
  );
  return data;
}

// ---- Impact preview -------------------------------------------------------

/** One block as it would be after the pending change. Send only what moves. */
export interface TreeImpactBlockChange {
  block_id: string;
  /** The crop replacing the current one (with its variety/strain). */
  crop_id?: string;
  crop_variety_id?: string | null;
  crop_variety_strain_id?: string | null;
  /** The block's crop is ended or removed. */
  crop_removed?: boolean;
  soil_texture?: string | null;
  /** The block is archived or inactivated. */
  removed?: boolean;
}

export interface TreeImpactRequest {
  blocks?: TreeImpactBlockChange[];
  /** Include only to preview a country change; null clears it. */
  country_code?: string | null;
}

export interface TreeImpactTree {
  tree_id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  /** False when the farm turned this tree off. */
  enabled: boolean;
  /** Per-block lists: other blocks of the farm it still runs on afterwards. */
  other_blocks?: number | null;
  /** Farm lists: blocks it runs on afterwards. */
  blocks?: number | null;
}

export interface TreeImpactBlock {
  block_id: string;
  label: string | null;
  label_ar: string | null;
  starting: TreeImpactTree[];
  stopping: TreeImpactTree[];
}

export interface TreeImpactResponse {
  farm_id: string;
  has_crops_before: boolean;
  has_crops_after: boolean;
  blocks: TreeImpactBlock[];
  farm_starting: TreeImpactTree[];
  farm_stopping: TreeImpactTree[];
  exclusions_cleared: TreeImpactTree[];
  changes_anything: boolean;
}

export async function previewFarmTreeImpact(
  farmId: string,
  change: TreeImpactRequest,
): Promise<TreeImpactResponse> {
  const { data } = await apiClient.post<TreeImpactResponse>(
    `/v1/farms/${farmId}/decision-tree-impact`,
    change,
  );
  return data;
}
