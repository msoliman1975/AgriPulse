// Pure helpers for the visual condition builder.
//
// The condition AST (see backend/app/shared/conditions/evaluator.py) is
// expressive: boolean groups (all_of / any_of / not), six binary ops
// plus `between` and `in`, and refs from eight sources. The builder now
// models all of it, so authoring no longer falls off a cliff into the
// raw-YAML editor the moment a tree needs a nested group or a NOT.
//
// The `unsupported` branch is kept, but it should now only be reached by
// a genuinely malformed AST rather than by a shape we simply declined to
// model. We never throw away the original AST: the panel keeps it and
// the YAML save path emits it untouched.

// ---- Domain constants ----------------------------------------------

// Mirrors backend constants in `backend/app/shared/conditions/{models,context}.py`.
// Keep in lock-step. These drifted once — the backend gained the KB P2
// trend keys and the KB P3 / taxonomy block fields while this file stayed
// on the original pair — which silently made every stage-gated and
// trend-based tree unparseable here and pushed it into the YAML fallback.
// If you add a key or field on the backend, add it here in the same PR.
export const INDICES_KEYS = [
  "mean",
  "baseline_deviation",
  // KB P2 trend features, computed at context load from recent history.
  "slope",
  "delta",
  "trend_direction",
] as const;
// The canonical imagery index codes (block_index_aggregates / grid
// aggregates). Closed list so the author picks from a dropdown rather than
// guessing; mirrors STANDARD_INDEX_CODES in
// backend/app/modules/indices/computation.py and IndexCode in api/indices.ts.
export const INDEX_CODES = [
  "ndvi",
  "ndwi",
  "evi",
  "savi",
  "ndre",
  "gndvi",
  "ndmi",
  "bsi",
  "msi",
] as const;
export const BLOCK_FIELDS = [
  // KB P3: the block's current phenological stage, resolved from the crop
  // taxonomy and auto-advanced daily.
  "growth_stage",
  "soil_texture",
  "salinity_class",
  // NOTE: no `crop_category`, `crop_path` or `crop_strain`. All three restate
  // the tree's own targeting — it already declares which crop paths it runs
  // on — so branching on them asks a question the targeting has answered. No
  // tree ever used one. Also no `canopy_size_class`: nothing writes it.
  // Keep identical to BLOCK_FIELDS in backend/app/shared/conditions/models.py.
] as const;

