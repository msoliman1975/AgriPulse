/**
 * The beta decision-tree engine's API surface — mocked.
 *
 * Sessions 1 and 3 are building these endpoints right now and none of them is
 * merged. So this file holds the whole contract twice: the types and the
 * exported client functions, which are what the screens import, and an
 * in-memory backend that answers them, marked off below.
 *
 * Swapping to the real API is one change in this file and nothing else: every
 * exported function's body becomes an `apiClient` call. No screen, query hook
 * or component references the mock.
 *
 * Endpoints still to replace, with the prompt that brings each one:
 *
 *   prompt 1  GET/POST/PATCH/DELETE /v1/decision-tree-findings           platform catalogue
 *   prompt 1  GET/POST/PATCH/DELETE /v1/tenant/decision-tree-findings    this tenant's codes
 *   prompt 3  POST /v1/decision-trees-beta/{code}:compile                publish checks
 *   prompt 5  GET  /v1/decision-trees-beta                               list
 *   prompt 5  GET  /v1/decision-trees-beta/{code}                        read
 *   prompt 5  POST /v1/decision-trees-beta/{code}/versions               save draft
 *   prompt 5  POST /v1/decision-trees-beta/{code}/versions/{n}:publish   publish
 *   prompt 6  POST /v1/decision-trees-beta/{code}:dry-run                fold per cell
 *   prompt 6  GET  /v1/decision-trees-beta/{code}/candidate-blocks       block picker
 *
 * The finding routes are the ones PR #700 shipped, read off its router. Three
 * things about them the mock already matches, so the swap does not change a
 * screen:
 *
 *   * They are two endpoints, not one. `listFindings` concatenates them, and
 *     `shadowed` comes back set on the tenant rows.
 *   * Both list responses are an envelope, `{ findings: [...] }`, not a bare
 *     array — unwrap `.findings`.
 *   * DELETE deactivates. It clears `is_active` and keeps the row, because the
 *     code is stored in every `recommendations.finding_set` that ever carried
 *     it. Nothing on this screen may call it a delete.
 *
 * Shapes follow docs/proposals/unified-decision-tree-engine.md sections 6.1,
 * 6.2 and 6.5.
 */

import {
  compileBetaTree,
  type CompileRejection,
} from "@/modules/decisionTrees/beta/lib/betaCompile";
import {
  enumerateFindingSets,
  foldFindings,
  type FoldFinding,
} from "@/modules/decisionTrees/beta/lib/betaFold";
import {
  parseBetaDoc,
  readCombinations,
  registeredCodes,
  STARTER_BETA_YAML,
} from "@/modules/decisionTrees/beta/lib/betaTree";
import type {
  ActionType,
  FindingSeverity,
  FindingStatus,
} from "@/modules/decisionTrees/beta/lib/betaConstants";

// ---- Types -----------------------------------------------------------

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
   * resolves platform first, so this row is never read (section 6.2).
   * Always false on a platform row.
   */
  shadowed: boolean;
}

export interface FindingWritePayload {
  code: string;
  clause_en: string;
  clause_ar: string;
  name_en: string;
  name_ar: string;
  default_status: FindingStatus;
  description_en?: string | null;
  description_ar?: string | null;
  is_active?: boolean;
}

export interface BetaTreeVersion {
  version: number;
  tree_yaml: string;
  published_at: string | null;
  created_at: string;
  notes: string | null;
}

export interface BetaTreeSummary {
  code: string;
  name_en: string;
  name_ar: string | null;
  /** NULL = platform-shipped; non-NULL = the caller's own tenant tree. */
  tenant_id: string | null;
  scope: "block" | "cell";
  current_version: number | null;
  published_version: number | null;
  updated_at: string;
}

export interface BetaTreeDetail extends BetaTreeSummary {
  versions: BetaTreeVersion[];
}

export interface BetaCompileResponse {
  rejections: CompileRejection[];
}

export interface BetaCandidateBlock {
  block_id: string;
  label: string;
  label_ar: string | null;
  cells: number;
}

export interface BetaDryRunPayload {
  block_id: string;
  /** Evaluate an unsaved draft rather than the stored version. */
  tree_yaml?: string;
}

