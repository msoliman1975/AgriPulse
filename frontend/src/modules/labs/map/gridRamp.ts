// The sub-block grid heat ramp, in one place.
//
// This used to live inline in MapCanvas's `addLayer` call, which was fine
// while nothing else needed to know the colours. The index legend does: it
// draws a swatch per class, and a legend whose swatches disagree with the
// pixels underneath reads as a bug.
//
// It lives in `map/` rather than `console/` on purpose — it deals in
// MapLibre expression types, which is exactly the loose-typing surface that
// folder is ESLint-exempt for.
//
// PER-INDEX AS OF THE BSI/MSI WORK. The ramp used to be one index-agnostic
// gradient (grey → red at 0.0 → amber at 0.3 → lime at 0.6 → green at 0.85)
// that assumed bigger = better. The header here already recorded that as a
// known bug for NDWI (McFeeters surface water: high = standing water) and for
// NDMI's negative end, and deferred the fix as "a separate, visible change to
// the map". This is that change, and MSI forced it: MSI is a ratio running
// ~0.2–2.0 where HIGH is bad, so under the old ramp every real reading sat at
// or above the 0.85 stop and a parched block rendered solid healthy green.
//
// Rather than add a second per-index colour table, the stops are derived from
// INDEX_CLASSES — already the single source of truth for what a value means,
// already ordered by verdict rather than by magnitude, and already the table
// the pixel layer and the legend read. So the grid cells, the pixels beneath
// them and the legend beside them now agree by construction instead of by
// three tables being kept in step by hand.
import type { ExpressionSpecification } from "maplibre-gl";

import type { AnyIndexCode as ApiIndexCode } from "@/api/indices";
import { NO_DATA_COLOR, classesFor } from "../console/indexClasses";

/**
 * Value encoded for a cell with no reading. Kept out of the real range.
 *
 * Caveat inherited from the FC-build side: -1 is a legal (if vanishingly
 * rare) reading for the normalized-difference indices, so a genuine -1.0
 * renders as "no data". Not introduced here and not worth a wire-format
 * change on its own, but worth knowing before trusting a grey cell.
 */
export const GRID_NO_DATA = -1;

/**
 * The paint expression MapCanvas installs on the grid fill layer.
 *
 * A `step` rather than an `interpolate`: the classes are discrete and each
 * carries an exact colour, so blending between them would paint values that
 * belong to no class — the same mistake the continuous ramp made, where the
 * gradient's own stops had nothing to do with any class boundary.
 *
 * `step` breaks on `>=` while `classify` uses an inclusive upper bound, so a
 * value sitting EXACTLY on a cut point lands one class higher here than in
 * the legend. That is the same one-ulp disagreement `titilerColormap`
 * documents for the pixel layer, and it is preferable to having the grid and
 * the pixels round opposite ways.
 *
 * `code` is nullable so a caller with no index selected renders every cell as
 * no-data grey rather than borrowing NDVI's verdict for an unknown quantity.
 */
export function gridRampExpression(code: ApiIndexCode | null): ExpressionSpecification | string {
  const value: ExpressionSpecification = ["to-number", ["get", "value"]];
  const classes = code ? classesFor(code) : [];
  // No index, no verdict: a flat colour rather than a degenerate expression,
  // because that is exactly what it means.
  if (classes.length === 0) return NO_DATA_COLOR;

  // Stops after the first: each class's lower bound is the previous class's
  // inclusive max. The last class runs to Infinity and so contributes no stop.
  const steps = classes
    .slice(0, -1)
    .flatMap((c, i) => [c.max, classes[i + 1].color] as [number, string])
    .flat();

  const ramp = ["step", value, classes[0].color, ...steps] as ExpressionSpecification;

  // The sentinel is matched exactly rather than folded into the ramp's bottom
  // class, so "no reading" stays visually distinct from "the worst reading".
  return ["case", ["==", value, GRID_NO_DATA], NO_DATA_COLOR, ramp];
}