export const SIGNAL_KEYS = [
  "value_numeric",
  "value_categorical",
  "value_event",
  "value_boolean",
  // KB P2 trend features over the numeric observation history.
  "value_slope",
  "value_delta",
  "value_trend_direction",
] as const;
export const WEATHER_SCOPES = [
  "latest_observation",
  "forecast_24h",
  "forecast_72h",
  "derived_today",
  "derived_yesterday",
] as const;
// Valid `field` names per weather scope. Unlike every other source these are
// NOT validated by the backend parser — `WeatherValueRef.field` is free-form
// because the loader is the source of truth for which fields exist per scope,
// and an unknown one resolves to None (permissive-on-missing-data). Which
// means a typo here produces a tree that parses, saves, and silently never
// fires. So the builder closes the list itself: these mirror the three SELECT
// lists in backend/app/modules/weather/snapshot.py exactly. If you add a
// column to one of those queries, add it here in the same PR.
const FORECAST_FIELDS = [
  "precipitation_mm_total",
  "precipitation_probability_pct_max",
  "air_temp_c_max",
  "air_temp_c_min",
  "air_temp_c_mean",
  "humidity_pct_mean",
  "et0_mm_total",
  "wind_speed_m_s_max",
  // Window coverage, so a rule can require a full window before acting
  // ("only if we actually have 24h of forecast").
  "hours_observed",
] as const;
const DERIVED_FIELDS = [
  "gdd_base10",
  "gdd_base15",
  "gdd_cumulative_base10_season",
  "et0_mm_daily",
  "precip_mm_daily",
  "precip_mm_7d",
  "precip_mm_30d",
  "temp_min_c",
  "temp_max_c",
  "temp_mean_c",
] as const;
export const WEATHER_FIELDS: Record<(typeof WEATHER_SCOPES)[number], readonly string[]> = {
  // The latest hourly observation row.
  latest_observation: [
    "air_temp_c",
    "humidity_pct",
    "precipitation_mm",
    "wind_speed_m_s",
    "wind_direction_deg",
    "pressure_hpa",
    "solar_radiation_w_m2",
    "cloud_cover_pct",
    "et0_mm",
  ],
  forecast_24h: FORECAST_FIELDS,
  forecast_72h: FORECAST_FIELDS,
  derived_today: DERIVED_FIELDS,
  derived_yesterday: DERIVED_FIELDS,
};
// First-class weather indices (PR-W7). `value` is the farm-level daily
// value; `baseline_deviation` is its z-score vs the day-of-year
// climatology. Mirrors WEATHER_INDEX_KEYS in
// backend/app/shared/conditions/context.py.
export const WEATHER_INDEX_KEYS = ["value", "baseline_deviation"] as const;
// The catalog codes (public weather_indices_catalog). Kept as a closed list
// so the author picks from a dropdown rather than guessing a code; mirrors
// the migration 0037 seed + 0049 (`humidity`) + 0057 (gap-audit indices).
//
// Unlike INDEX_CODES above this list is load-bearing at RUNTIME, not just in
// the picker: `parseValueRef` rejects an unknown code, which drops the whole
// tree editor to the read-only YAML fallback. A code seeded in the migration
// and missed here does not degrade gracefully.
export const WEATHER_INDEX_CODES = [
  "temperature",
  "radiation",
  "wind",
  "humidity",
  "rainfall",
  "evapotranspiration",
  "evaporation_coeff",
  "rain_et_balance",
  "leaf_wetness",
  "frost_risk",
  "heat_stress",
  "drought_spi",
] as const;
// Per-block weather-driven disease/pest risk fields (PR-R3). `score` is the
// 0-100 pressure; `level` its low|moderate|high banding. Mirrors
// WEATHER_RISK_FIELDS in backend/app/shared/conditions/context.py.
export const WEATHER_RISK_FIELDS = ["score", "level"] as const;
// Per-block crop water accounting (block_water_balance_daily): precipitation +
// irrigation - ETc. Mirrors WATER_BALANCE_FIELDS in
// backend/app/shared/conditions/context.py.
//
// `balance_mm` is the headline; the rest are the derivation, so a tree can
// branch on WHY a block is short rather than only on the fact. High demand,
// absent rain and unlogged irrigation all produce a negative balance and call
// for different actions.
//
// `irrigation_logged` exists so a tree can refuse to act on a deficit it
// cannot trust: a farm that never records irrigation shows a permanent
// shortfall that is a bookkeeping artefact, not dry soil.
export const WATER_BALANCE_FIELDS = [
  "balance_mm",
  "etc_mm",
  "et0_mm",
  "kc_used",
  "precip_mm",
  "irrigation_mm",
  "irrigation_logged",
] as const;
// The mango V1 pathogen/pest codes (weather.risk registry), each with the
// crop path prefix its model is registered for. Mirrors REGISTRY in
// backend/app/modules/weather/risk/registry.py — a model only ever scores
// blocks whose crop path is that prefix or one of its descendants, so a tree
// targeting citrus can never see one of these. Surfacing the prefix is what
// stops an author branching on a risk their blocks will never be scored for.
export const WEATHER_RISK_CROP_PREFIX: Record<string, string> = {
  powdery_mildew: "mango",
  anthracnose: "mango",
  fruit_fly: "mango",
};
export const WEATHER_RISK_CODES = ["powdery_mildew", "anthracnose", "fruit_fly"] as const;

/** True when a risk model registered for `prefix` can score a block under any
 *  of `cropPaths`. Prefix match, mirroring `_crop_applies` on the backend:
 *  `mango` covers `mango.keitt.large`, and — because a tree targeting the
 *  broader `mango` runs on every cultivar — a target that is a prefix OF the
 *  model's own path counts too. An empty target list means "not yet
 *  targeted", so nothing is hidden. */
export function riskAppliesToCrops(riskCode: string, cropPaths: string[]): boolean {
  const prefix = WEATHER_RISK_CROP_PREFIX[riskCode];
  if (!prefix || cropPaths.length === 0) return true;
  return cropPaths.some(
    (path) => path === prefix || path.startsWith(prefix + ".") || prefix.startsWith(path + "."),
  );
}

/** True when a crop-attribute definition at `path` can resolve for a block
 *  under any of `cropPaths`. Definitions are inherited down the taxonomy, so
 *  a `mango` definition resolves for `mango.keitt`; and a tree targeting
 *  `mango` runs on blocks that may carry `mango.keitt`, so a definition
 *  deeper than the target counts too. */