/** One cell's fold. `matched_rule_codes` is null when the text was composed. */
export interface BetaDryRunCell {
  cell_id: string;
  cell_row: number | null;
  cell_col: number | null;
  finding_set: string[];
  matched_rule_codes: string[] | null;
  severity: FindingSeverity | null;
  status: FindingStatus;
  action_type: ActionType | null;
  text_en: string;
  text_ar: string;
  /** Codes in the set that no catalogue resolved. */
  unresolved: string[];
  error: string | null;
}

export interface BetaDryRunResponse {
  block_id: string;
  cells_evaluated: number;
  /** Cells whose finding set was non-empty, i.e. that produce a card. */
  cells_with_card: number;
  cells: BetaDryRunCell[];
}

// ---- Client ----------------------------------------------------------
//
// Every function below is a one-line delegate today. Replace each body with
// its `apiClient` call and delete the mock section; nothing else moves.

/** Both catalogues, concatenated, with `shadowed` set on the tenant rows the
 *  platform table also defines. Two GETs, one list. */
export async function listFindings(): Promise<Finding[]> {
  return mock.listFindings();
}

export async function createFinding(
  source: FindingSource,
  payload: FindingWritePayload,
): Promise<Finding> {
  return mock.createFinding(source, payload);
}

export async function updateFinding(
  source: FindingSource,
  code: string,
  payload: FindingWritePayload,
): Promise<Finding> {
  return mock.updateFinding(source, code, payload);
}

/**
 * Deactivate a finding. Not a delete.
 *
 * The code is stored in every `recommendations.finding_set` that ever carried
 * it and named by every tree that registers it, so the row stays and
 * `is_active` is cleared. The screen says "Deactivate" for the same reason.
 */
export async function deactivateFinding(source: FindingSource, code: string): Promise<Finding> {
  return mock.deactivateFinding(source, code);
}

export async function listBetaTrees(): Promise<BetaTreeSummary[]> {
  return mock.listTrees();
}

export async function getBetaTree(code: string): Promise<BetaTreeDetail> {
  return mock.getTree(code);
}

/** Append a draft version. The engine is append-only, as today. */
export async function saveBetaTreeDraft(
  code: string,
  tree_yaml: string,
  notes?: string | null,
): Promise<BetaTreeDetail> {
  return mock.saveDraft(code, tree_yaml, notes ?? null);
}

export async function compileBetaTreeRemote(
  code: string,
  tree_yaml: string,
): Promise<BetaCompileResponse> {
  return mock.compile(code, tree_yaml);
}

export async function publishBetaTreeVersion(
  code: string,
  version: number,
): Promise<BetaTreeDetail> {
  return mock.publish(code, version);
}

export async function getBetaCandidateBlocks(code: string): Promise<BetaCandidateBlock[]> {
  return mock.candidateBlocks(code);
}

export async function betaDryRun(
  code: string,
  payload: BetaDryRunPayload,
): Promise<BetaDryRunResponse> {
  return mock.dryRun(code, payload);
}

// ======================================================================
// MOCK BACKEND — delete this whole section when the endpoints land.
// ======================================================================

const LATENCY_MS = 120;

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), LATENCY_MS));
}

function nowIso(): string {
  return new Date().toISOString();
}

type MockFindingRow = Omit<Finding, "shadowed">;

