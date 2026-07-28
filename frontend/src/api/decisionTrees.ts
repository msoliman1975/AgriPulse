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

export type TransferabilityGrade =
  | "very_high"
  | "high"
  | "medium"
  | "low"
  | "not_applicable";

export interface TreeTransferability {
  egypt: TransferabilityGrade | null;
  middle_east: TransferabilityGrade | null;
  global: TransferabilityGrade | null;
}

// Pull the provenance blocks out of an untyped compiled tree. Tolerant
// of the legacy shape (keys absent) — returns nulls so callers render
// nothing rather than crashing on an older version's compiled JSON.
export function readTreeProvenance(
  compiled: Record<string, unknown> | null | undefined,
): { evidence: TreeEvidence | null; transferability: TreeTransferability | null } {
  const ev = compiled?.evidence;
  const tr = compiled?.transferability;
  return {
    evidence:
      ev && typeof ev === "object" ? (ev as TreeEvidence) : null,
    transferability:
      tr && typeof tr === "object" ? (tr as TreeTransferability) : null,
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

export interface DryRunResponse {
  matched: boolean;
  outcome: {
    action_type: string;
    severity: string;
    confidence: string;
    parameters: Record<string, unknown>;
    text_en: string;
    text_ar: string | null;
    valid_for_hours: number | null;
  } | null;
  path: TreePathStepDTO[];
  evaluation_snapshot: Record<string, unknown>;
  error: string | null;
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
  const { data } = await apiClient.patch<DecisionTreeDetail>(
    `/v1/decision-trees/${code}`,
    payload,
  );
  return data;
}

export async function archiveDecisionTree(code: string): Promise<void> {
  await apiClient.delete(`/v1/decision-trees/${code}`);
}

export async function restoreDecisionTree(code: string): Promise<DecisionTreeDetail> {
  const { data } = await apiClient.post<DecisionTreeDetail>(
    `/v1/decision-trees/${code}:restore`,
  );
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