export function attributePathAppliesToCrops(path: string, cropPaths: string[]): boolean {
  if (cropPaths.length === 0) return true;
  return cropPaths.some(
    (target) => target === path || target.startsWith(path + ".") || path.startsWith(target + "."),
  );
}

/** The signal value keys that can be non-null for a definition of
 *  `value_kind`. Exactly one `value_*` column is populated per kind, so
 *  offering all seven is offering six ways to write a term that never
 *  matches. The trend keys ride along with numeric signals only. */
export function signalKeysForValueKind(kind: string | undefined): readonly string[] {
  switch (kind) {
    case "numeric":
      return ["value_numeric", "value_slope", "value_delta", "value_trend_direction"];
    case "categorical":
      return ["value_categorical"];
    case "event":
      return ["value_event"];
    case "boolean":
      return ["value_boolean"];
    default:
      // Unknown / not-yet-picked (and `geopoint`, which no key exposes) —
      // fall back to the full list rather than emptying the dropdown.
      return SIGNAL_KEYS;
  }
}
// Crop-attribute keys. Mirrors CROP_ATTRIBUTE_KEYS in
// backend/app/shared/conditions/context.py. One key today; declared as a list
// so a future `days_since` derivation slots in without changing the ref shape.
export const CROP_ATTRIBUTE_KEYS = ["value"] as const;
// NOTE: unlike every other source, crop_attribute has NO closed list of
// codes here. The codes come from `public.crop_attribute_definitions` and grow
// with the catalog, so the builder fetches them from
// GET /api/v1/crops/attribute-definitions. That is why this file carries no
// CROP_ATTRIBUTE_CODES constant — adding one would immediately be wrong.

// Sub-block grid spatial-anomaly fields (G-4). Mirrors GRID_FIELDS in
// backend/app/shared/conditions/context.py.
export const GRID_FIELDS = [
  "worst_z",
  "flagged_count",
  "worst_row",
  "worst_col",
  "severity",
] as const;

// Binary comparison ops — one left ref, one right operand.
export const BINARY_OPS = ["lt", "le", "gt", "ge", "eq", "ne"] as const;
export type BinaryOp = (typeof BINARY_OPS)[number];

// Every op the term editor offers. `between` takes a low/high pair and
// `in` takes a value list, so they get their own operand shapes below.
export const TERM_OPS = [...BINARY_OPS, "between", "in"] as const;
export type TermOp = (typeof TERM_OPS)[number];

/** How deep the visual builder lets an author nest groups. The node
 *  details panel is a fixed ~360px column and each level costs
 *  indentation, so past this the UI stops offering "add group" — the AST
 *  itself has no such limit and a deeper tree authored in YAML still
 *  parses and renders here. */
export const MAX_GROUP_DEPTH = 3;

// ---- AST types -----------------------------------------------------

export type ValueRefSource =
  | "indices"
  | "block"
  | "weather"
  | "weather_index"
  | "weather_risk"
  | "water_balance"
  | "signals"
  | "grid"
  | "crop_attribute"
  | "params";

export type ValueRef =
  | { source: "indices"; index_code: string; key: (typeof INDICES_KEYS)[number] }
  | { source: "block"; field: (typeof BLOCK_FIELDS)[number] }
  | { source: "weather"; scope: (typeof WEATHER_SCOPES)[number]; field: string }
  | {
      source: "weather_index";
      index_code: (typeof WEATHER_INDEX_CODES)[number];
      key: (typeof WEATHER_INDEX_KEYS)[number];
    }
  | {
      source: "weather_risk";
      risk_code: (typeof WEATHER_RISK_CODES)[number];
      field: (typeof WEATHER_RISK_FIELDS)[number];
    }
  | { source: "water_balance"; field: (typeof WATER_BALANCE_FIELDS)[number] }
  | { source: "signals"; code: string; key: (typeof SIGNAL_KEYS)[number] }
  | { source: "grid"; index_code: string; field: (typeof GRID_FIELDS)[number] }
  | { source: "crop_attribute"; code: string; key: (typeof CROP_ATTRIBUTE_KEYS)[number] }
  | { source: "params"; name: string };

// The right-hand side of a comparison can be a literal (number, string,
// boolean) or a value-ref (typically a params ref so the same tree can be
// re-parameterized per tenant).
export type RightOperand =
  | { kind: "number"; value: number }
  | { kind: "string"; value: string }
  | { kind: "boolean"; value: boolean }
  | { kind: "ref"; ref: ValueRef };