// The eight codes public migration 0090 seeds, copied from it so the mock and
// the database agree on code, clause and default status. Wording comes from
// the merged mango tree (design section 7).
const platformFindings: MockFindingRow[] = [
  {
    code: "ndvi_low",
    name_en: "Low vigour",
    name_ar: "حيوية منخفضة",
    clause_en: "canopy vigour is below the band for this tree size",
    clause_ar: "حيوية المجموع دون النطاق لهذا الحجم",
    default_status: "issue",
    description_en:
      "The vigour index chosen for this block's soil and tree size reads below the band the index guide expects.",
    description_ar:
      "مؤشر الحيوية المختار لتربة القطعة وحجم الشجرة يقرأ دون النطاق الذي يتوقعه دليل المؤشرات.",
    is_active: true,
    source: "platform",
  },
  {
    code: "dry",
    name_en: "Low leaf water",
    name_ar: "نقص ماء الأوراق",
    clause_en: "leaf water is low",
    clause_ar: "ماء الأوراق منخفض",
    default_status: "issue",
    description_en: "At least two of NDMI, SMI and CWSI agree that the block is short of water.",
    description_ar: "اتفق مؤشران على الأقل من NDMI و SMI و CWSI على أن القطعة تعاني نقص ماء.",
    is_active: true,
    source: "platform",
  },
  {
    code: "nutrient_low",
    name_en: "Low nitrogen",
    name_ar: "نقص نيتروجين",
    clause_en: "leaf nitrogen is below the band",
    clause_ar: "نيتروجين الأوراق دون النطاق",
    default_status: "issue",
    description_en: "NDRE reads below the band the guide expects for this tree size.",
    description_ar: "يقرأ NDRE دون النطاق الذي يتوقعه الدليل لهذا الحجم.",
    is_active: true,
    source: "platform",
  },
  {
    code: "cover_open",
    name_en: "Open ground cover",
    name_ar: "غطاء أرضي مكشوف",
    clause_en: "more bare ground is showing than the guide expects",
    clause_ar: "الأرض المكشوفة أكثر مما يتوقعه الدليل",
    default_status: "issue",
    description_en: "BSI reads above the band for this tree size.",
    description_ar: "يقرأ BSI فوق النطاق لهذا الحجم.",
    is_active: true,
    source: "platform",
  },
  {
    code: "pest_high",
    name_en: "Anthracnose high",
    name_ar: "أنثراكنوز مرتفع",
    clause_en: "anthracnose pressure is high",
    clause_ar: "ضغط الأنثراكنوز مرتفع",
    default_status: "alert",
    description_en:
      "Weather conditions strongly favour anthracnose infection while the block carries susceptible tissue.",
    description_ar: "تُرجّح ظروف الطقس بقوة الإصابة بالأنثراكنوز والقطعة تحمل أنسجة قابلة للإصابة.",
    is_active: true,
    source: "platform",
  },
  {
    code: "pest_med",
    name_en: "Anthracnose building",
    name_ar: "أنثراكنوز متصاعد",
    clause_en: "anthracnose pressure is building",
    clause_ar: "ضغط الأنثراكنوز يتصاعد",
    default_status: "issue",
    description_en: "Conditions are moving toward anthracnose. This is the scouting window.",
    description_ar: "تتجه الظروف نحو الأنثراكنوز. هذه نافذة الكشف الميداني.",
    is_active: true,
    source: "platform",
  },
  {
    code: "mildew_high",
    name_en: "Powdery mildew high",
    name_ar: "بياض دقيقي مرتفع",
    clause_en: "powdery mildew pressure is high",
    clause_ar: "ضغط البياض الدقيقي مرتفع",
    default_status: "alert",
    description_en:
      "Weather conditions strongly favour powdery mildew while the block is in bloom.",
    description_ar: "تُرجّح ظروف الطقس بقوة البياض الدقيقي والقطعة في الإزهار.",
    is_active: true,
    source: "platform",
  },
  {
    code: "fly_high",
    name_en: "Fruit fly high",
    name_ar: "ذبابة فاكهة مرتفعة",
    clause_en: "fruit fly pressure is high",
    clause_ar: "ضغط ذبابة الفاكهة مرتفع",
    default_status: "alert",
    description_en:
      "Conditions strongly favour fruit fly activity while the block has ripening fruit.",
    description_ar: "تُرجّح الظروف بقوة نشاط ذبابة الفاكهة والقطعة تحمل ثمارًا تنضج.",
    is_active: true,
    source: "platform",
  },
];

const tenantFindings: MockFindingRow[] = [
  {
    code: "salinity_rising",
    name_en: "Salinity rising",
    name_ar: "ارتفاع الملوحة",
    clause_en: "soil salinity is rising",
    clause_ar: "ملوحة التربة في ارتفاع",
    default_status: "issue",
    description_en: "A tenant-authored finding, read from the EC probe signal.",
    description_ar: "نتيجة أنشأها المستأجر، تُقرأ من إشارة مسبار التوصيل الكهربائي.",
    is_active: true,
    source: "tenant",
  },
  {
    // Deliberate: the admin screen has to show a shadowed row, because the
    // fold resolves the platform table first and this one is never read.
    code: "dry",
    name_en: "Low leaf water (local wording)",
    name_ar: "نقص ماء الأوراق (صياغة محلية)",
    clause_en: "the leaves are running dry",
    clause_ar: "الأوراق بدأت تجف",
    default_status: "issue",
    description_en: "Written before the platform shipped `dry`. Never read now.",
    description_ar: "كُتبت قبل إصدار المنصة للرمز dry. لم تعد تُقرأ.",
    is_active: true,
    source: "tenant",
  },
];

