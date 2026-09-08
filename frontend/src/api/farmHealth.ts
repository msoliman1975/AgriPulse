// The Farm Health View reads — what each decision tree says about a farm's
// blocks and grid cells.
//
// A verdict row exists for every leaf a tree reached, including the ones
// that found nothing wrong. **No row means the tree did not run there.**
// That absence is information, and it is why the farm read omits a block
// rather than returning it empty: this endpoint cannot tell "no tree ran
// here" from "no such block", and an empty entry would invite the map to
// paint a confident grey over the second case.
import { apiClient } from "./client";

/**
 * The five platform status codes, worst last. The order is the rank: a
 * block holding one `issue` and six `good` reads as an issue.
 *
 * Declared here for typing only. The colours and labels come from the
 * server — see {@link getVerdictStatuses} — because a copy of a backend
 * list in the bundle is how the two drift.
 */
export const STATUS_CODES = ["na", "very_good", "good", "issue", "alert"] as const;
export type StatusCode = (typeof STATUS_CODES)[number];

/** The four leaf kinds a tree can end in. */
export type LeafKind = "alert" | "recommendation" | "status" | "no_action";

export interface StatusDefinition {
  code: StatusCode;
  /** Highest wins when one block holds several verdicts. `na` is 0. */
  rank: number;
  /** Hex, from the platform list. The map paints this. */
  color: string;
  label_en: string;
  label_ar: string;
}

export interface Verdict {
  id: string;
  farm_id: string;
  block_id: string;
  /** Null for a whole-block verdict; set for one grid cell. */
  cell_id: string | null;
  /** Resolved from grid_cells, so a reader can say "R2·C3", not a UUID. */
  cell_row: number | null;
  cell_col: number | null;
  scope: string;
  tree_id: string;
  tree_code: string;
  tree_version: number;
  leaf_node_id: string;
  kind: LeafKind;
  status_code: StatusCode;
  /** Set on alert and recommendation verdicts only. */
  severity: string | null;
  text_en: string;
  text_ar: string | null;
  /** The interval this answer has held. `valid_to` null while current. */
  valid_from: string;
  valid_to: string | null;
  last_evaluated_at: string;
  alert_id: string | null;
  recommendation_id: string | null;
}

export interface BlockVerdicts {
  block_id: string;
  as_of: string | null;
  /** The worst status across the block, which is what it reads as. */
  worst_status: StatusCode | null;
  last_evaluated_at: string | null;
  verdicts: Verdict[];
}

export interface FarmVerdicts {
  farm_id: string;
  as_of: string | null;
  blocks: BlockVerdicts[];
}

/** The legend. Served rather than shipped in the bundle. */
export async function getVerdictStatuses(): Promise<StatusDefinition[]> {
  const { data } = await apiClient.get<StatusDefinition[]>("/verdict-statuses");
  return data;
}

/**
 * Every block of one farm, with what each tree says about it.
 *
 * `at` replays a past instant. Omitted, the current answers come back.
 */
export async function getFarmVerdicts(farmId: string, at?: string): Promise<FarmVerdicts> {
  const { data } = await apiClient.get<FarmVerdicts>(`/farms/${farmId}/verdicts`, {
    params: at ? { at } : undefined,
  });
  return data;
}

/**
 * One block's verdicts.
 *
 * `farm_id` is required because it is what the request is authorized
 * against. A farm-scoped user has no tenant-wide role to fall back on, so
 * omitting it is a silent 403 on a request that looks correct.
 */
export async function getBlockVerdicts(
  blockId: string,
  farmId: string,
  at?: string,
): Promise<BlockVerdicts> {
  const { data } = await apiClient.get<BlockVerdicts>(`/blocks/${blockId}/verdicts`, {
    params: at ? { farm_id: farmId, at } : { farm_id: farmId },
  });
  return data;
}