export type Term =
  | { op: BinaryOp; left: ValueRef; right: RightOperand }
  | { op: "between"; left: ValueRef; low: RightOperand; high: RightOperand }
  | { op: "in"; left: ValueRef; values: RightOperand[] };

export type GroupMode = "all" | "any";

/** One node of the editable condition tree. Recursive, mirroring the
 *  backend AST rather than the flattened single/group pair the V1
 *  builder used. */
export type ConditionNode =
  | { kind: "term"; term: Term }
  | { kind: "group"; mode: GroupMode; children: ConditionNode[] }
  | { kind: "not"; child: ConditionNode };

export type EditableCondition =
  | { kind: "empty" }
  | { kind: "node"; node: ConditionNode }
  | { kind: "unsupported"; reason: string; raw: unknown };

// ---- Parse: AST → editable form -----------------------------------

/** Convert a raw `condition.tree` AST into the editable form. Returns
 *  `unsupported` (with the original AST preserved on `raw`) only when the
 *  shape is genuinely unrecognisable — an unknown op, a malformed ref, a
 *  group whose children aren't a list. Callers show a read-only fallback
 *  in that branch. */
export function parseConditionTree(raw: unknown): EditableCondition {
  if (raw === undefined || raw === null) return { kind: "empty" };
  if (!isRecord(raw)) {
    return { kind: "unsupported", reason: "Condition is not an object.", raw };
  }
  const node = parseNode(raw);
  if (!node) {
    return {
      kind: "unsupported",
      reason: "Condition shape not recognised.",
      raw,
    };
  }
  // A top-level group with nothing in it reads as "no condition".
  if (node.kind === "group" && node.children.length === 0) return { kind: "empty" };
  return { kind: "node", node };
}

function parseNode(raw: unknown): ConditionNode | null {
  if (!isRecord(raw)) return null;

  if ("all_of" in raw || "any_of" in raw) {
    const mode: GroupMode = "all_of" in raw ? "all" : "any";
    const children = mode === "all" ? raw.all_of : raw.any_of;
    if (!Array.isArray(children)) return null;
    const parsed: ConditionNode[] = [];
    for (const child of children) {
      const node = parseNode(child);
      if (!node) return null;
      parsed.push(node);
    }
    return { kind: "group", mode, children: parsed };
  }

  if ("not" in raw) {
    const child = parseNode(raw.not);
    if (!child) return null;
    return { kind: "not", child };
  }

  const term = parseTerm(raw);
  return term ? { kind: "term", term } : null;
}

function parseTerm(raw: unknown): Term | null {
  if (!isRecord(raw)) return null;
  const op = raw.op;
  if (typeof op !== "string") return null;
  const left = parseValueRef(raw.left);
  if (!left) return null;

  if (op === "between") {
    const low = parseRightOperand(raw.low);
    const high = parseRightOperand(raw.high);
    if (low === null || high === null) return null;
    return { op: "between", left, low, high };
  }

  if (op === "in") {
    if (!Array.isArray(raw.values)) return null;
    const values: RightOperand[] = [];
    for (const v of raw.values) {
      const parsed = parseRightOperand(v);
      if (parsed === null) return null;
      values.push(parsed);
    }
    return { op: "in", left, values };
  }

  if (!(BINARY_OPS as readonly string[]).includes(op)) return null;
  const right = parseRightOperand(raw.right);
  if (right === null) return null;
  return { op: op as BinaryOp, left, right };
}

