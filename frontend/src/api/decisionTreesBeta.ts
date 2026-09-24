/**
 * The beta decision-tree engine's API surface.
 *
 * One file on purpose: every call the beta designer makes to the server goes
 * through here, so the seam between the screens and the backend is in one
 * place and a contract change is one diff.
 *
 * Two things this file converts, and nothing else does:
 *
 *   1. **The definition travels as JSON, never as a YAML string.** The tree
 *      version row holds a `definition` JSONB column. YAML exists only inside
 *      the browser, as the editing buffer the pure helpers in
 *      `beta/lib/betaTree.ts` rewrite; `dumpBetaDoc` / `parseBetaDoc` convert
 *      at the page, and the wire never sees it.
 *   2. **A tree is addressed by id, the screens route by code.** The routes
 *      take `{tree_id}`; `/decision-trees-beta/:code` is what an author reads
 *      and links to. `resolveTreeId` turns one into the other off the list
 *      read, so no screen carries a uuid.
 *
 * Paths, and where each one came from:
 *
 *   /v1/platform/decision-trees/beta…   the pinned contract for session A.
 *   /v1/decision-tree-findings          the platform catalogue, as built on
 *   /v1/tenant/decision-tree-findings   `feat/dte-findings-catalogue`. The
 *                                       pinned contract said
 *                                       `/platform/decision-tree-findings`
 *                                       and one route for both tables; the
 *                                       branch that exists has two prefixes,
 *                                       neither of them `/platform/`.
 *
 * Three things about the finding routes, read off the router PR #700 shipped:
 *
 *   * They are two endpoints, not one. `listFindings` reads both and
 *     concatenates them, and `shadowed` comes back set on the tenant rows the
 *     platform table also defines.
 *   * Both list responses are an envelope, `{ findings: [...] }`, not a bare
 *     array. Unwrap `.findings`.
 *   * DELETE deactivates. It clears `is_active`, keeps the row, and answers
 *     204. Nothing on this screen may call it a delete.
 *
 * Shapes follow docs/proposals/unified-decision-tree-engine.md sections 6.1,
 * 6.2 and 6.5.
 */

import type {
  ActionType,
  FindingSeverity,
  FindingStatus,
} from "@/modules/decisionTrees/beta/lib/betaConstants";
import type { BetaTreeDoc } from "@/modules/decisionTrees/beta/lib/betaTree";
import type { AuthoringScope } from "@/modules/decisionTrees/lib/authoringScope";

import { listBlocks } from "./blocks";
import { apiClient } from "./client";
import { isApiError, type ProblemDetails } from "./errors";
import { listFarms } from "./farms";

const BETA_TREES = "/v1/platform/decision-trees/beta";
const PLATFORM_FINDINGS = "/v1/decision-tree-findings";
const TENANT_FINDINGS = "/v1/tenant/decision-tree-findings";

/** How many farms the dry-run block picker walks. A tenant with more farms
 *  than this picks the block from the farm console instead; the picker is a
 *  convenience, not the block catalogue. */
const DRY_RUN_FARM_LIMIT = 20;

// ---- Decision engine switch ------------------------------------------

const DECISION_ENGINE = "/v1/platform/decision-engine";

export type DecisionEngine = "old" | "beta";

/** What one flip closed in one tenant schema. */
export interface EngineCloseOutCounts {
  recommendations_expired: number;
  history_rows: number;
  alerts_resolved: number;
  verdicts_closed: number;
}

export interface DecisionEngineState {
  engine: DecisionEngine;
  switched_at: string | null;
  switched_by: string | null;
  last_close_out: {
    from: DecisionEngine;
    to: DecisionEngine;
    tenants: Record<string, EngineCloseOutCounts>;
  } | null;
  /** Set on a PUT only. False when the switch already held that engine. */
  changed?: boolean | null;
}

export async function getDecisionEngine(): Promise<DecisionEngineState> {
  const { data } = await apiClient.get<DecisionEngineState>(DECISION_ENGINE);
  return data;
}

export async function switchDecisionEngine(engine: DecisionEngine): Promise<DecisionEngineState> {
  const { data } = await apiClient.put<DecisionEngineState>(DECISION_ENGINE, { engine });
  return data;
}

// ---- Findings --------------------------------------------------------

export type FindingSource = "platform" | "tenant";

