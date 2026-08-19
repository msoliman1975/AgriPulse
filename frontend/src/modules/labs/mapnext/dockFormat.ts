// Pure helpers for the Block Dock. Kept out of the component files so the
// tricky bits — reading a condition step back into "actual vs. threshold" —
// are unit-testable without rendering anything.
import type { AnyIndexCode as ApiIndexCode } from "@/api/indices";
import type { ExplainStep } from "@/api/recommendations";
import { chartDateLocale } from "@/lib/chartFormat";

import { HEALTH_DOT, HIGHER_IS_WORSE, INDEX_BANDS, type IndexBand } from "./constants";

export function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

/** Change thresholds in the index's own units: below `small` is flat, past
 *  `big` in the wrong direction is a real move.
 *
 *  Split by unit, not by index. The twelve dimensionless indices live in
 *  roughly [-1, 3] and keep the original inspector's numbers. `lst` is
 *  degrees Celsius on a 0-60 scale, where 0.01 is noise from a 100 m pixel
 *  and 0.05 would flag every scene as a critical drop. */
function deltaThresholds(unit: string | null | undefined): { small: number; big: number } {
  return unit === "°C" ? { small: 0.5, big: 2 } : { small: 0.01, big: 0.05 };
}

/** A change in one index as arrow + signed text + severity colour.
 *
 * The thresholds are the original inspector's: a small rise is good news, a
 * small fall is worth watching, and anything past -0.05 in a week is a real
 * drop. Two things this adds, which the old number-only `deltaLabel` it
 * replaces could not know:
 *
 *   * DIRECTION. Ten indices read "higher is a better canopy" and three do
 *     not, so a +6 °C week on LST was painted green, as were rising MSI
 *     (water stress) and rising NDWI (water standing on the block). The
 *     colour now follows HIGHER_IS_WORSE; the arrow still follows the number,
 *     because the arrow states what happened and the colour states whether
 *     that is good.
 *   * UNIT. `+0.02` and `+0.02 °C` are not the same statement, and the second
 *     is below what the sensor resolves.
 */
export function indexDeltaLabel(
  code: ApiIndexCode,
  d: number | null | undefined,
  unit?: string | null,
): { text: string; arrow: string; color: string } {
  if (d == null || !Number.isFinite(d)) {
    return { text: "—", arrow: "→", color: HEALTH_DOT.unknown };
  }
  const { small, big } = deltaThresholds(unit);
  const digits = unit === "°C" ? 1 : 2;
  const arrow = d > small ? "▲" : d < -small ? "▼" : "→";
  const text =
    Math.abs(d) <= small
      ? "±0"
      : `${d > 0 ? "+" : ""}${d.toFixed(digits)}${unit ? ` ${unit}` : ""}`;

  // Positive `toward` means the block moved the way this index calls better.
  const toward = HIGHER_IS_WORSE.has(code) ? -d : d;
  const color =
    toward > small
      ? HEALTH_DOT.healthy
      : toward < -big
        ? HEALTH_DOT.critical
        : toward < -small
          ? HEALTH_DOT.watch
          : HEALTH_DOT.unknown;
  return { text, arrow, color };
}

/** Which interpretation band a reading falls in, or null when there is nothing
 * to interpret — a block the pipeline has not produced a clear scene for, or
 * one whose farm holds no subscription to the product that index comes from.
 *
 * Bands are ascending and inclusive on `max`, so the first one the value fits
 * under wins. The Infinity terminator makes the fallback unreachable in
 * practice; it is there so a hand-edited table that loses it degrades to "top
 * band" rather than to null. NaN is treated as no reading, not as a band. */
export function bandFor(code: ApiIndexCode, value: number | null | undefined): IndexBand | null {
  if (value == null || !Number.isFinite(value)) return null;
  const bands = INDEX_BANDS[code];
  if (!bands?.length) return null;
  return bands.find((b) => value <= b.max) ?? bands[bands.length - 1];
}

/** `fruit_set` → `Fruit set`. Last-resort rendering for a raw enum value with
 * no entry in a translated catalogue — always English, so pass a `t()` lookup
 * through `defaultValue` rather than calling this directly where a catalogue
 * exists (see `activityLabel`). */
