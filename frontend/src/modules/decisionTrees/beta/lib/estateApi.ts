/**
 * The estate dry run's API surface, and the run-results read.
 *
 * Kept beside the screens that use it rather than in
 * `@/api/decisionTreesBeta.ts`, which belongs to the designer. Both files
 * talk to the same `/v1/platform/decision-trees/beta` prefix; the split is by
 * owner, not by path, so a change to the designer's contract and a change to
 * this one are two diffs in two files.
 *
 * Four routes:
 *
 *   POST /v1/platform/decision-trees/beta/{tree_id}/estate-dry-run
 *   GET  /v1/platform/decision-trees/beta/{tree_id}/estate-dry-run/{run_id}
 *   GET  /v1/platform/decision-trees/beta/{tree_id}/estate-dry-runs
 *   GET  /v1/platform/decision-trees/beta/{tree_id}/runs
 *
 * **Every one of them names its tenant.** A platform admin has no tenant of
 * their own, so `tenant_id` is a parameter rather than something read off the
 * caller. A tenant-scoped caller may leave it out and gets their own.
 *
 * Shapes follow docs/proposals/unified-decision-tree-engine.md section 9.
 */

import { apiClient } from "@/api/client";

const BETA_TREES = "/v1/platform/decision-trees/beta";

/** One row of the finding-set table. */
export interface EstateFindingSet {
  codes: string[];
  /** `{dry, ndvi_low}` — what the report calls this set. */
  label: string;
  count: number;
  share_pct: number;
  /** The combination rule that matched, or null when the text was composed. */
  matched_rule: string | null;
  composed: boolean;
  composed_count: number;
  blocks: number;
  status: string | null;
  severity: string | null;
  action_type: string | null;
  text_en: string | null;
}

export interface EstateErrorByNode {
  node_id: string;
  count: number;
  share_pct: number;
  example: string | null;
}

export interface EstateSlowBlock {
  block_id: string;
  block_name: string | null;
  farm_name: string | null;
  cells: number;
  duration_ms: number;
}

export interface EstateBlockFailure {
  block_id: string;
  block_name: string | null;
  error: string | null;
}

/** The report document. Empty while the run is still `running`. */
export interface EstateReport {
  scope?: string;
  blocks_evaluated?: number;
  blocks_not_targeted?: number;
  blocks_failed?: number;
  block_failures?: EstateBlockFailure[];
  cells_evaluated?: number;
  cells_no_findings?: number;
  cells_no_findings_pct?: number;
  cells_carded?: number;
  cells_errored?: number;
  cells_errored_pct?: number;
  finding_sets?: EstateFindingSet[];
  other_sets?: { sets: number; cells: number };
  rules_defined?: number;
  rules_fired?: number;
  rules_never_fired?: string[];
  composed_cells?: number;
  composed_share_pct?: number;
  errors?: { count: number; by_node: EstateErrorByNode[] };
  timing?: {
    total_ms: number;
    per_cell_ms: number;
    includes?: string;
    slowest_blocks?: EstateSlowBlock[];
    node_timing?: { available: boolean; reason: string };
  };
}

export type EstateRunState = "running" | "done" | "failed";

export interface EstateRunSummary {
  id: string;
  tree_id: string;
  tree_code: string;
  tree_name: string | null;
  version_id: string | null;
  scope: string;
  state: EstateRunState;
  requested_by: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  blocks_evaluated: number;
  blocks_failed: number;
  cells_evaluated: number;
  cells_errored: number;
  error: string | null;
}

export interface EstateRun extends EstateRunSummary {
  report: EstateReport;
}

export interface EstateRunStarted {
  run_id: string;
  tenant_id: string;
  tree_id: string;
  tree_code: string;
  scope: string;
  state: EstateRunState;
}

/** One block-and-finding-set group from a real run, read from the traces. */
export interface BetaRunResultRow {
  run_id: string;
  block_id: string;
  block_name: string | null;
  block_name_ar: string | null;
  farm_id: string | null;
  farm_name: string | null;
  tree_id: string;
  tree_code: string;
  /** Joined from the catalogue; a trace row carries no tree name. */
  tree_name: string | null;
  tree_name_ar: string | null;
  tree_version: number | null;
  scope: string;
  status: string;
  finding_set: string[];
  matched_rule: string | null;
  registered_by: Record<string, string[]>;
  cells: number;
  cards_opened: number;
  recommendation_id: string | null;
  errored: number;
  last_evaluated_at: string | null;
}

/** `tenant_id` is omitted for a tenant-scoped caller, who has only one. */
function tenantParams(tenantId: string | null): Record<string, string> | undefined {
  return tenantId ? { tenant_id: tenantId } : undefined;
}

export async function startEstateDryRun(
  treeId: string,
  tenantId: string,
  blockLimit?: number,
): Promise<EstateRunStarted> {
  const { data } = await apiClient.post<EstateRunStarted>(
    `${BETA_TREES}/${treeId}/estate-dry-run`,
    blockLimit ? { tenant_id: tenantId, block_limit: blockLimit } : { tenant_id: tenantId },
  );
  return data;
}

export async function getEstateDryRun(
  treeId: string,
  runId: string,
  tenantId: string | null,
): Promise<EstateRun> {
  const { data } = await apiClient.get<EstateRun>(
    `${BETA_TREES}/${treeId}/estate-dry-run/${runId}`,
    { params: tenantParams(tenantId) },
  );
  return { ...data, report: data.report ?? {} };
}

export async function listEstateDryRuns(
  treeId: string,
  tenantId: string | null,
): Promise<EstateRunSummary[]> {
  const { data } = await apiClient.get<EstateRunSummary[]>(
    `${BETA_TREES}/${treeId}/estate-dry-runs`,
    { params: tenantParams(tenantId) },
  );
  return Array.isArray(data) ? data : [];
}

export async function listBetaRunResults(
  treeId: string,
  tenantId: string | null,
): Promise<BetaRunResultRow[]> {
  const { data } = await apiClient.get<BetaRunResultRow[]>(`${BETA_TREES}/${treeId}/runs`, {
    params: tenantParams(tenantId),
  });
  return Array.isArray(data) ? data : [];
}