/** One row of a finding catalogue. `source` says which table it came from. */
export interface Finding {
  code: string;
  clause_en: string;
  clause_ar: string;
  name_en: string;
  name_ar: string;
  default_status: FindingStatus;
  description_en: string | null;
  description_ar: string | null;
  is_active: boolean;
  source: FindingSource;
  /**
   * A tenant row whose code also exists in the platform table. The fold
   * resolves platform first, so this row is never read (section 6.2). The
   * server computes it; always false on a platform row.
   */
  shadowed: boolean;
}

interface FindingListResponse {
  findings: Finding[];
}

/**
 * The editable fields, and only those.
 *
 * `code` is the identity and is not in here: it is stored in every
 * `recommendations.finding_set` that ever carried it. `is_active` is not
 * either — the catalogue model forbids unknown fields, and a row is retired
 * through DELETE rather than by writing the flag.
 */
export interface FindingWritePayload {
  clause_en: string;
  clause_ar: string;
  name_en: string;
  name_ar: string;
  default_status: FindingStatus;
  description_en?: string | null;
  description_ar?: string | null;
}

function findingsPath(source: FindingSource): string {
  return source === "platform" ? PLATFORM_FINDINGS : TENANT_FINDINGS;
}

/**
 * Both catalogues, resolved the way the fold resolves them.
 *
 * A platform caller has no tenant, so the tenant route cannot answer for
 * them and is not called. Calling it anyway would land a 403 in an empty
 * list, and an empty tenant table on screen would read as "this tenant has
 * written no codes" when the truth is "you are not in a tenant".
 */
export async function listFindings(
  scope: AuthoringScope,
  options: { includeInactive?: boolean } = {},
): Promise<Finding[]> {
  const params = options.includeInactive ? { include_inactive: true } : undefined;
  const platform = await apiClient.get<FindingListResponse>(PLATFORM_FINDINGS, { params });
  if (scope === "platform") return platform.data.findings;
  const tenant = await apiClient.get<FindingListResponse>(TENANT_FINDINGS, { params });
  return [...platform.data.findings, ...tenant.data.findings];
}

export async function createFinding(
  source: FindingSource,
  code: string,
  payload: FindingWritePayload,
): Promise<Finding> {
  const { data } = await apiClient.post<Finding>(findingsPath(source), { ...payload, code });
  return data;
}

export async function updateFinding(
  source: FindingSource,
  code: string,
  payload: FindingWritePayload,
): Promise<Finding> {
  const { data } = await apiClient.patch<Finding>(
    `${findingsPath(source)}/${encodeURIComponent(code)}`,
    payload,
  );
  return data;
}

/** Deactivate a code. Not a delete.
 *
 *  The row stays — every card that carried it still names it, and every tree
 *  that registers it still resolves — and `is_active` is cleared so it stops
 *  being offered. The backend handler is `deactivate_platform_finding`.
 *  204, no body. Nothing on this screen may call it a delete. */
export async function deactivateFinding(source: FindingSource, code: string): Promise<void> {
  await apiClient.delete(`${findingsPath(source)}/${encodeURIComponent(code)}`);
}

// ---- Trees -----------------------------------------------------------

export interface BetaTreeVersion {
  id: string;
  version: number;
  definition: BetaTreeDoc;
  published_at: string | null;
  created_at: string;
  notes: string | null;
}

export interface BetaTreeSummary {
  id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  /** NULL = platform-shipped; non-NULL = the caller's own tenant tree. */
  tenant_id: string | null;
  scope: "block" | "cell";
  /** The published version. `current_version_id` points at it, so a tree
   *  with a number here is live and one with null has never been published. */
  current_version: number | null;
  /** The unpublished draft on top of it, or null when there is none. */
  draft_version: number | null;
  updated_at: string;
}

export interface BetaTreeDetail extends BetaTreeSummary {
  versions: BetaTreeVersion[];
}

export interface BetaTreeCreatePayload {
  code: string;
  definition: BetaTreeDoc;
  notes?: string | null;
}

interface BetaTreeListResponse {
  trees?: BetaTreeSummary[];
  items?: BetaTreeSummary[];
}

/**
 * The newest version, whether it is a draft or the published one.
 *
 * The designer always opens on it. Kept here rather than in the page because
 * "newest" is a property of what the endpoint returns, and a server that
 * starts sorting the other way should be absorbed at the seam.
 */
