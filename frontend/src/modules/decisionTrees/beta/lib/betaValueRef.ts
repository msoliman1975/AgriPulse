/**
 * The value-ref vocabulary, and how to read one back as text.
 *
 * Separate from `components/ValueRefField.tsx` so the canvas can describe a
 * ref without importing a form, and so neither file mixes components with
 * constants.
 *
 * The source lists come from `lib/conditionEdit.ts`, never a second copy: an
 * index code that existed in one editor and not the other would be a silent
 * gap between two screens authoring one engine. `vars` is the one source the
 * condition builder does not have — section 4.2 adds it, so a `set` node can
 * write a variable a later condition reads back.
 */

import {
  BLOCK_FIELDS,
  GRID_FIELDS,
  INDEX_CODES,
  INDICES_KEYS,
  SIGNAL_KEYS,
  WATER_BALANCE_FIELDS,
  WEATHER_FIELDS,
  WEATHER_INDEX_CODES,
  WEATHER_INDEX_KEYS,
  WEATHER_RISK_CODES,
  WEATHER_RISK_FIELDS,
  WEATHER_SCOPES,
} from "../../lib/conditionEdit";

export const BETA_VALUE_SOURCES = [
  "indices",
  "block",
  "weather",
  "weather_index",
  "weather_risk",
  "water_balance",
  "signals",
  "grid",
  "crop_attribute",
  "params",
  "vars",
] as const;

export type BetaValueSource = (typeof BETA_VALUE_SOURCES)[number];

export type BetaValueRef = Record<string, unknown> & { source: BetaValueSource };

export interface ValueRefFieldSpec {
  key: string;
  labelKey: string;
  options?: readonly string[];
}

export function defaultBetaValueRef(source: BetaValueSource): BetaValueRef {
  switch (source) {
    case "indices":
      return { source, index_code: "ndvi", key: "baseline_deviation" };
    case "block":
      return { source, field: BLOCK_FIELDS[0] };
    case "weather":
      return { source, scope: WEATHER_SCOPES[0], field: WEATHER_FIELDS[WEATHER_SCOPES[0]][0] };
    case "weather_index":
      return { source, index_code: WEATHER_INDEX_CODES[0], key: WEATHER_INDEX_KEYS[0] };
    case "weather_risk":
      return { source, risk_code: WEATHER_RISK_CODES[0], field: WEATHER_RISK_FIELDS[0] };
    case "water_balance":
      return { source, field: WATER_BALANCE_FIELDS[0] };
    case "signals":
      return { source, code: "", key: SIGNAL_KEYS[0] };
    case "grid":
      return { source, index_code: "ndvi", field: GRID_FIELDS[0] };
    case "crop_attribute":
      return { source, code: "", key: "value" };
    case "params":
      return { source, name: "" };
    case "vars":
      return { source, name: "" };
  }
}

/** Which two or three fields this source has. */
export function valueRefFields(ref: BetaValueRef): ValueRefFieldSpec[] {
  switch (ref.source) {
    case "indices":
      return [
        { key: "index_code", labelKey: "indexCode", options: INDEX_CODES },
        { key: "key", labelKey: "key", options: INDICES_KEYS },
      ];
    case "block":
      return [{ key: "field", labelKey: "field", options: BLOCK_FIELDS }];
    case "weather": {
      const scope = scalarText(ref.scope) || WEATHER_SCOPES[0];
      const fields = WEATHER_FIELDS[scope as (typeof WEATHER_SCOPES)[number]] ?? [];
      return [
        { key: "scope", labelKey: "scope", options: WEATHER_SCOPES },
        { key: "field", labelKey: "field", options: fields },
      ];
    }
    case "weather_index":
      return [
        { key: "index_code", labelKey: "indexCode", options: WEATHER_INDEX_CODES },
        { key: "key", labelKey: "key", options: WEATHER_INDEX_KEYS },
      ];
    case "weather_risk":
      return [
        { key: "risk_code", labelKey: "riskCode", options: WEATHER_RISK_CODES },
        { key: "field", labelKey: "field", options: WEATHER_RISK_FIELDS },
      ];
    case "water_balance":
      return [{ key: "field", labelKey: "field", options: WATER_BALANCE_FIELDS }];
    case "signals":
      return [
        { key: "code", labelKey: "code" },
        { key: "key", labelKey: "key", options: SIGNAL_KEYS },
      ];
    case "grid":
      return [
        { key: "index_code", labelKey: "indexCode", options: INDEX_CODES },
        { key: "field", labelKey: "field", options: GRID_FIELDS },
      ];
    case "crop_attribute":
      return [{ key: "code", labelKey: "code" }];
    case "params":
    case "vars":
      return [{ key: "name", labelKey: "name" }];
  }
}

export function asBetaValueRef(value: unknown): BetaValueRef {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const r = value as Record<string, unknown>;
    if (
      typeof r.source === "string" &&
      (BETA_VALUE_SOURCES as readonly string[]).includes(r.source)
    ) {
      return r as BetaValueRef;
    }
  }
  return defaultBetaValueRef("indices");
}

/**
 * An unknown read back as text, or "" when it is not a scalar.
 *
 * YAML authors can put anything in these fields. `String(x)` on an object
 * prints "[object Object]" into an input, which then saves that string over
 * the author's structure — so a non-scalar returns nothing rather than
 * something that looks typed.
 */
export function scalarText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

/** A one-line reading of a ref, for a node body. Codes are not translated —
 *  a code reads the same in both languages. */
export function describeValueRef(ref: unknown): string {
  if (!ref || typeof ref !== "object") return scalarText(ref) || "—";
  const r = ref as Record<string, unknown>;
  const parts = ["source", "index_code", "risk_code", "code", "name", "scope", "key", "field"]
    .map((k) => scalarText(r[k]))
    .filter((v) => v !== "");
  return parts.join(".") || "—";
}

/** A switch case's value, or a condition's right-hand side, as one line. */
export function describeOperand(value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => scalarText(v)).join(" | ");
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return describeValueRef(value);
  return scalarText(value);
}
