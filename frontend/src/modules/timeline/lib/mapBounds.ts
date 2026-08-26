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
