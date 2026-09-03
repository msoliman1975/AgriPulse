// Which decision trees a farm runs.
//
// Mirrors the two routes in backend/app/modules/recommendations/router.py —
// keep in lock-step. Both need `farm.manage_config` on the farm, the same
// capability the rest of the farm settings drawer needs.
//
// The list is an opt-out: every tree is on until the farm turns it off, so a
// tree published after a farm last opened this screen reaches it anyway.

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
  enabled: boolean;
}

export interface FarmDecisionTreesResponse {
  farm_id: string;
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
