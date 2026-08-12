// The sub-block grid heat ramp, in one place.
//
// This used to live inline in MapCanvas's `addLayer` call, which was fine
// while nothing else needed to know the colours. The index legend does: it
// draws a swatch per class, and a legend whose swatches disagree with the
// pixels underneath reads as a bug. Both now derive from GRID_RAMP_STOPS.
//
// It lives in `map/` rather than `console/` on purpose — it deals in
// MapLibre expression types, which is exactly the loose-typing surface that
// folder is ESLint-exempt for.
//
// KNOWN LIMITATION, pre-existing and deliberately preserved here rather than
// silently "fixed": the ramp is index-agnostic and assumes bigger = better.
// That is wrong for NDWI (McFeeters surface water — high means standing
// water) and for the negative end of NDMI. Those indices' low bands sample
// in the grey→red segment below. Changing the ramp per index is a separate,
// visible change to the map; it is not something a legend refactor should
// smuggle in. See the Slice 3 note in the plan.
import type { ExpressionSpecification } from "maplibre-gl";

/** Value encoded for a cell with no reading. Kept out of the real range. */
export const GRID_NO_DATA = -1;

/**
 * Ramp control points, ascending by value. MapLibre interpolates linearly
 * between them; `gridRampColor` reproduces that arithmetic for the legend.
 */
export const GRID_RAMP_STOPS: readonly (readonly [number, string])[] = [
  [GRID_NO_DATA, "#9ca3af"], // no data
  [0.0, "#dc2626"], // very low — bare or water
  [0.3, "#f59e0b"], // stressed
  [0.6, "#84cc16"], // moderate
  [0.85, "#16a34a"], // healthy
] as const;

/** The paint expression MapCanvas installs on the grid fill layer. */
export function gridRampExpression(): ExpressionSpecification {
  return [
    "interpolate",
    ["linear"],
    ["to-number", ["get", "value"]],
    ...GRID_RAMP_STOPS.flatMap(([value, color]) => [value, color]),
  ] as ExpressionSpecification;
}

function hexToRgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex(r: number, g: number, b: number): string {
  const clamp = (v: number): number => Math.max(0, Math.min(255, Math.round(v)));
  return `#${((clamp(r) << 16) | (clamp(g) << 8) | clamp(b)).toString(16).padStart(6, "0")}`;
}

/**
 * The colour the map would paint for `value`. Mirrors MapLibre's
 * `interpolate/linear`: clamped at both ends, linear in sRGB between stops.
 */
export function gridRampColor(value: number): string {
  if (!Number.isFinite(value)) return GRID_RAMP_STOPS[0][1];
  const stops = GRID_RAMP_STOPS;
  if (value <= stops[0][0]) return stops[0][1];
  const last = stops[stops.length - 1];
  if (value >= last[0]) return last[1];
  for (let i = 0; i < stops.length - 1; i += 1) {
    const [v0, c0] = stops[i];
    const [v1, c1] = stops[i + 1];
    if (value >= v0 && value <= v1) {
      const f = v1 === v0 ? 0 : (value - v0) / (v1 - v0);
      const [r0, g0, b0] = hexToRgb(c0);
      const [r1, g1, b1] = hexToRgb(c1);
      return rgbToHex(r0 + (r1 - r0) * f, g0 + (g1 - g0) * f, b0 + (b1 - b0) * f);
    }
  }
  return last[1];
}
