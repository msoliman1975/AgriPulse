// The extent the replay map frames on.
//
// Pure geometry, in its own module so it can be tested without importing
// maplibre-gl — which touches `window.URL.createObjectURL` at import time
// and so cannot be loaded under jsdom at all. Anything worth asserting
// about the map has to live outside the component for that reason.

import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";

/** `[[west, south], [east, north]]`, or null when there is nothing to frame. */
export type Extent = [[number, number], [number, number]];

/**
 * The bounding box of the farm's blocks, widened to its AOI.
 *
 * Returns null when neither has loaded. That null is not an edge case, it
 * is the state the map mounts in on every cold load: the component is
 * constructed before the block list arrives, so the constructor's `bounds`
 * option has nothing to work with and the framing has to happen later,
 * when the data and the map are both ready.
 */
export function boundsOf<P>(
  blocks: FeatureCollection<Polygon, P>,
  farmBoundary: MultiPolygon | null,
): Extent | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  const visit = (ring: number[][]): void => {
    for (const [lon, lat] of ring) {
      if (lon < west) west = lon;
      if (lon > east) east = lon;
      if (lat < south) south = lat;
      if (lat > north) north = lat;
    }
  };
  for (const f of blocks.features) for (const ring of f.geometry.coordinates) visit(ring);
  if (farmBoundary) for (const poly of farmBoundary.coordinates) for (const r of poly) visit(r);
  if (!Number.isFinite(west) || !Number.isFinite(south)) return null;
  return [
    [west, south],
    [east, north],
  ];
}

/**
 * MapLibre's source `bounds`: a FLAT `[west, south, east, north]`.
 *
 * Deliberately a different type from `Extent`, which is the nested pair
 * `fitBounds` takes. The two are trivially convertible and easy to swap by
 * accident, and swapping them silently produces a box on the equator.
 */
export type SourceBounds = [number, number, number, number];

/**
 * How far to widen a raster's declared bounds beyond the ground it covers.
 *
 * `bounds` on a raster source suppresses tile REQUESTS outside the box, so
 * a box that is too small does not merely save traffic — it silently drops
 * the edge of the image. The stored COG is cut on its own 10 m pixel grid
 * and keeps whole any pixel whose centre is inside the AOI, so colour runs
 * up to ~5 m past the boundary, and 15 m on the 30 m thermal product.
 *
 * 0.002 degrees is roughly 220 m at this latitude — two orders of
 * magnitude more than that overhang, and still a small fraction of a farm.
 * The saving comes from the viewport being far larger than the farm, not
 * from the box being tight, so there is nothing to gain by trimming it.
 */
const BOUNDS_PAD_DEG = 0.002;

/** `[west, south, east, north]` of a MultiPolygon, or undefined if empty. */
export function boundsOfMultiPolygon(
  mp: MultiPolygon | null | undefined,
): SourceBounds | undefined {
  if (!mp) return undefined;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const poly of mp.coordinates) {
    for (const ring of poly) {
      for (const [lon, lat] of ring) {
        if (lon < west) west = lon;
        if (lon > east) east = lon;
        if (lat < south) south = lat;
        if (lat > north) north = lat;
      }
    }
  }
  return Number.isFinite(west) && Number.isFinite(south) ? [west, south, east, north] : undefined;
}

/** The smallest box containing both, or whichever one exists. */
export function unionBounds(
  a: SourceBounds | undefined,
  b: SourceBounds | undefined,
): SourceBounds | undefined {
  if (!a) return b;
  if (!b) return a;
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
}

/** Widen a box by `BOUNDS_PAD_DEG` on every side. See that constant. */
export function padBounds(b: SourceBounds | undefined): SourceBounds | undefined {
  if (!b) return undefined;
  return [
    b[0] - BOUNDS_PAD_DEG,
    b[1] - BOUNDS_PAD_DEG,
    b[2] + BOUNDS_PAD_DEG,
    b[3] + BOUNDS_PAD_DEG,
  ];
}
