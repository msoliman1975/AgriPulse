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
//
// The badge is now a symbol, not a circle — see markerIcons.ts for why the
// three overlays needed three shapes — so this also resolves each block's
// marker image and count label. Resolving them HERE rather than in a
// MapLibre `match` expression keeps the image ids in one place: an id the
// layer asks for but the registration loop never created renders as nothing
// at all, with no error, which would drop the alert off the map silently.

import { pointOnFeature } from "@turf/turf";
import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

import { alertActionGlyph, alertChipImageId, markerSeverity } from "./markerIcons";
import type { UnitFeatureProps } from "./types";

/** What the symbol layer reads off each badge feature. */
export interface AlertBadgeProps extends UnitFeatureProps {
  /** Registered marker image id — glyph from the verb, colour from severity. */
  marker_icon: string;
  /** The count, pre-rendered. MapLibre can `to-string` a number itself, but
   *  a block carrying more than 99 open alerts would make the chip wider than
   *  the block, so the cap happens here where it can be explained. */
  marker_count: string;
}

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
): FeatureCollection<Point, AlertBadgeProps> {
  const features: Feature<Point, AlertBadgeProps>[] = [];
  for (const f of units.features) {
    if (!f.properties.has_alert) continue;
    const count = f.properties.alert_count;
    features.push({
      type: "Feature",
      id: f.id,
      geometry: pointOnFeature(f).geometry,
      properties: {
        ...f.properties,
        marker_icon: alertChipImageId(
          alertActionGlyph(f.properties.alert_action_type),
          markerSeverity(f.properties.alert_severity),
        ),
        // `has_alert` is derived from a count > 0, so a badge with a count of
        // 0 cannot occur; guard anyway rather than print "0" on the map.
        marker_count: count > 99 ? "99+" : String(Math.max(count, 1)),
      },
    });
  }
  return { type: "FeatureCollection", features };
}
