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
  const { data } = await apiClient.get<StatusDefinition[]>("/v1/verdict-statuses");
  return data;
}

/**
 * Every block of one farm, with what each tree says about it.
 *
 * `at` replays a past instant. Omitted, the current answers come back.
 */
export async function getFarmVerdicts(farmId: string, at?: string): Promise<FarmVerdicts> {
  const { data } = await apiClient.get<FarmVerdicts>(`/v1/farms/${farmId}/verdicts`, {
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
  const { data } = await apiClient.get<BlockVerdicts>(`/v1/blocks/${blockId}/verdicts`, {
    params: at ? { farm_id: farmId, at } : { farm_id: farmId },
  });
  return data;
}

/** One step of the walk a tree took, as the trace records it. */
export interface WalkStep {
  node_id: string;
  matched: boolean;
  label_en?: string | null;
  label_ar?: string | null;
  /** The comparison, as the compiled tree holds it. Shape varies by operator. */
  condition?: Record<string, unknown> | null;
  /** The refs this node read, already resolved. */
  values?: Record<string, unknown> | null;
}

export interface VerdictReasoning {
  verdict_id: string;
  block_id: string;
  cell_id: string | null;
  cell_row: number | null;
  cell_col: number | null;
  scope: string;
  tree_id: string;
  tree_code: string;
  tree_version: number;
  leaf_node_id: string;
  kind: LeafKind;
  status_code: StatusCode;
  severity: string | null;
  valid_from: string;
  last_evaluated_at: string;
  /**
   * False when retention has pruned the run behind this verdict. The verdict
   * still stands and its status is still correct; only the walk is gone, and
   * the screen says so rather than showing an empty step list.
   */
  reasoning_available: boolean;
  trace_id: string | null;
  evaluated_at: string | null;
  node_path: WalkStep[];
  resolved_values: Record<string, unknown>;
  param_overrides: Record<string, unknown>;
}

/**
 * The walk behind one verdict.
 *
 * Not `/decision-tree-traces/{id}`: that endpoint is gated on
 * `decision_tree.read`, which FarmManager, Agronomist, FieldOperator, Scout
 * and Viewer do not hold. Every reader of this screen would get a 403 on the
 * one request that explains the colour they are looking at.
 */
export async function getVerdictReasoning(
  blockId: string,
  verdictId: string,
  farmId: string,
): Promise<VerdictReasoning> {
  const { data } = await apiClient.get<VerdictReasoning>(
    `/v1/blocks/${blockId}/verdicts/${verdictId}/reasoning`,
    { params: { farm_id: farmId } },
  );
  return data;
}

export interface FarmVerdictHistory {
  farm_id: string;
  from_at: string;
  to_at: string;
  tree_code: string | null;
  /**
   * True when the guard cut the list. The caller has more history than a
   * replay can draw and should narrow the window or name a tree, rather than
   * draw a map that is quietly missing rows.
   */
  truncated: boolean;
  verdicts: Verdict[];
}

/**
 * Every verdict that stood at any point in a window, as intervals.
 *
 * One request for a whole replay. One row per change, not per day: a block
 * holding the same verdict for a month is a single row, and the client
 * rebuilds each day's frame from the intervals.
 */
export async function getFarmVerdictHistory(
  farmId: string,
  from: string,
  to: string,
  treeCode?: string | null,
): Promise<FarmVerdictHistory> {
  const { data } = await apiClient.get<FarmVerdictHistory>(
    `/v1/farms/${farmId}/verdict-history`,
    { params: { from, to, ...(treeCode ? { tree_code: treeCode } : {}) } },
  );
  return data;
}