function parseValueRef(raw: unknown): ValueRef | null {
  if (!isRecord(raw)) return null;
  const source = raw.source;
  if (source === "indices") {
    const index_code = typeof raw.index_code === "string" ? raw.index_code : "";
    const key = (raw.key ?? "baseline_deviation") as string;
    if (!(INDICES_KEYS as readonly string[]).includes(key)) return null;
    return {
      source: "indices",
      index_code,
      key: key as (typeof INDICES_KEYS)[number],
    };
  }
  if (source === "block") {
    const field = raw.field as string;
    if (!(BLOCK_FIELDS as readonly string[]).includes(field)) return null;
    return { source: "block", field: field as (typeof BLOCK_FIELDS)[number] };
  }
  if (source === "weather") {
    const scope = raw.scope as string;
    if (!(WEATHER_SCOPES as readonly string[]).includes(scope)) return null;
    const field = typeof raw.field === "string" ? raw.field : "";
    return {
      source: "weather",
      scope: scope as (typeof WEATHER_SCOPES)[number],
      field,
    };
  }
  if (source === "weather_index") {
    const index_code = raw.index_code as string;
    if (!(WEATHER_INDEX_CODES as readonly string[]).includes(index_code)) return null;
    const key = (raw.key ?? "baseline_deviation") as string;
    if (!(WEATHER_INDEX_KEYS as readonly string[]).includes(key)) return null;
    return {
      source: "weather_index",
      index_code: index_code as (typeof WEATHER_INDEX_CODES)[number],
      key: key as (typeof WEATHER_INDEX_KEYS)[number],
    };
  }
  if (source === "weather_risk") {
    const risk_code = raw.risk_code as string;
    if (!(WEATHER_RISK_CODES as readonly string[]).includes(risk_code)) return null;
    const field = (raw.field ?? "score") as string;
    if (!(WEATHER_RISK_FIELDS as readonly string[]).includes(field)) return null;
    return {
      source: "weather_risk",
      risk_code: risk_code as (typeof WEATHER_RISK_CODES)[number],
      field: field as (typeof WEATHER_RISK_FIELDS)[number],
    };
  }
  if (source === "water_balance") {
    const field = (raw.field ?? "balance_mm") as string;
    if (!(WATER_BALANCE_FIELDS as readonly string[]).includes(field)) return null;
    return { source: "water_balance", field: field as (typeof WATER_BALANCE_FIELDS)[number] };
  }
  if (source === "signals") {
    const code = typeof raw.code === "string" ? raw.code : "";
    const key = (raw.key ?? "value_numeric") as string;
    if (!(SIGNAL_KEYS as readonly string[]).includes(key)) return null;
    return {
      source: "signals",
      code,
      key: key as (typeof SIGNAL_KEYS)[number],
    };
  }
  if (source === "grid") {
    const index_code = typeof raw.index_code === "string" ? raw.index_code : "";
    const field = raw.field as string;
    if (!(GRID_FIELDS as readonly string[]).includes(field)) return null;
    return {
      source: "grid",
      index_code,
      field: field as (typeof GRID_FIELDS)[number],
    };
  }
  if (source === "crop_attribute") {
    const code = typeof raw.code === "string" ? raw.code : "";
    const key = (raw.key ?? "value") as string;
    if (!(CROP_ATTRIBUTE_KEYS as readonly string[]).includes(key)) return null;
    return {
      source: "crop_attribute",
      code,
      key: key as (typeof CROP_ATTRIBUTE_KEYS)[number],
    };
  }
  if (source === "params") {
    const name = typeof raw.name === "string" ? raw.name : "";
    return { source: "params", name };
  }
  return null;
}

function parseRightOperand(raw: unknown): RightOperand | null {
  if (raw === undefined || raw === null) return null;
  if (typeof raw === "number") return { kind: "number", value: raw };
  if (typeof raw === "string") {
    // Try to coerce numerics so authors who wrote `right: "0.5"` in
    // YAML still get the number editor. YAML usually emits numbers
    // unquoted; coercion is a safety net.
    const asNum = Number(raw);
    if (raw.trim() !== "" && !Number.isNaN(asNum)) {
      return { kind: "number", value: asNum };
    }
    return { kind: "string", value: raw };
  }
  if (typeof raw === "boolean") return { kind: "boolean", value: raw };
  if (isRecord(raw) && "source" in raw) {
    const ref = parseValueRef(raw);
    if (ref) return { kind: "ref", ref };
  }
  return null;
}

// ---- Serialize: editable form → AST -------------------------------

/** Inverse of `parseConditionTree`. A lone comparison emits a flat
 *  comparison node (no group wrapper) so the YAML matches the style the
 *  seeds are written in. */
export function serializeCondition(cond: EditableCondition): unknown {
  if (cond.kind === "empty") return undefined;
  if (cond.kind === "unsupported") return cond.raw;
  return serializeNode(cond.node);
}

export function serializeNode(node: ConditionNode): unknown {
  if (node.kind === "term") return serializeTerm(node.term);
  if (node.kind === "not") return { not: serializeNode(node.child) };
  const key = node.mode === "all" ? "all_of" : "any_of";
  return { [key]: node.children.map(serializeNode) };
}

