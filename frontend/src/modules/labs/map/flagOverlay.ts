// Field flags as map points.
//
// A flag always draws. When the scout captured a position the pin sits where
// they stood; when they did not, it sits at the block's centroid — the same
// fallback the signal overlay uses, and for the same reason: a finding with no
// coordinate is still a finding, and dropping it from the map would make the
// map disagree with the panel.

import type { Feature, FeatureCollection, Point } from "geojson";

import type { FieldFlag } from "@/api/fieldFlags";

export interface FlagOverlayProps {
  flag_id: string;
  severity: string;
  /** Drives fill vs hollow. Closed pins stay on the map for the rest of their
   *  lifetime, so the layer has to say which ones are finished. */
  open: boolean;
  title: string;
  /** Where the coordinate came from, so a reader can tell a GPS fix from a
   *  block-centre approximation rather than trusting a pin that is neither. */
  source: "point" | "block_centroid";
}

export function buildFlagOverlay(
  flags: FieldFlag[],
  blockCentroids: Map<string, [number, number]>,
): FeatureCollection<Point, FlagOverlayProps> {
  const features: Feature<Point, FlagOverlayProps>[] = [];
  for (const f of flags) {
    let coord: [number, number] | undefined;
    let source: FlagOverlayProps["source"] = "point";
    if (f.point && Array.isArray(f.point.coordinates)) {
      const [lon, lat] = f.point.coordinates;
      if (Number.isFinite(lon) && Number.isFinite(lat)) coord = [lon, lat];
    }
    if (!coord) {
      const centroid = blockCentroids.get(f.block_id);
      if (centroid) {
        coord = centroid;
        source = "block_centroid";
      }
    }
    // No position and no centroid: nothing truthful to draw. The panel still
    // lists it, so the flag is not lost — it is only absent from the map.
    if (!coord) continue;
    features.push({
      type: "Feature",
      id: f.id,
      geometry: { type: "Point", coordinates: coord },
      properties: {
        flag_id: f.id,
        severity: f.severity,
        open: f.status === "open",
        title: f.note.split("\n")[0].slice(0, 120),
        source,
      },
    });
  }
  return { type: "FeatureCollection", features };
}
