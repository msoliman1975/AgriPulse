// What the map should frame, as a bounding box.
//
// Kept out of the map component so the three "fit" answers can be tested
// without WebGL: jsdom has none, and a framing that is subtly wrong looks
// plausible in a screenshot.

import type { Polygon } from "geojson";

export interface Bounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

/** Grow a box to include a point. */
function extend(box: Bounds | null, lon: number, lat: number): Bounds {
  if (box === null) return { west: lon, south: lat, east: lon, north: lat };
  return {
    west: Math.min(box.west, lon),
    south: Math.min(box.south, lat),
    east: Math.max(box.east, lon),
    north: Math.max(box.north, lat),
  };
}

export function boundsOfRings(rings: [number, number][][]): Bounds | null {
  let box: Bounds | null = null;
  for (const ring of rings) {
    for (const [lon, lat] of ring) {
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      box = extend(box, lon, lat);
    }
  }
  return box;
}

export function boundsOfPolygon(polygon: Polygon | null | undefined): Bounds | null {
  if (!polygon || !Array.isArray(polygon.coordinates)) return null;
  return boundsOfRings(polygon.coordinates as [number, number][][]);
}

/**
 * A box that is not a point.
 *
 * A single cell, or a block drawn as one coordinate, gives a zero-width box,
 * and fitting to that zooms to the maximum. Padding it by a fraction of the
 * larger side keeps a one-cell area readable at a sane scale.
 */
export function padBounds(box: Bounds, fraction = 0.15): Bounds {
  const width = box.east - box.west;
  const height = box.north - box.south;
  const span = Math.max(width, height);
  // A degenerate box still has to occupy something. About ten metres.
  const pad = span > 0 ? span * fraction : 0.0001;
  return {
    west: box.west - pad,
    south: box.south - pad,
    east: box.east + pad,
    north: box.north + pad,
  };
}

/** Every block of the farm. */
export function farmBounds(polygons: (Polygon | null | undefined)[]): Bounds | null {
  let box: Bounds | null = null;
  for (const polygon of polygons) {
    const one = boundsOfPolygon(polygon);
    if (one === null) continue;
    box = box === null ? one : {
      west: Math.min(box.west, one.west),
      south: Math.min(box.south, one.south),
      east: Math.max(box.east, one.east),
      north: Math.max(box.north, one.north),
    };
  }
  return box;
}

/** The cells of one area. */
export function areaBounds(rings: [number, number][][]): Bounds | null {
  return boundsOfRings(rings);
}

/** What MapLibre's fitBounds takes: south-west then north-east. */
export function toLngLatBounds(box: Bounds): [[number, number], [number, number]] {
  return [
    [box.west, box.south],
    [box.east, box.north],
  ];
}
