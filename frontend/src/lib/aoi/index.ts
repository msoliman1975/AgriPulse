import type { MultiPolygon, Polygon } from "geojson";
import type { PolygonalFeature } from "./parse";

export { parseAoiFile, pickPolygonalFeatures, AoiParseError, MAX_FILE_BYTES } from "./parse";
export type { PolygonalFeature, AoiParseResult, AoiSourceFormat } from "./parse";

/** Returns the first feature's geometry, or null when the list is empty. */
export function singleBoundary(features: PolygonalFeature[]): Polygon | MultiPolygon | null {
  if (features.length === 0) return null;
  return features[0].geometry;
}
