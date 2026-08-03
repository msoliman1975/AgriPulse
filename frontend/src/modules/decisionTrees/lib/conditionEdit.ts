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
export const INDEX_CODES = ["ndvi", "ndwi", "evi", "savi", "ndre", "gndvi", "ndmi"] as const;
export const BLOCK_FIELDS = [
  "crop_category",
  // KB P3: the block's current phenological stage, resolved from the crop
  // taxonomy and auto-advanced daily.
  "growth_stage",
  // Crop taxonomy: hierarchical path (`mango.alphonso.short`) + strain leaf.
  "crop_path",
  "crop_strain",
  "soil_texture",
  "salinity_class",
  "canopy_size_class",
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
// First-class weather indices (PR-W7). `value` is the farm-level daily
// value; `baseline_deviation` is its z-score vs the day-of-year
// climatology. Mirrors WEATHER_INDEX_KEYS in
// backend/app/shared/conditions/context.py.
export const WEATHER_INDEX_KEYS = ["value", "baseline_deviation"] as const;
// The seven catalog codes (public weather_indices_catalog). Kept as a
// closed list so the author picks from a dropdown rather than guessing
// a code; mirrors the migration 0037 seed.
export const WEATHER_INDEX_CODES = [
  "temperature",
  "radiation",
  "wind",
  "rainfall",
  "evapotranspiration",
  "evaporation_coeff",
  "rain_et_balance",
] as const;
// Per-block weather-driven disease/pest risk fields (PR-R3). `score` is the
// 0-100 pressure; `level` its low|moderate|high banding. Mirrors
// WEATHER_RISK_FIELDS in backend/app/shared/conditions/context.py.
export const WEATHER_RISK_FIELDS = ["score", "level"] as const;
// The mango V1 pathogen/pest codes (weather.risk registry). Closed list so
// the author picks from a dropdown; mirrors REGISTRY in
// backend/app/modules/weather/risk/registry.py.
export const WEATHER_RISK_CODES = ["powdery_mildew", "anthracnose", "fruit_fly"] as const;
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
  | "signals"
  | "grid"
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
  | { source: "signals"; code: string; key: (typeof SIGNAL_KEYS)[number] }
  | { source: "grid"; index_code: string; field: (typeof GRID_FIELDS)[number] }
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
    case "signals":
      return { source: "signals", code: ref.code, key: ref.key };
    case "grid":
      return { source: "grid", index_code: ref.index_code, field: ref.field };
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
      return { source: "block", field: "crop_category" };
    case "weather":
      return { source: "weather", scope: "forecast_24h", field: "precipitation_mm_total" };
    case "weather_index":
      return { source: "weather_index", index_code: "temperature", key: "baseline_deviation" };
    case "weather_risk":
      return { source: "weather_risk", risk_code: "powdery_mildew", field: "score" };
    case "signals":
      return { source: "signals", code: "", key: "value_numeric" };
    case "grid":
      return { source: "grid", index_code: "ndvi", field: "flagged_count" };
    case "params":
      return { source: "params", name: "" };
  }
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}