export function latestVersion(tree: BetaTreeDetail): BetaTreeVersion | null {
  if (tree.versions.length === 0) return null;
  return tree.versions.reduce((best, v) => (v.version > best.version ? v : best));
}

/** The newest version when it is unpublished, else null. Only a draft can be
 *  discarded, and only a draft is what Save appends to. */
export function draftVersion(tree: BetaTreeDetail): BetaTreeVersion | null {
  const latest = latestVersion(tree);
  return latest && latest.published_at === null ? latest : null;
}

export async function listBetaTrees(): Promise<BetaTreeSummary[]> {
  const { data } = await apiClient.get<BetaTreeSummary[] | BetaTreeListResponse>(BETA_TREES);
  if (Array.isArray(data)) return data;
  return data.trees ?? data.items ?? [];
}

/**
 * A code to the id the routes take.
 *
 * Off the list read, and not cached here: a module-level map would answer
 * with a tree the caller has since lost access to, and the list is one small
 * request. React Query caches the list itself.
 */
export async function resolveBetaTreeId(code: string): Promise<string> {
  const trees = await listBetaTrees();
  const match = trees.find((t) => t.code === code);
  if (!match) throw new Error(`No beta tree with code "${code}".`);
  return match.id;
}

/** Normalise a detail body. A server that answers with the current
 *  definition and no version list still gives the designer something to
 *  open, rather than an empty canvas that reads as an empty tree. */
function normalizeDetail(raw: BetaTreeDetail & { definition?: BetaTreeDoc }): BetaTreeDetail {
  if (Array.isArray(raw.versions) && raw.versions.length > 0) return raw;
  if (!raw.definition) return { ...raw, versions: [] };
  return {
    ...raw,
    versions: [
      {
        id: `${raw.id}:current`,
        version: raw.current_version ?? 1,
        definition: raw.definition,
        published_at: raw.current_version != null ? raw.updated_at : null,
        created_at: raw.updated_at,
        notes: null,
      },
    ],
  };
}

export async function getBetaTree(code: string): Promise<BetaTreeDetail> {
  const treeId = await resolveBetaTreeId(code);
  const { data } = await apiClient.get<BetaTreeDetail & { definition?: BetaTreeDoc }>(
    `${BETA_TREES}/${treeId}`,
  );
  return normalizeDetail(data);
}

export async function createBetaTree(payload: BetaTreeCreatePayload): Promise<BetaTreeDetail> {
  const { data } = await apiClient.post<BetaTreeDetail & { definition?: BetaTreeDoc }>(
    BETA_TREES,
    payload,
  );
  return normalizeDetail(data);
}

/**
 * Append a draft version.
 *
 * Append-only, as the current engine is: posting a definition identical to
 * the newest one writes nothing. That is why a bad draft is discarded and
 * never saved over — see `discardBetaDraft`.
 */
export async function appendBetaDraft(
  treeId: string,
  definition: BetaTreeDoc,
  notes?: string | null,
): Promise<BetaTreeVersion> {
  const { data } = await apiClient.post<BetaTreeVersion>(`${BETA_TREES}/${treeId}/versions`, {
    definition,
    notes: notes ?? null,
  });
  return data;
}

export async function publishBetaVersion(
  treeId: string,
  versionId: string,
): Promise<BetaTreeDetail> {
  const { data } = await apiClient.post<BetaTreeDetail & { definition?: BetaTreeDoc }>(
    `${BETA_TREES}/${treeId}/publish`,
    { version_id: versionId },
  );
  return normalizeDetail(data);
}

/** Discard the unpublished draft. 204, no body. */
export async function discardBetaDraft(treeId: string): Promise<void> {
  await apiClient.delete(`${BETA_TREES}/${treeId}/draft`);
}

// ---- Publish checks --------------------------------------------------

/**
 * One reason the server refused a version.
 *
 * This is the authoritative check. `beta/lib/betaCompile.ts` runs the same
 * rule names in the browser while the author types, and is advisory only:
 * the publish is held by what comes back from here.
 *
 * `node_ids` is what the compiler emits — a rule such as "a path ends
 * without stop" names every node it found. `node_id` is the first of them,
 * which is what the panel links to.
 */
export interface BetaValidationError {
  rule: string;
  node_id: string | null;
  node_ids: string[];
  message_en: string;
  message_ar: string;
}