function serializeTerm(term: Term): Record<string, unknown> {
  if (term.op === "between") {
    return {
      op: "between",
      left: serializeValueRef(term.left),
      low: serializeRightOperand(term.low),
      high: serializeRightOperand(term.high),
    };
  }
  if (term.op === "in") {
    return {
      op: "in",
      left: serializeValueRef(term.left),
      values: term.values.map(serializeRightOperand),
    };
  }
  return {
    op: term.op,
    left: serializeValueRef(term.left),
    right: serializeRightOperand(term.right),
  };
}

function serializeValueRef(ref: ValueRef): Record<string, unknown> {
  switch (ref.source) {
    case "indices":
      return {
        source: "indices",
        index_code: ref.index_code,
        key: ref.key,
      };
    case "block":
      return { source: "block", field: ref.field };
    case "weather":
      return { source: "weather", scope: ref.scope, field: ref.field };
    case "weather_index":
      return { source: "weather_index", index_code: ref.index_code, key: ref.key };
    case "weather_risk":
      return { source: "weather_risk", risk_code: ref.risk_code, field: ref.field };
    case "water_balance":
      return { source: "water_balance", field: ref.field };
    case "signals":
      return { source: "signals", code: ref.code, key: ref.key };
    case "grid":
      return { source: "grid", index_code: ref.index_code, field: ref.field };
    case "crop_attribute":
      return { source: "crop_attribute", code: ref.code, key: ref.key };
    case "params":
      return { source: "params", name: ref.name };
  }
}

function serializeRightOperand(rhs: RightOperand): unknown {
  switch (rhs.kind) {
    case "number":
      return rhs.value;
    case "string":
      return rhs.value;
    case "boolean":
      return rhs.value;
    case "ref":
      return serializeValueRef(rhs.ref);
  }
}

// ---- Term shape transitions ----------------------------------------

/** Switch a term to a different operator, carrying the left ref and as
 *  much of the right-hand side as the new shape can hold. Going binary →
 *  `between` seeds the low bound from the old right operand; → `in`
 *  seeds the first list entry. Going back keeps the low bound / first
 *  entry. Without this an author loses their threshold every time they
 *  try a different operator. */
// ---- Operand typing ------------------------------------------------
//
// The evaluator compares whatever the left ref resolves to against the
// right operand, with no type checking: `soil_texture = 0` parses, saves,
// publishes and then never matches, because a string is never equal to a
// number. The builder used to make that the *default* — every left ref got
// a `number: 0` on the right — so picking a categorical field and typing
// nothing else produced a dead term.
//
// `leftOperandType` says what a ref actually resolves to, and
// `retypeTermForLeft` re-shapes the right side to suit when the author
// changes the left. `leftOperandValues` returns the closed vocabulary when
// there is one, so the operand becomes a picker rather than a text box.

export type OperandType = "number" | "categorical" | "boolean";

/** Trend keys resolve to rising/falling/stable across sources. */
const TREND_VALUES = ["rising", "falling", "stable"] as const;
// Mirrors SoilTexture / SalinityClass in api/blocks.ts (the blocks CHECK
// constraints), the crops catalog `category` values, and the banding
// vocabularies in weather/risk + the grid anomaly verdict.
const SOIL_TEXTURE_VALUES = [
  "sandy",
  "sandy_loam",
  "loam",
  "clay_loam",
  "clay",
  "silty_loam",
  "silty_clay",
] as const;
const SALINITY_VALUES = [
  "non_saline",
  "slightly_saline",
  "moderately_saline",
  "strongly_saline",
] as const;
const RISK_LEVEL_VALUES = ["low", "moderate", "high"] as const;
const GRID_SEVERITY_VALUES = ["warning", "critical"] as const;

export function leftOperandType(ref: ValueRef): OperandType {
  switch (ref.source) {
    case "indices":
      return ref.key === "trend_direction" ? "categorical" : "number";
    case "block":
      // Every block field is a stored string (stage, path, strain, texture,
      // salinity class, crop category).
      return "categorical";
    case "signals":
      if (ref.key === "value_boolean") return "boolean";
      return ref.key === "value_numeric" || ref.key === "value_slope" || ref.key === "value_delta"
        ? "number"
        : "categorical";
    case "weather_risk":
      return ref.field === "level" ? "categorical" : "number";
    case "water_balance":
      // Every field is millimetres or a coefficient except the logged flag,
      // which is the one a tree compares with eq/ne to gate on trustworthiness.
      return ref.field === "irrigation_logged" ? "boolean" : "number";
    case "grid":
      return ref.field === "severity" ? "categorical" : "number";
    case "crop_attribute":
      // The resolved type follows the definition's value_type (numeric, date,
      // text, single- or multi-select), which the builder doesn't know here.
      // Treat as categorical: a string compares sanely against a date or a
      // select, and an author comparing a numeric attribute can still switch
      // the operand kind by hand.
      return "categorical";
    default:
      // weather / weather_index — every field in those snapshots is a Decimal.
      return "number";
  }
}

