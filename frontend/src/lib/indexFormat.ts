// Formatting for imagery-index values.
//
// Every index was a dimensionless ratio until `lst` (Landsat surface
// temperature) arrived, so the charts hardcoded `value.toFixed(3)`. That
// is wrong for a temperature twice over: `31.850` implies a precision a
// 100 m thermal pixel does not have, and a bare `31.85` sitting next to
// an NDVI of `0.723` reads as the same kind of number when it is not.
//
// The unit comes from `public.indices_catalog.unit` via
// `GET /api/v1/indices/catalog` — deliberately not hardcoded here, since
// a hardcoded table is exactly what drifted from the backend and left
// `ndmi` uncheckable in Insights for a year.

/** Decimals for a dimensionless index — a normalized difference or ratio. */
export const DIMENSIONLESS_DECIMALS = 3;

/**
 * Decimals per unit symbol, for the units that need something other than
 * the dimensionless default.
 *
 * Surface temperature is delivered from a 100 m native sensor resampled
 * onto a 30 m grid; one decimal already overstates it, and three would be
 * false precision dressed up as rigour.
 */
export const UNIT_DECIMALS: Readonly<Record<string, number>> = {
  "°C": 1,
};

/** How many decimals to render for a value carrying `unit`. */
export function indexDecimals(unit: string | null | undefined): number {
  if (!unit) return DIMENSIONLESS_DECIMALS;
  return UNIT_DECIMALS[unit] ?? DIMENSIONLESS_DECIMALS;
}

/**
 * Render an index value with its unit, e.g. `0.723` or `31.9 °C`.
 *
 * An empty or missing unit is the dimensionless case and yields a bare
 * number, so callers need no special case — the same shape
 * `WeatherTrendsPanel` already uses for weather indices.
 */
export function formatIndexValue(
  value: number | null | undefined,
  unit: string | null | undefined,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const rendered = value.toFixed(indexDecimals(unit));
  return unit ? `${rendered} ${unit}` : rendered;
}

/**
 * Axis-tick form: the number alone, at the unit's precision.
 *
 * The unit belongs on the axis label, not repeated down every tick.
 */
export function formatIndexTick(
  value: number | null | undefined,
  unit: string | null | undefined,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return value.toFixed(indexDecimals(unit));
}
