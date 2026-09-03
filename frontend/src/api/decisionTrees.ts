// Mirrors backend/app/modules/recommendations/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export interface DecisionTree {
  id: string;
  code: string;
  // NULL = platform-shipped tree (read-only to tenants); non-NULL = the
  // caller's own tenant-authored tree (editable / archivable).
  tenant_id: string | null;
  name_en: string;
  name_ar: string | null;
  description_en: string | null;
  description_ar: string | null;
  crop_id: string | null;
  // Multi-axis targeting sets (DT targeting PR-2/PR-5). Empty = matches any.
  crop_paths: string[];
  country_codes: string[];
  soil_textures: string[];
  // Execution granularity (PR-C1): "block" (default) or "cell".
  scope: "block" | "cell";
  applicable_regions: string[];
  is_active: boolean;
  current_version: number | null;
  // Soft-delete flag (experience redesign). Archived trees are hidden from
  // the default catalog + never evaluated, but stay restorable.
  archived: boolean;
}

// Catalog filter for the list endpoint's `status` query param.
export type DecisionTreeListStatus = "active" | "archived" | "all";

// Scientific-provenance metadata (KB P1-A). Lives inside `tree_compiled`
// (the backend folds it in at compile time); these mirror the shapes
// produced by recommendations/loader.py. Optional — absent on trees that
// don't declare an `evidence:` / `transferability:` block.
export type EvidenceConfidence = "very_high" | "high" | "medium" | "low";

export type CitationSourceType =
  | "peer_reviewed"
  | "fao"
  | "usda"
  | "extension"
  | "university"
  | "research_institution"
  | "remote_sensing"
  | "government";

export interface TreeCitation {
  source_type: CitationSourceType;
  title: string;
  doi: string | null;
  url: string | null;
  year: number | null;
}

export interface TreeEvidence {
  confidence: EvidenceConfidence;
  notes: string | null;
  citations: TreeCitation[];
}

export type TransferabilityGrade = "very_high" | "high" | "medium" | "low" | "not_applicable";

export interface TreeTransferability {
  egypt: TransferabilityGrade | null;
  middle_east: TransferabilityGrade | null;
  global: TransferabilityGrade | null;
}

// Pull the provenance blocks out of an untyped compiled tree. Tolerant
// of the legacy shape (keys absent) — returns nulls so callers render
// nothing rather than crashing on an older version's compiled JSON.
export function readTreeProvenance(compiled: Record<string, unknown> | null | undefined): {
  evidence: TreeEvidence | null;
  transferability: TreeTransferability | null;
} {
  const ev = compiled?.evidence;
  const tr = compiled?.transferability;
  return {
    evidence: ev && typeof ev === "object" ? (ev as TreeEvidence) : null,
    transferability: tr && typeof tr === "object" ? (tr as TreeTransferability) : null,
  };
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
  // Multi-axis targeting sets (DT targeting PR-2). Empty set = matches any.
  crop_paths: string[];
  country_codes: string[];
  soil_textures: string[];
  versions: DecisionTreeVersion[];
}

// One block the tree would target (dry-run picker, PR-4).
export interface DryRunCandidateBlock {
  block_id: string;
  label: string;
  /** The same "Farm / Block" label from the Arabic columns. Null when
   *  neither half has an Arabic name; the reader falls back to `label`. */
  label_ar: string | null;
}

export interface DecisionTreeCreatePayload {
  code: string;
  crop_code?: string | null;
  // Multi-axis targeting from the authoring pickers (PR-5). Injected into the
  // compiled spec server-side; omit to leave whatever the YAML declares.
  crop_paths?: string[];
  country_codes?: string[];
  soil_textures?: string[];
  scope?: "block" | "cell";
  tree_yaml: string;
}

export interface DecisionTreeVersionCreatePayload {
  tree_yaml: string;
  notes?: string | null;
}