interface RawValidationError {
  rule?: unknown;
  node_id?: unknown;
  node_ids?: unknown;
  message_en?: unknown;
  message_ar?: unknown;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function readErrorList(raw: unknown): BetaValidationError[] {
  if (!Array.isArray(raw)) return [];
  const out: BetaValidationError[] = [];
  for (const entry of raw) {
    const e = (entry ?? {}) as RawValidationError;
    if (typeof e.rule !== "string") continue;
    const nodeIds = asStringArray(e.node_ids);
    const nodeId = typeof e.node_id === "string" ? e.node_id : (nodeIds[0] ?? null);
    out.push({
      rule: e.rule,
      node_id: nodeId,
      node_ids: nodeIds.length > 0 ? nodeIds : nodeId ? [nodeId] : [],
      message_en: typeof e.message_en === "string" ? e.message_en : e.rule,
      message_ar: typeof e.message_ar === "string" ? e.message_ar : "",
    });
  }
  return out;
}

/**
 * The publish checks carried by a rejected save or publish.
 *
 * A validation failure is a 422 whose problem body carries `errors`. The
 * list may sit at the top of the problem or under `extras`, depending on how
 * the route raised it, so both are read. Returns null when the failure was
 * something else — a 403, a network error — which the caller shows as a
 * plain message rather than as a node to go and fix.
 */
export function readValidationErrors(error: unknown): BetaValidationError[] | null {
  if (!isApiError(error) || error.status !== 422) return null;
  const problem: ProblemDetails = error.problem;
  const direct = readErrorList(problem.errors);
  if (direct.length > 0) return direct;
  const extras = problem.extras as { errors?: unknown } | undefined;
  const nested = readErrorList(extras?.errors);
  if (nested.length > 0) return nested;
  return null;
}

// ---- Dry run ---------------------------------------------------------

export interface BetaCandidateBlock {
  block_id: string;
  label: string;
  label_ar: string | null;
}

/**
 * One cell's fold, in the server's own field names.
 *
 * This read `finding_set`, `matched_rule_codes` and `unresolved` — a contract
 * written before the endpoint existed. The server sends `identity`,
 * `rule_code` and `composed` and has never sent an unresolved list, so the
 * table read `undefined.length` and the whole page fell over the moment a dry
 * run returned. Every field here was checked against a live response.
 */
export interface BetaDryRunCell {
  cell_id: string;
  cell_row: number | null;
  cell_col: number | null;
  /** The sorted finding codes. Empty means the tree found nothing, which is
   *  a healthy cell and not a missing answer. */
  identity: string[];
  findings: BetaDryRunFinding[];
  severity: FindingSeverity | null;
  status: FindingStatus | null;
  action_type: ActionType | null;
  text_en: string | null;
  text_ar: string | null;
  /** True when the text came from joining clauses rather than from a rule. */
  composed: boolean;
  /** The combination rule that matched, when one did. */
  rule_code: string | null;
  /** The node the walk ended on. A cell that stopped anywhere else errored. */
  stopped_at: string | null;
  error: string | null;
}

/** One finding a walk registered, with the nodes that registered it. */
export interface BetaDryRunFinding {
  code: string;
  severity: FindingSeverity;
  registered_by: string[];
}

export interface BetaDryRunResponse {
  tree_id: string;
  code: string;
  block_id: string;
  scope: string;
  version_id: string | null;
  cells_evaluated: number;
  /** Cells whose fold produced a card. The rest are healthy or errored. */
  cells_carded: number;
  /** Cells whose walk ended badly. Counted apart, because an errored cell is
   *  not a healthy one and must never read as one. */
  cells_errored: number;
  /** Of the carded cells, how many composed their text. */
  cells_composed: number;
  cells: BetaDryRunCell[];
}

/**
 * Walk the tree's stored draft over one block.
 *
 * The route takes a block and nothing else, so the draft has to be saved
 * first. The designer disables the run while the editor is dirty rather than
 * running the previous body and labelling the answer as the author's edit.
 *
 * A block with no grid returns no cells. That is an answer, not a failure,
 * and the panel says which one it is.
 */
export async function betaDryRun(treeId: string, blockId: string): Promise<BetaDryRunResponse> {
  const { data } = await apiClient.post<BetaDryRunResponse>(`${BETA_TREES}/${treeId}/dry-run`, {
    block_id: blockId,
  });
  // Defensive on the two lists the table walks. A field this client expects
  // and the server does not send used to reach the table as `undefined` and
  // take the page down with it; the report is worth more than the field.
  return {
    ...data,
    cells: (Array.isArray(data.cells) ? data.cells : []).map((cell) => ({
      ...cell,
      identity: Array.isArray(cell.identity) ? cell.identity : [],
      findings: Array.isArray(cell.findings) ? cell.findings : [],
    })),
  };
}

/**
 * Blocks the dry run can be pointed at.
 *
 * There is no candidate-block route on the contract, so this reads the
 * caller's own farms and their blocks. Both are tenant-scoped: a platform
 * caller has no farms, and asking anyway would land a 403 in an empty
 * picker. The designer says so in words instead — see `dryRun.platformScope`.
 */
export async function listDryRunBlocks(): Promise<BetaCandidateBlock[]> {
  const farms = await listFarms({ limit: DRY_RUN_FARM_LIMIT });
  const perFarm = await Promise.all(
    farms.items.map(async (farm) => {
      const page = await listBlocks(farm.id, { limit: 200 });
      return page.items.map((block) => ({
        block_id: block.id,
        label: `${farm.name} / ${block.name ?? block.code}`,
        label_ar:
          farm.name_ar || block.name_ar
            ? `${farm.name_ar ?? farm.name} / ${block.name_ar ?? block.name ?? block.code}`
            : null,
      }));
    }),
  );
  return perFarm.flat().sort((a, b) => a.label.localeCompare(b.label));
}

// ---- One cell's walk -------------------------------------------------

/** One node the walk visited, in the server's own field names. */
export interface BetaWalkStep {
  node_id: string;
  kind: string;
  matched: boolean | null;
  label_en: string | null;
  label_ar: string | null;
  /** What a condition read, by reference name. Empty on every other kind. */
  values: Record<string, unknown>;
  /** What the node did: the finding a register wrote, the variables a set
   *  wrote, the case a switch chose. */
  detail: Record<string, unknown> | null;
}

/** The combination rule that wrote a cell's text. */
export interface BetaWalkRule {
  code: string | null;
  codes: string[];
  text_en: string | null;
  text_ar: string | null;
  status: FindingStatus | null;
  action_type: ActionType | null;
}

/** One finding's own clause, as composition joined it. */
export interface BetaWalkClause {
  code: string;
  severity: FindingSeverity;
  clause_en: string | null;
  clause_ar: string | null;
}

export interface BetaCellWalkResponse {
  tree_id: string;
  code: string;
  block_id: string;
  version_id: string | null;
  /** The cell as this walk found it. Echoed in full on purpose — see
   *  `betaCellWalk`. */
  cell: BetaDryRunCell;
  path: BetaWalkStep[];
  /** Set when a combination rule matched. Null when the text was composed. */
  rule: BetaWalkRule | null;
  /** Set when the text was composed. Null when a rule matched. */
  composed_from: BetaWalkClause[] | null;
}

/**
 * Why one cell got the result it got.
 *
 * A separate call from the dry run rather than a field on it: a 300-cell
 * block would otherwise carry a 20-step path 300 times over to answer a
 * question asked about one row.
 *
 * **This re-walks.** Nothing stores a dry run, so the readings behind the
 * path are the readings at the moment of this call, and an imagery or weather
 * load that landed in between can change the answer. That is why `cell` comes
 * back in full: the caller compares it with the row it opened from and says
 * so, rather than drawing a path that explains a different answer.
 *
 * Defensive on `path` for the same reason `betaDryRun` is defensive on
 * `cells`: a field this client expects and the server does not send used to
 * reach a table as `undefined` and take the page down with it.
 */
export async function betaCellWalk(
  treeId: string,
  blockId: string,
  cellId: string,
  options: { definition?: BetaTreeDoc | null; versionId?: string | null } = {},
): Promise<BetaCellWalkResponse> {
  const { data } = await apiClient.post<BetaCellWalkResponse>(
    `${BETA_TREES}/${treeId}/dry-run/cell`,
    {
      block_id: blockId,
      cell_id: cellId,
      definition: options.definition ?? null,
      version_id: options.versionId ?? null,
    },
  );
  return {
    ...data,
    path: Array.isArray(data.path) ? data.path : [],
    composed_from: Array.isArray(data.composed_from) ? data.composed_from : null,
  };
}
