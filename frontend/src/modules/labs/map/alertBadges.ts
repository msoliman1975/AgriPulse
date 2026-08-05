// Anchor points for the map's alert badges.
//
// The badge layer is a maplibre `circle`, and a circle layer draws one
// circle per coordinate of whatever geometry it is bound to. Bound to the
// polygon `units` source it therefore painted a badge on EVERY VERTEX of
// every alerting block — a ring of red dots around the corners instead of
// one badge per block. (The `units-label` layer sitting next to it never
// had the problem because `symbol` layers collapse a polygon to a single
// anchor.)
//
// So the badges get their own point source, derived here.

import { pointOnFeature } from "@turf/turf";
import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

import type { UnitFeatureProps } from "./types";

/**
 * One badge anchor per alerting block.
 *
 * Uses `pointOnFeature` rather than a centroid: a centroid can land
 * outside a concave block — an L-shaped field, a pivot sector — which
 * would float the badge over a neighbouring block and point the operator
 * at the wrong place. `pointOnFeature` is guaranteed to sit on the
 * feature.
 *
 * Non-alerting blocks are dropped rather than carried and filtered in the
 * style, so the common case (nothing wrong on the farm) ships an empty
 * collection.
 */
export function buildAlertBadgePoints(
  units: FeatureCollection<Polygon, UnitFeatureProps>,
): FeatureCollection<Point, UnitFeatureProps> {
  const features: Feature<Point, UnitFeatureProps>[] = [];
  for (const f of units.features) {
    if (!f.properties.has_alert) continue;
    features.push({
      type: "Feature",
      id: f.id,
      geometry: pointOnFeature(f).geometry,
      properties: f.properties,
    });
  }
  return { type: "FeatureCollection", features };
}