// Editable tree-level metadata (experience redesign). Full-replace: the
// metadata panel always sends the complete set. Crop targeting is required.
export interface DecisionTreeUpdatePayload {
  name_en: string;
  name_ar?: string | null;
  description_en?: string | null;
  description_ar?: string | null;
  crop_paths: string[];
  country_codes: string[];
  soil_textures: string[];
  scope: "block" | "cell";
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

/** One grid cell's verdict in a `scope: cell` dry-run. */
export interface DryRunCell {
  cell_id: string;
  cell_row: number | null;
  cell_col: number | null;
  matched: boolean;
  action_type: string | null;
  severity: string | null;
  text_en: string | null;
  error: string | null;
}

/**
 * Whether the tree's crop / country / soil filters admit this block.
 * Reported, never enforced — the dry-run evaluates either way, but a tree the
 * sweep would skip here no longer looks like one that runs.
 */
export interface DryRunTargeting {
  matched: boolean;
  axis: "crop" | "country" | "soil" | null;
  required: string[];
  /** null = the block (or its farm, for country) has no value on that axis. */
  actual: string | null;
}

export interface DryRunResponse {
  matched: boolean;
  scope: "block" | "cell";
  targeting: DryRunTargeting | null;
  outcome: {
    action_type: string;
    severity: string;
    confidence: string;
    parameters: Record<string, unknown>;
    text_en: string;
    text_ar: string | null;
    valid_for_hours: number | null;
  } | null;
  // For a cell-scoped tree these describe one representative cell (the first
  // that fired, else the first evaluated) — a cell-scoped tree has no single
  // block-level verdict. `cells` carries every cell's answer.
  path: TreePathStepDTO[];
  evaluation_snapshot: Record<string, unknown>;
  error: string | null;
  cells_evaluated: number;
  cells_matched: number;
  cells: DryRunCell[];
}

// --- On-demand tree run (authoring) ----------------------------------------
//
// The dry-run's counterpart: `:dry-run` previews, `:run` commits. A run
// evaluates the tree's *published* version across a whole farm and opens
// real recommendations in the Action Center — there is deliberately no
// draft-YAML mode, because a recommendation names the version that produced
// it.

/** One farm the tree targets. `blocks_targeted` is what the run would walk. */
export interface TreeRunCandidateFarm {
  farm_id: string;
  name: string;
  name_ar: string | null;
  blocks_total: number;
  blocks_targeted: number;
}

export interface TreeRunPayload {
  farm_id: string;
}

/** What the run did on one block of the farm. */
export interface TreeRunBlockResult {
  block_id: string;
  label: string;
  label_ar: string | null;
  /** 0 when this block's crop / country / soil excluded the tree. */
  trees_evaluated: number;
  skipped_targeting: boolean;
  recommendations_opened: number;
  fired: number;
  /** Fired, but an open recommendation from this tree already existed. */
  deduped: number;
  errors: number;
}

export interface TreeRunResponse {
  run_id: string;
  farm_id: string;
  tree_code: string;
  tree_version: number;
  scope: "block" | "cell";
  blocks_evaluated: number;
  blocks_targeted: number;
  recommendations_opened: number;
  /** Why a re-run legitimately opens nothing. Never let this read as failure. */
  deduped: number;
  cleared: number;
  errors: number;
  traces_written: number;
  blocks: TreeRunBlockResult[];
}

// --- Evaluation lineage (tenant 0062) --------------------------------------

export type EvalRunKind = "sweep" | "on_demand";
export type EvalTraceStatus = "fired" | "clear" | "skipped" | "error";

export interface EvalRun {
  id: string;
  kind: EvalRunKind;
  actor_user_id: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  blocks_evaluated: number;
  trees_evaluated: number;
  trees_skipped: number;
  recommendations_opened: number;
  alerts_opened: number;
  traces_written: number;
  outcome: string;
  error: string | null;
}

export interface EvalTrace {
  id: string;
  run_id: string;
  evaluated_at: string;
  farm_id: string;
  block_id: string;
  block_name: string | null;
  block_name_ar: string | null;
  cell_id: string | null;
  cell_row: number | null;
  cell_col: number | null;
  tree_id: string;
  tree_code: string;
  tree_version: number;
  scope: "block" | "cell";
  status: EvalTraceStatus;
  /** Which targeting axis excluded the tree; only set when status=skipped. */
  // `farm` means the farm turned this tree off (tenant migration 0089);
  // the other three are the tree's own targeting axes.
  skip_axis: "crop" | "country" | "soil" | "farm" | null;
  skip_detail: { required?: string[]; actual?: string | null } | null;
  outcome: {
    kind?: string;
    action_type?: string;
    severity?: string;
    confidence?: string;
    leaf_node_id?: string | null;
    /** The tree fired but an open rec/alert already existed for this target. */
    deduped?: boolean;
  } | null;
  recommendation_id: string | null;
  alert_id: string | null;
  duration_ms: number | null;
  error: string | null;
}

export interface EvalTraceDetail extends EvalTrace {
  node_path: TreePathStepDTO[];
  /** Empty on a `clear` row by design — the walk is kept, the values are not. */
  resolved_values: Record<string, unknown>;
  param_overrides: Record<string, unknown>;
}

export interface EvalTraceFilters {
  run_id?: string;
  block_id?: string;
  farm_id?: string;
  tree_code?: string;
  status?: EvalTraceStatus[];
  limit?: number;
}

export async function listDecisionTrees(
  status: DecisionTreeListStatus = "active",
): Promise<DecisionTree[]> {
  const { data } = await apiClient.get<DecisionTree[]>("/v1/decision-trees", {
    params: { status },
  });
  return data;
}

export async function getDecisionTree(code: string): Promise<DecisionTreeDetail> {
  const { data } = await apiClient.get<DecisionTreeDetail>(`/v1/decision-trees/${code}`);
  return data;
}

export async function listDecisionTreeVersions(code: string): Promise<DecisionTreeVersion[]> {
  const { data } = await apiClient.get<DecisionTreeVersion[]>(
    `/v1/decision-trees/${code}/versions`,
  );
  return data;
}

export async function createDecisionTree(
  payload: DecisionTreeCreatePayload,
): Promise<DecisionTreeDetail> {
  const { data } = await apiClient.post<DecisionTreeDetail>("/v1/decision-trees", payload);
  return data;
}

export async function updateDecisionTree(
  code: string,
  payload: DecisionTreeUpdatePayload,
): Promise<DecisionTreeDetail> {
  const { data } = await apiClient.patch<DecisionTreeDetail>(`/v1/decision-trees/${code}`, payload);
  return data;
}

export async function archiveDecisionTree(code: string): Promise<void> {
  await apiClient.delete(`/v1/decision-trees/${code}`);
}

export async function restoreDecisionTree(code: string): Promise<DecisionTreeDetail> {
  const { data } = await apiClient.post<DecisionTreeDetail>(`/v1/decision-trees/${code}:restore`);
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

export async function listEvalRuns(limit = 50): Promise<EvalRun[]> {
  const { data } = await apiClient.get<EvalRun[]>("/v1/decision-tree-runs", {
    params: { limit },
  });
  return data;
}

export async function listEvalTraces(filters: EvalTraceFilters = {}): Promise<EvalTrace[]> {
  const { data } = await apiClient.get<EvalTrace[]>("/v1/decision-tree-traces", {
    params: {
      run_id: filters.run_id,
      block_id: filters.block_id,
      farm_id: filters.farm_id,
      tree_code: filters.tree_code,
      status: filters.status,
      limit: filters.limit ?? 200,
    },
  });
  return data;
}

// The drill-down. Separate from the list because the node walk and the
// resolved values are megabytes per page and only ever read one row at a time.
export async function getEvalTrace(traceId: string): Promise<EvalTraceDetail> {
  const { data } = await apiClient.get<EvalTraceDetail>(`/v1/decision-tree-traces/${traceId}`);
  return data;
}

// Blocks the tree would actually fire on (filtered by its crop/country/soil
// targeting) — populates the dry-run block picker.
export async function getDecisionTreeCandidateBlocks(
  code: string,
): Promise<DryRunCandidateBlock[]> {
  const { data } = await apiClient.get<DryRunCandidateBlock[]>(
    `/v1/decision-trees/${code}/candidate-blocks`,
  );
  return data;
}

// Farms the tree targets, with targeted-block counts — populates the run
// picker. Separate from candidate-blocks: a run is farm-wide, so the author
// picks a farm and the count tells them how much of it is in scope.
export async function getDecisionTreeCandidateFarms(code: string): Promise<TreeRunCandidateFarm[]> {
  const { data } = await apiClient.get<TreeRunCandidateFarm[]>(
    `/v1/decision-trees/${code}/candidate-farms`,
  );
  return data;
}

// Runs the published version for real: opens recommendations in the Action
// Center for every targeted block of the farm.
export async function runDecisionTreeOnFarm(
  code: string,
  payload: TreeRunPayload,
): Promise<TreeRunResponse> {
  const { data } = await apiClient.post<TreeRunResponse>(`/v1/decision-trees/${code}:run`, payload);
  return data;
}