export function humanize(raw: string | null | undefined): string {
  if (!raw) return "—";
  const s = raw.replace(/_/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "—";
}

/** Every date in the dock formats against the UI language, not the browser's.
 * `undefined` here meant an Arabic UI on an English-locale browser kept
 * printing "Jun 15" next to Arabic labels. */
export function shortDate(iso: string | null | undefined, lang?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(chartDateLocale(lang), {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

/** Observation dates in the title bar carry the year — a block last seen in
 * a previous season should not read as a recent one. */
export function longDate(iso: string | null | undefined, lang?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(chartDateLocale(lang), {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

/** Weekday chip over a 3-day forecast column. */
export function weekday(iso: string | null | undefined, lang?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(chartDateLocale(lang), { weekday: "short" });
  } catch {
    return iso;
  }
}

/** Crop · variety · strain, from the block's current assignment.
 *
 * NB: read the ASSIGNMENT, not `UnitDetail.crop` — that field is a hardcoded
 * null left over from the map prototype, so anything reading it renders every
 * block as unassigned. See loadUnitDetail in ../map/api.ts.
 */
export function cropLabel(
  assignment:
    | { crop_name: string; variety_name: string | null; strain_name: string | null }
    | null
    | undefined,
): string | null {
  if (!assignment) return null;
  return [assignment.crop_name, assignment.variety_name, assignment.strain_name]
    .filter(Boolean)
    .join(" · ");
}

/** ISO yyyy-mm-dd, `days` before `to` (default today). */
export function isoDaysBefore(days: number, to: Date = new Date()): string {
  const d = new Date(to.getTime() - days * 86_400_000);
  return d.toISOString().slice(0, 10);
}

export function isoDay(d: Date = new Date()): string {
  return d.toISOString().slice(0, 10);
}

// ---- condition reading ----------------------------------------------------

/** Mirrors `_ref_key` in backend/app/shared/conditions/evaluator.py — the
 * dotted key a resolved value is filed under in `ExplainStep.values`. */
export function refKey(ref: unknown): string | null {
  if (ref == null || typeof ref !== "object") return null;
  const r = ref as Record<string, unknown>;
  const src = r.source;
  if (typeof src !== "string") return null;
  switch (src) {
    case "indices":
      return `indices.${String(r.index_code)}.${String(r.key)}`;
    case "weather":
      return `weather.${String(r.scope)}.${String(r.field)}`;
    case "weather_index":
      return `weather_index.${String(r.index_code)}.${String(r.key)}`;
    case "weather_risk":
      return `weather_risk.${String(r.risk_code)}.${String(r.field)}`;
    case "signals":
      return `signals.${String(r.code)}.${String(r.key)}`;
    case "grid":
      return `grid.${String(r.index_code)}.${String(r.field)}`;
    case "params":
      return `params.${String(r.name)}`;
    case "block":
      return `block.${String(r.field)}`;
    default:
      return null;
  }
}

const OP_SYMBOL: Record<string, string> = {
  lt: "<",
  le: "≤",
  gt: ">",
  ge: "≥",
  eq: "=",
  ne: "≠",
};

/** A comparison operand as text: a literal prints itself, a ref prints the
 * value it resolved to (so a `$params.threshold` reads as a number, not a
 * variable name). Returns null when neither is available. */
function operandText(raw: unknown, values: Record<string, string>): string | null {
  if (raw == null) return null;
  if (typeof raw === "object") {
    // Both sides of a comparison may be refs — the evaluator resolves them
    // into the same `values` map, keyed by dotted ref.
    const key = refKey(raw);
    return key ? (values[key] ?? null) : null;
  }
  if (typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean") {
    return String(raw);
  }
  return null;
}

export interface ConditionReading {
  /** e.g. "0.39" — what the block actually measured. */
  actual: string | null;
  /** e.g. "≥ 0.45" — the bar it had to clear. */
  threshold: string | null;
  /** Every resolved ref, for compound conditions we can't summarise. */
  values: [string, string][];
}

/** Reduce one visited node to the numbers a reader needs.
 *
 * Simple comparisons ("ndvi ≥ 0.45") get an actual/threshold pair. Compound
 * nodes (all_of / any_of / not) have no single threshold, so they fall back
 * to listing whatever refs resolved — better than showing nothing. */
export function readCondition(step: ExplainStep): ConditionReading {
  const values = Object.entries(step.values ?? {});
  const cond = step.condition;
  if (!cond || typeof cond.op !== "string") {
    return { actual: null, threshold: null, values };
  }

  const leftKey = refKey(cond.left);
  const actual = leftKey ? (step.values?.[leftKey] ?? null) : null;

  if (cond.op === "between") {
    const lo = operandText(cond.low, step.values ?? {});
    const hi = operandText(cond.high, step.values ?? {});
    return {
      actual,
      threshold: lo != null && hi != null ? `${lo}–${hi}` : null,
      values,
    };
  }

  if (cond.op === "in") {
    const list = Array.isArray(cond.values)
      ? cond.values.map((v) => operandText(v, step.values ?? {})).filter((v): v is string => v != null)
      : [];
    return { actual, threshold: list.length ? list.join(", ") : null, values };
  }

  const symbol = OP_SYMBOL[cond.op];
  const right = operandText(cond.right, step.values ?? {});
  return {
    actual,
    threshold: symbol && right != null ? `${symbol} ${right}` : null,
    values,
  };
}

/** Decision steps are the checks; the trailing leaf is the verdict. */
export function decisionSteps(steps: ExplainStep[]): ExplainStep[] {
  return steps.filter((s) => s.matched !== null);
}

export function leafStep(steps: ExplainStep[]): ExplainStep | null {
  const leaves = steps.filter((s) => s.matched === null);
  return leaves.length ? leaves[leaves.length - 1] : null;
}

/** How many checks a tree failed — drives the tab's count badge. */
export function failingCount(steps: ExplainStep[]): number {
  return steps.filter((s) => s.matched === false).length;
}