/** The closed vocabulary for a categorical ref, or null when the values are
 *  open-ended (a crop path, a taxonomy-driven growth stage, a tenant's own
 *  categorical signal). */
export function leftOperandValues(ref: ValueRef): readonly string[] | null {
  if (ref.source === "indices" && ref.key === "trend_direction") return TREND_VALUES;
  if (ref.source === "signals" && ref.key === "value_trend_direction") return TREND_VALUES;
  if (ref.source === "weather_risk" && ref.field === "level") return RISK_LEVEL_VALUES;
  if (ref.source === "grid" && ref.field === "severity") return GRID_SEVERITY_VALUES;
  if (ref.source === "block") {
    if (ref.field === "soil_texture") return SOIL_TEXTURE_VALUES;
    if (ref.field === "salinity_class") return SALINITY_VALUES;
  }
  return null;
}

/** What the right-hand operand should look like for a given left ref.
 *
 *  For most sources this follows from the ref alone, but `signals` and
 *  `crop_attribute` are defined by *data*: the tenant's signal definition or
 *  the platform's crop-attribute definition fixes the type, the legal values,
 *  the bounds and the unit. Those definitions are already fetched to populate
 *  the code dropdowns, so the operand editor can use them too rather than
 *  making the author retype what the platform already knows.
 */
export interface OperandSpec {
  control: "number" | "text" | "select" | "boolean" | "date";
  /** Closed vocabulary. A value outside it can never match, so it is enforced. */
  values?: readonly string[];
  /** Advisory bounds. NOT enforced — see the note on `operandOutOfRange`. */
  min?: number;
  max?: number;
  unit?: string | null;
}

/** The subset of a signal definition the operand editor needs. */
export interface SignalOperandSource {
  value_kind: string;
  categorical_values?: string[] | null;
  value_min?: string | null;
  value_max?: string | null;
  unit?: string | null;
}

/** The subset of a crop-attribute definition the operand editor needs. */
export interface CropAttributeOperandSource {
  value_type: string;
  options?: { code: string }[] | null;
  value_min?: string | null;
  value_max?: string | null;
  unit_en?: string | null;
}

