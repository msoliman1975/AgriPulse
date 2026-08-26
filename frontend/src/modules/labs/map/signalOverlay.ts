import type { Feature, FeatureCollection, Point } from "geojson";

import type { Geopoint, LocationMode, SignalObservation, ValueKind } from "@/api/signals";
import type { UnitFeatureProps } from "./types";

// CS-8: turn signal observations into a Point FeatureCollection for
// MapLibre. Observations carry their coordinate one of three ways
// (CS-1 / CS-5) — we pick whichever is most precise that's present,
// in this order:
//
//   1. location_point        (operator picked an exact spot — CS-1 D2
//                             point_in_entity / free_point)
//   2. value_geopoint        (the observed value IS a geopoint —
//                             e.g. a wildlife sighting, an old design
//                             where geopoint doubled as location)
//   3. block centroid        (operator said "this block" — entity mode;
//                             fallback so block-scoped observations still
//                             render as a single marker on the block)
//
// Observations with no resolvable coordinate (entity mode + missing
// block, or unknown block id) are silently dropped — the picker UI
// surfaces the count via skippedCount so the operator can tell.

export interface SignalOverlayProps {
  observation_id: string;
  signal_code: string;
  value_kind: ValueKind | null;
  value_display: string;
  observed_at: string;
  location_mode: LocationMode;
  block_id: string | null;
  source: "location_point" | "value_geopoint" | "block_centroid";
  /**
   * How many observations resolved to THIS coordinate, this one included.
   *
   * Entity-mode observations have no coordinate of their own, so every one
   * recorded against a block lands on that block's centroid — 145
   * observations across 36 blocks on Bashier Elkhier, all stacked four deep.
   * MapLibre can place exactly one symbol per point, so the other three were
   * silently dropped and unreachable: invisible, and not returned by
   * `queryRenderedFeatures` either, which is what "the icons stopped being
   * clickable" turned out to mean.
   *
   * One feature per coordinate, carrying the count, is the honest shape. The
   * map says how many readings are here and the panel walks them.
   */
  stack_count: number;
  /**
   * Every observation id at this coordinate, newest first, as a JSON array
   * string. MapLibre flattens feature properties through its worker, so an
   * array does not survive the round trip — it arrives as "[object Object]".
   * Serialised here and parsed by the click handler's consumer.
   */
  stack_ids: string;
}

export interface BuildOverlayResult {
  features: FeatureCollection<Point, SignalOverlayProps>;
  skippedCount: number;
}

/**
 * Convert an array of observations + the known block centroids into a
 * GeoJSON FeatureCollection MapCanvas can drop into a source.
 *
 * `blockCentroids` is `{block_id → [lon, lat]}`. The map page already
 * has block geometries in its summary projection; the caller is
 * responsible for computing the centroid (small + already cached) and
 * passing it in.
 */
export function buildSignalOverlay(
  observations: readonly SignalObservation[],
  blockCentroids: ReadonlyMap<string, [number, number]>,
  options: {
    /** Value kind per signal definition id.
     *
     * A map rather than one kind for the whole call, because the overlay now
     * carries every signal type at once and a single kind would label a
     * categorical observation as numeric. Falls back to `valueKind` for the
     * one-definition callers that predate that. */
    valueKindByDefinitionId?: ReadonlyMap<string, ValueKind>;
    valueKind?: ValueKind | null;
  } = {},
): BuildOverlayResult {
  let skippedCount = 0;

  // Coordinate -> the observations sitting on it, in the order they arrived.
  // Keyed on the coordinate rounded to ~1 cm: two entity-mode observations on
  // one block produce bit-identical centroids, but a float key that depends on
  // exact equality is the kind that works until it does not.
  const stacks = new Map<
    string,
    { coord: [number, number]; placed: PlacedCoord; rows: SignalObservation[] }
  >();

  for (const obs of observations) {
    const placed = _resolveCoord(obs, blockCentroids);
    if (placed === null) {
      skippedCount += 1;
      continue;
    }
    const key = `${placed.coord[0].toFixed(7)},${placed.coord[1].toFixed(7)}`;
    const bucket = stacks.get(key);
    if (bucket) bucket.rows.push(obs);
    else stacks.set(key, { coord: placed.coord, placed, rows: [obs] });
  }

  const features: Feature<Point, SignalOverlayProps>[] = [];
  for (const { coord, placed, rows } of stacks.values()) {
    // Newest first: the mark opens the most recent reading, which is the one
    // an operator asking "what did the scout find here" means.
    const ordered = [...rows].sort((a, b) => (a.time < b.time ? 1 : a.time > b.time ? -1 : 0));
    const top = ordered[0];
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [coord[0], coord[1]] },
      properties: {
        observation_id: top.id,
        signal_code: top.signal_code,
        value_kind:
          options.valueKindByDefinitionId?.get(top.signal_definition_id) ??
          options.valueKind ??
          null,
        value_display: formatObservationValue(top),
        observed_at: top.time,
        location_mode: top.location_mode ?? "entity",
        block_id: top.block_id,
        source: placed.source,
        stack_count: ordered.length,
        stack_ids: JSON.stringify(ordered.map((o) => o.id)),
      },
    });
  }

  return {
    features: { type: "FeatureCollection", features },
    skippedCount,
  };
}

