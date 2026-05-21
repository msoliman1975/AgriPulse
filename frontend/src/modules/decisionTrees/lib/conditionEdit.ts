// Pure helpers for the visual condition builder (PR-D5).
//
// The condition AST (see backend/app/shared/conditions/evaluator.py) is
// expressive: boolean groups (all_of / any_of / not), six comparison
// ops + between + in, refs from five sources (indices, block, weather,
// signals, params). The V1 builder covers the common case observed in
// the seeds + most authored trees:
//
//   * One comparison node, OR
//   * One all_of / any_of group of comparison nodes (single level)
//
// Anything else — nested groups, `not`, `between`, `in`, mixed
// shapes — falls into the `unsupported` form, and the panel surfaces a
// read-only JSON + "edit this in the YAML editor" hint. We never throw
// away the original AST; the panel keeps it around and the YAML save
// path emits it untouched.

// ---- Domain constants ----------------------------------------------

// Mirrors backend constants in `backend/app/shared/conditions/{models,context}.py`.
// Keep in lock-step.
export const INDICES_KEYS = ["mean", "baseline_deviation"] as const;
export const BLOCK_FIELDS = ["crop_category"] as const;
export const SIGNAL_KEYS = [
  "value_numeric",
  "value_categorical",
  "value_event",
  "value_boolean",
] as const;
export const WEATHER_SCOPES = [
  "latest_observation",
  "forecast_24h",
  "forecast_72h",
  "derived_today",
  "derived_yesterday",
] as const;

// Comparison ops the V1 builder surfaces in the operator dropdown.
// `between` and `in` exist in the engine but are deferred to YAML —
// they need range / set inputs the row UI doesn't model yet.
export const COMPARISON_OPS = ["lt", "le", "gt", "ge", "eq", "ne"] as const;
export type ComparisonOp = (typeof COMPARISON_OPS)[number];

// ---- AST types -----------------------------------------------------

export type ValueRefSource = "indices" | "block" | "weather" | "signals" | "params";

export type ValueRef =
  | { source: "indices"; index_code: string; key: (typeof INDICES_KEYS)[number] }
  | { source: "block"; field: (typeof BLOCK_FIELDS)[number] }
  | { source: "weather"; scope: (typeof WEATHER_SCOPES)[number]; field: string }
  | { source: "signals"; code: string; key: (typeof SIGNAL_KEYS)[number] }
  | { source: "params"; name: string };

// The right-hand side of a binary comparison can be a literal (number,
// string, boolean) or a value-ref (typically a params ref so the same
// tree can be re-parameterized per tenant).
export type RightOperand =
  | { kind: "number"; value: number }
  | { kind: "string"; value: string }
  | { kind: "boolean"; value: boolean }
  | { kind: "ref"; ref: ValueRef };

export interface ComparisonTerm {
  op: ComparisonOp;
  left: ValueRef;
  right: RightOperand;
}

export type GroupMode = "all" | "any";

export type EditableCondition =
  | { kind: "single"; term: ComparisonTerm }
  | { kind: "group"; mode: GroupMode; terms: ComparisonTerm[] }
  | { kind: "empty" }
  | { kind: "unsupported"; reason: string; raw: unknown };

// ---- Parse: AST → editable form -----------------------------------

/** Convert a raw `condition.tree` AST into the editable form. Returns
 *  `unsupported` (with the original AST preserved on `raw`) whenever the
 *  shape isn't one of the simple cases the V1 builder handles. Callers
 *  show a read-only fallback in that branch. */
export function parseConditionTree(raw: unknown): EditableCondition {
  if (raw === undefined || raw === null) return { kind: "empty" };
  if (!isRecord(raw)) {
    return { kind: "unsupported", reason: "Condition is not an object.", raw };
  }
  // Boolean group?
  if ("all_of" in raw || "any_of" in raw) {
    const mode: GroupMode = "all_of" in raw ? "all" : "any";
    const children = (mode === "all" ? raw.all_of : raw.any_of) as unknown;
    if (!Array.isArray(children)) {
      return {
        kind: "unsupported",
        reason: `'${mode}_of' must be a list.`,
        raw,
      };
    }
    const parsedTerms: ComparisonTerm[] = [];
    for (const child of children) {
      const term = parseComparison(child);
      if (!term) {
        return {
          kind: "unsupported",
          reason: "Nested groups, NOT, BETWEEN and IN are edited in YAML.",
          raw,
        };
      }
      parsedTerms.push(term);
    }
    if (parsedTerms.length === 0) return { kind: "empty" };
    if (parsedTerms.length === 1) {
      return { kind: "single", term: parsedTerms[0] };
    }
    return { kind: "group", mode, terms: parsedTerms };
  }
  if ("not" in raw) {
    return {
      kind: "unsupported",
      reason: "NOT groups are edited in YAML.",
      raw,
    };
  }
  // Single comparison?
  const term = parseComparison(raw);
  if (term) return { kind: "single", term };
  return {
    kind: "unsupported",
    reason: "Condition shape not handled by the visual builder.",
    raw,
  };
}

function parseComparison(raw: unknown): ComparisonTerm | null {
  if (!isRecord(raw)) return null;
  const op = raw.op;
  if (typeof op !== "string") return null;
  if (!(COMPARISON_OPS as readonly string[]).includes(op)) {
    // between / in — defer to YAML for V1.
    return null;
  }
  const left = parseValueRef(raw.left);
  if (!left) return null;
  const right = parseRightOperand(raw.right);
  if (right === null) return null;
  return { op: op as ComparisonOp, left, right };
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

/** Inverse of `parseConditionTree`. Single-term editable forms emit
 *  a flat comparison node so the YAML matches the pre-builder style. */
export function serializeCondition(cond: EditableCondition): unknown {
  if (cond.kind === "empty") return undefined;
  if (cond.kind === "unsupported") return cond.raw;
  if (cond.kind === "single") return serializeComparison(cond.term);
  // Group: keep the original `${mode}_of` key.
  const key = cond.mode === "all" ? "all_of" : "any_of";
  return { [key]: cond.terms.map(serializeComparison) };
}

function serializeComparison(term: ComparisonTerm): Record<string, unknown> {
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
    case "signals":
      return { source: "signals", code: ref.code, key: ref.key };
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

// ---- Helpers -------------------------------------------------------

export function defaultComparisonTerm(): ComparisonTerm {
  return {
    op: "lt",
    left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
    right: { kind: "number", value: 0 },
  };
}

export function defaultValueRef(source: ValueRefSource): ValueRef {
  switch (source) {
    case "indices":
      return { source: "indices", index_code: "ndvi", key: "baseline_deviation" };
    case "block":
      return { source: "block", field: "crop_category" };
    case "weather":
      return { source: "weather", scope: "forecast_24h", field: "precipitation_mm_total" };
    case "signals":
      return { source: "signals", code: "", key: "value_numeric" };
    case "params":
      return { source: "params", name: "" };
  }
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}