function numeric(raw: string | null | undefined): number | undefined {
  if (raw === null || raw === undefined || raw === "") return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

export function signalOperandSpec(def: SignalOperandSource | undefined): OperandSpec | null {
  if (!def) return null;
  switch (def.value_kind) {
    case "numeric":
      return {
        control: "number",
        min: numeric(def.value_min),
        max: numeric(def.value_max),
        unit: def.unit ?? null,
      };
    case "boolean":
      return { control: "boolean" };
    case "categorical":
      // A categorical signal records one of its declared options and nothing
      // else, so anything outside the list is a guaranteed non-match.
      return def.categorical_values?.length
        ? { control: "select", values: def.categorical_values }
        : { control: "text" };
    default:
      // `event` is free-form text; `geopoint` has no comparable value key.
      return { control: "text" };
  }
}

export function cropAttributeOperandSpec(
  def: CropAttributeOperandSource | undefined,
): OperandSpec | null {
  if (!def) return null;
  switch (def.value_type) {
    case "integer":
    case "decimal":
      return {
        control: "number",
        min: numeric(def.value_min),
        max: numeric(def.value_max),
        unit: def.unit_en ?? null,
      };
    case "boolean":
      return { control: "boolean" };
    case "date":
      return { control: "date" };
    case "single_select":
    case "multi_select":
      return def.options?.length
        ? { control: "select", values: def.options.map((o) => o.code) }
        : { control: "text" };
    default:
      return { control: "text" };
  }
}

/** True when a numeric operand sits outside the definition's recorded bounds.
 *
 *  Deliberately advisory, not blocking. `value_min` / `value_max` describe the
 *  range the platform expects to *record*, and a rule that fires outside it is
 *  often exactly the rule worth writing — "alert if pH goes above 9" on a
 *  signal whose recorded maximum is 8.5. Warning keeps the typo visible without
 *  refusing the alert.
 */
export function operandOutOfRange(spec: OperandSpec | null, operand: RightOperand): boolean {
  if (!spec || spec.control !== "number" || operand.kind !== "number") return false;
  if (spec.min !== undefined && operand.value < spec.min) return true;
  return spec.max !== undefined && operand.value > spec.max;
}

/** The operand kind a spec's control implies, for re-typing on a left change. */
export function specOperandKind(spec: OperandSpec): RightOperand["kind"] {
  if (spec.control === "number") return "number";
  if (spec.control === "boolean") return "boolean";
  return "string";
}

/** Coerce one operand to `type`, keeping the value where it survives the
 *  crossing. A params ref is left alone — it resolves at evaluation time
 *  and re-typing it would throw away the author's parameter name. */
function retypeOperand(operand: RightOperand, type: OperandType): RightOperand {
  if (operand.kind === "ref") return operand;
  if (type === "number") {
    if (operand.kind === "number") return operand;
    const n = operand.kind === "string" ? Number(operand.value) : NaN;
    return { kind: "number", value: Number.isFinite(n) && operand.value !== "" ? n : 0 };
  }
  if (type === "boolean") {
    if (operand.kind === "boolean") return operand;
    return { kind: "boolean", value: operand.kind === "string" && operand.value === "true" };
  }
  if (operand.kind === "string") return operand;
  // A number crossing into a categorical slot is dropped rather than
  // stringified. `growth_stage = "0"` is a filled-in box that can never match;
  // an empty one reads as unfinished, which is what it is. Where the field has
  // a closed vocabulary, retypeTermForLeft seeds a real value over this.
  return { kind: "string", value: "" };
}

/** Swap a term's left ref, re-typing the right side to match it. When the
 *  new left has a closed vocabulary and the carried-over value isn't in it,
 *  seed the first value rather than leaving an empty string that reads as
 *  authored. */
export function retypeTermForLeft(term: Term, left: ValueRef): Term {
  const type = leftOperandType(left);
  const values = leftOperandValues(left);
  const fix = (operand: RightOperand): RightOperand => {
    const next = retypeOperand(operand, type);
    if (values && next.kind === "string" && !values.includes(next.value)) {
      return { kind: "string", value: values[0] };
    }
    return next;
  };
  if (term.op === "between") {
    return { ...term, left, low: fix(term.low), high: fix(term.high) };
  }
  if (term.op === "in") {
    return { ...term, left, values: term.values.map(fix) };
  }
  return { ...term, left, right: fix(term.right) };
}

export function changeTermOp(term: Term, op: TermOp): Term {
  if (term.op === op) return term;
  const carried = firstOperand(term);
  if (op === "between") {
    return { op: "between", left: term.left, low: carried, high: carried };
  }
  if (op === "in") {
    return { op: "in", left: term.left, values: [carried] };
  }
  return { op, left: term.left, right: carried };
}

function firstOperand(term: Term): RightOperand {
  if (term.op === "between") return term.low;
  if (term.op === "in") return term.values[0] ?? { kind: "number", value: 0 };
  return term.right;
}

// ---- Helpers -------------------------------------------------------

export function defaultTerm(): Term {
  return {
    op: "lt",
    left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
    right: { kind: "number", value: 0 },
  };
}

export function defaultTermNode(): ConditionNode {
  return { kind: "term", term: defaultTerm() };
}

export function defaultGroupNode(mode: GroupMode = "all"): ConditionNode {
  return { kind: "group", mode, children: [defaultTermNode()] };
}

export function defaultValueRef(source: ValueRefSource): ValueRef {
  switch (source) {
    case "indices":
      return { source: "indices", index_code: "ndvi", key: "baseline_deviation" };
    case "block":
      return { source: "block", field: "growth_stage" };
    case "weather":
      return { source: "weather", scope: "forecast_24h", field: "precipitation_mm_total" };
    case "weather_index":
      return { source: "weather_index", index_code: "temperature", key: "baseline_deviation" };
    case "weather_risk":
      return { source: "weather_risk", risk_code: "powdery_mildew", field: "score" };
    case "water_balance":
      return { source: "water_balance", field: "balance_mm" };
    case "signals":
      return { source: "signals", code: "", key: "value_numeric" };
    case "grid":
      return { source: "grid", index_code: "ndvi", field: "flagged_count" };
    case "crop_attribute":
      // Empty code: the builder fills it from the fetched catalog, the same
      // way `signals` starts blank.
      return { source: "crop_attribute", code: "", key: "value" };
    case "params":
      return { source: "params", name: "" };
  }
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}