/**
 * Pull the first non-null typed value off the observation and render
 * it short enough for a popup line. Numbers keep their string-typed
 * Decimal serialisation; booleans render as Yes/No (English only —
 * the popup is locale-aware via i18n in the UI layer).
 */
export function formatObservationValue(obs: SignalObservation): string {
  if (obs.value_numeric !== null && obs.value_numeric !== undefined) {
    return obs.value_numeric;
  }
  if (obs.value_categorical) return obs.value_categorical;
  if (obs.value_event) return obs.value_event;
  if (obs.value_boolean !== null && obs.value_boolean !== undefined) {
    return obs.value_boolean ? "Yes" : "No";
  }
  if (obs.value_geopoint) {
    const { latitude: lat, longitude: lon } = obs.value_geopoint;
    return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  }
  return "—";
}

/**
 * Helper for callers that already have the full unit GeoJSON the map
 * page passes to MapCanvas. Computes the centroid of each polygon
 * via the simple-average-of-vertices approximation. Good enough for a
 * marker placement — a block-scale polygon's true centroid is within
 * a few metres of the vertex average. Logical pivot rings get the
 * arithmetic centre of their bounding box (close enough).
 */
export function blockCentroidsFromGeojson(
  fc: FeatureCollection<GeoJSON.Polygon, UnitFeatureProps>,
): Map<string, [number, number]> {
  const out = new Map<string, [number, number]>();
  for (const feature of fc.features) {
    const id = feature.properties.id;
    if (!id) continue;
    const ring = feature.geometry.coordinates[0];
    if (!ring || ring.length === 0) continue;
    let sumLon = 0;
    let sumLat = 0;
    let n = 0;
    // Skip the closing duplicate vertex if present.
    const end =
      ring.length > 2 &&
      ring[0][0] === ring[ring.length - 1][0] &&
      ring[0][1] === ring[ring.length - 1][1]
        ? ring.length - 1
        : ring.length;
    for (let i = 0; i < end; i++) {
      sumLon += ring[i][0];
      sumLat += ring[i][1];
      n += 1;
    }
    if (n > 0) out.set(id, [sumLon / n, sumLat / n]);
  }
  return out;
}

interface PlacedCoord {
  coord: [number, number];
  source: SignalOverlayProps["source"];
}

function _resolveCoord(
  obs: SignalObservation,
  blockCentroids: ReadonlyMap<string, [number, number]>,
): PlacedCoord | null {
  if (obs.location_point && _isFiniteGeopoint(obs.location_point)) {
    return {
      coord: [obs.location_point.longitude, obs.location_point.latitude],
      source: "location_point",
    };
  }
  if (obs.value_geopoint && _isFiniteGeopoint(obs.value_geopoint)) {
    return {
      coord: [obs.value_geopoint.longitude, obs.value_geopoint.latitude],
      source: "value_geopoint",
    };
  }
  if (obs.block_id) {
    const centroid = blockCentroids.get(obs.block_id);
    if (centroid) return { coord: centroid, source: "block_centroid" };
  }
  return null;
}

function _isFiniteGeopoint(g: Geopoint): boolean {
  return (
    Number.isFinite(g.longitude) &&
    Number.isFinite(g.latitude) &&
    Math.abs(g.longitude) <= 180 &&
    Math.abs(g.latitude) <= 90
  );
}