const MANGO_BETA_YAML = `code: mango_water_beta
name_en: Mango water and pressure (beta)
name_ar: الماء والضغط على المانجو (تجريبي)
description_en: Registers water, vigour and pest findings, then folds them into one card.
description_ar: تسجل نتائج الماء والحيوية والآفات ثم تدمجها في بطاقة واحدة.

registers:
  - dry
  - ndvi_low
  - pest_high

combinations:
  - codes: [dry, ndvi_low]
    action_type: irrigate
    status: issue
    text_en: Water shortage is the cause. Irrigate before treating anything else.
    text_ar: نقص المياه هو السبب. اسقِ قبل معالجة أي شيء آخر.

root: cond_1
nodes:
  cond_1:
    label_en: Is leaf water below baseline?
    label_ar: هل ماء الورقة أقل من خط الأساس؟
    condition:
      tree:
        op: lt
        left: { source: indices, index_code: ndmi, key: baseline_deviation }
        right: -0.1
    on_match: reg_1
    on_miss: set_1

  reg_1:
    label_en: Record low leaf water
    label_ar: سجّل انخفاض ماء الورقة
    register:
      code: dry
      severity: warning
    next: set_1

  set_1:
    label_en: Remember which index was used
    label_ar: احفظ المؤشر المستخدم
    set:
      index_used: ndmi
      ndvi_now:
        source: indices
        index_code: ndvi
        key: mean
    next: sw_1

  sw_1:
    label_en: Anthracnose pressure bands
    label_ar: نطاقات ضغط الأنثراكنوز
    switch:
      on: { source: weather_risk, risk_code: anthracnose, field: score }
      cases:
        - { op: ge, value: 70, go: reg_2 }
        - { op: ge, value: 40, go: reg_3 }
      default: stop_1

  reg_2:
    label_en: Record high pest pressure
    label_ar: سجّل ارتفاع ضغط الآفات
    register:
      code: pest_high
      severity: critical
    next: stop_1

  reg_3:
    label_en: Record dropping vigour
    label_ar: سجّل انخفاض الحيوية
    register:
      code: ndvi_low
      severity: info
    next: stop_1

  stop_1:
    label_en: End and fold
    label_ar: إنهاء ودمج
    stop: true
`;

interface MockTree {
  summary: BetaTreeSummary;
  versions: BetaTreeVersion[];
}

const trees: MockTree[] = [
  {
    summary: {
      code: "mango_water_beta",
      name_en: "Mango water and pressure (beta)",
      name_ar: "الماء والضغط على المانجو (تجريبي)",
      tenant_id: "mock-tenant",
      scope: "cell",
      current_version: 2,
      published_version: 1,
      updated_at: nowIso(),
    },
    versions: [
      {
        version: 1,
        tree_yaml: MANGO_BETA_YAML,
        published_at: nowIso(),
        created_at: nowIso(),
        notes: "First cut",
      },
      {
        version: 2,
        tree_yaml: MANGO_BETA_YAML,
        published_at: null,
        created_at: nowIso(),
        notes: null,
      },
    ],
  },
  {
    summary: {
      code: "starter_beta",
      name_en: "New beta tree",
      name_ar: "شجرة تجريبية جديدة",
      tenant_id: "mock-tenant",
      scope: "block",
      current_version: 1,
      published_version: null,
      updated_at: nowIso(),
    },
    versions: [
      {
        version: 1,
        tree_yaml: STARTER_BETA_YAML.replace("code: REPLACE_ME", "code: starter_beta"),
        published_at: null,
        created_at: nowIso(),
        notes: null,
      },
    ],
  },
];

function resolvedFindings(): Finding[] {
  const platformCodes = new Set(platformFindings.map((f) => f.code));
  return [
    ...platformFindings.map((f) => ({ ...f, shadowed: false })),
    ...tenantFindings.map((f) => ({ ...f, shadowed: platformCodes.has(f.code) })),
  ];
}

/** The codes the fold can resolve: platform first, then tenant. */
function foldCatalogue(): Map<string, FoldFinding> {
  const out = new Map<string, FoldFinding>();
  for (const f of [...tenantFindings, ...platformFindings]) {
    out.set(f.code, {
      code: f.code,
      clause_en: f.clause_en,
      clause_ar: f.clause_ar,
      name_en: f.name_en,
      name_ar: f.name_ar,
      default_status: f.default_status,
      source: f.source,
    });
  }
  return out;
}

function findTree(code: string): MockTree {
  const tree = trees.find((t) => t.summary.code === code);
  if (!tree) throw new Error(`No beta tree with code "${code}"`);
  return tree;
}

function currentYaml(tree: MockTree): string {
  const version = tree.versions[tree.versions.length - 1];
  return version?.tree_yaml ?? "";
}

/**
 * A deterministic pseudo-random number from a string.
 *
 * The dry run has to invent cell readings, and they must not change on every
 * render — an author comparing two runs would read the churn as the tree
 * behaving differently.
 */
function hashUnit(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 10000) / 10000;
}

const mock = {
  listFindings(): Promise<Finding[]> {
    return delay(resolvedFindings());
  },

  createFinding(source: FindingSource, payload: FindingWritePayload): Promise<Finding> {
    const table = source === "platform" ? platformFindings : tenantFindings;
    if (table.some((f) => f.code === payload.code)) {
      return Promise.reject(new Error(`A ${source} finding "${payload.code}" already exists.`));
    }
    const row: MockFindingRow = {
      code: payload.code,
      clause_en: payload.clause_en,
      clause_ar: payload.clause_ar,
      name_en: payload.name_en,
      name_ar: payload.name_ar,
      default_status: payload.default_status,
      description_en: payload.description_en ?? null,
      description_ar: payload.description_ar ?? null,
      is_active: payload.is_active ?? true,
      source,
    };
    table.push(row);
    const platformCodes = new Set(platformFindings.map((f) => f.code));
    return delay({ ...row, shadowed: source === "tenant" && platformCodes.has(row.code) });
  },

  updateFinding(
    source: FindingSource,
    code: string,
    payload: FindingWritePayload,
  ): Promise<Finding> {
    const table = source === "platform" ? platformFindings : tenantFindings;
    const index = table.findIndex((f) => f.code === code);
    if (index < 0) return Promise.reject(new Error(`No ${source} finding "${code}".`));
    const row: MockFindingRow = {
      ...table[index],
      ...payload,
      description_en: payload.description_en ?? null,
      description_ar: payload.description_ar ?? null,
      is_active: payload.is_active ?? true,
      source,
    };
    table[index] = row;
    const platformCodes = new Set(platformFindings.map((f) => f.code));
    return delay({ ...row, shadowed: source === "tenant" && platformCodes.has(row.code) });
  },

  deactivateFinding(source: FindingSource, code: string): Promise<Finding> {
    const table = source === "platform" ? platformFindings : tenantFindings;
    const index = table.findIndex((f) => f.code === code);
    if (index < 0) return Promise.reject(new Error(`No ${source} finding "${code}".`));
    // The row stays. Only `is_active` changes.
    table[index] = { ...table[index], is_active: false };
    const platformCodes = new Set(platformFindings.map((f) => f.code));
    return delay({
      ...table[index],
      shadowed: source === "tenant" && platformCodes.has(code),
    });
  },

  listTrees(): Promise<BetaTreeSummary[]> {
    return delay(trees.map((t) => ({ ...t.summary })));
  },

  getTree(code: string): Promise<BetaTreeDetail> {
    const tree = findTree(code);
    return delay({ ...tree.summary, versions: tree.versions.map((v) => ({ ...v })) });
  },

  saveDraft(code: string, tree_yaml: string, notes: string | null): Promise<BetaTreeDetail> {
    const tree = findTree(code);
    const last = tree.versions[tree.versions.length - 1];
    // Append-only, with the same no-op the current engine has: re-saving an
    // unchanged body writes no version.
    if (last && last.published_at === null && last.tree_yaml === tree_yaml) {
      return delay({ ...tree.summary, versions: tree.versions.map((v) => ({ ...v })) });
    }
    if (last && last.published_at === null) {
      last.tree_yaml = tree_yaml;
      last.notes = notes;
    } else {
      tree.versions.push({
        version: (last?.version ?? 0) + 1,
        tree_yaml,
        published_at: null,
        created_at: nowIso(),
        notes,
      });
    }
    tree.summary.current_version = tree.versions[tree.versions.length - 1].version;
    tree.summary.updated_at = nowIso();
    return delay({ ...tree.summary, versions: tree.versions.map((v) => ({ ...v })) });
  },

  compile(code: string, tree_yaml: string): Promise<BetaCompileResponse> {
    void code;
    const rejections = compileBetaTree({
      yaml: tree_yaml,
      knownFindingCodes: [...foldCatalogue().keys()],
    });
    return delay({ rejections });
  },

  publish(code: string, version: number): Promise<BetaTreeDetail> {
    const tree = findTree(code);
    const target = tree.versions.find((v) => v.version === version);
    if (!target) return Promise.reject(new Error(`No version ${version} of "${code}".`));
    const rejections = compileBetaTree({
      yaml: target.tree_yaml,
      knownFindingCodes: [...foldCatalogue().keys()],
    });
    if (rejections.length > 0) {
      return Promise.reject(
        new Error(`The compiler rejected version ${version} in ${rejections.length} places.`),
      );
    }
    target.published_at = nowIso();
    tree.summary.published_version = version;
    tree.summary.updated_at = nowIso();
    return delay({ ...tree.summary, versions: tree.versions.map((v) => ({ ...v })) });
  },

  candidateBlocks(code: string): Promise<BetaCandidateBlock[]> {
    void code;
    return delay([
      {
        block_id: "blk-north-12",
        label: "Bashayer / North 12",
        label_ar: "بشاير / شمال ١٢",
        cells: 9,
      },
      {
        block_id: "blk-north-13",
        label: "Bashayer / North 13",
        label_ar: "بشاير / شمال ١٣",
        cells: 6,
      },
      { block_id: "blk-west-04", label: "Bashayer / West 4", label_ar: "بشاير / غرب ٤", cells: 12 },
    ]);
  },

  dryRun(code: string, payload: BetaDryRunPayload): Promise<BetaDryRunResponse> {
    const tree = findTree(code);
    const yaml = payload.tree_yaml ?? currentYaml(tree);
    const doc = parseBetaDoc(yaml);
    const rules = readCombinations(doc);
    const catalogue = foldCatalogue();
    const severityByCode = new Map(
      [...registeredCodes(doc).keys()].map((c) => {
        const node = Object.values(doc?.nodes ?? {}).find(
          (n) => n.register?.code === c && n.register?.severity,
        );
        const severity: FindingSeverity = node?.register?.severity ?? "warning";
        return [c, severity] as const;
      }),
    );

    // Which sets this tree can produce; the cells sample from them, so the
    // dry run and the combinations tab cannot disagree about what is possible.
    const producible = enumerateFindingSets(doc).sets;
    const block = [
      { block_id: "blk-north-12", cells: 9 },
      { block_id: "blk-north-13", cells: 6 },
      { block_id: "blk-west-04", cells: 12 },
    ].find((b) => b.block_id === payload.block_id) ?? { block_id: payload.block_id, cells: 9 };

    const cells: BetaDryRunCell[] = [];
    for (let i = 0; i < block.cells; i++) {
      const cell_id = `${block.block_id}-c${i + 1}`;
      const pick = producible.length
        ? producible[Math.floor(hashUnit(cell_id) * producible.length)]
        : null;
      const card = foldFindings(pick?.codes ?? [], rules, {
        findings: catalogue,
        severityByCode,
      });
      cells.push({
        cell_id,
        cell_row: Math.floor(i / 3) + 1,
        cell_col: (i % 3) + 1,
        finding_set: card.finding_set,
        matched_rule_codes: card.matched_rule ? card.matched_rule.codes : null,
        severity: card.severity,
        status: card.status,
        action_type: card.action_type,
        text_en: card.text_en,
        text_ar: card.text_ar,
        unresolved: card.unresolved,
        error: null,
      });
    }
    return delay({
      block_id: block.block_id,
      cells_evaluated: cells.length,
      cells_with_card: cells.filter((c) => c.finding_set.length > 0).length,
      cells,
    });
  },
};
