import type { Feature, FeatureCollection, Polygon, MultiPolygon } from "geojson";
import { parseGeoJsonText } from "./geojson";
import { parseShapefile } from "./shapefile";
import { parseKml } from "./kml";

export const MAX_FILE_BYTES = 10 * 1024 * 1024;

export type AoiSourceFormat = "geojson" | "shapefile" | "kml";

export interface AoiParseResult {
  format: AoiSourceFormat;
  collection: FeatureCollection;
}

export class AoiParseError extends Error {
  public readonly code: "too_large" | "unsupported_extension" | "invalid_content" | "empty";
  constructor(code: AoiParseError["code"], message?: string) {
    super(message ?? code);
    this.code = code;
  }
}

function detectFormat(file: File): AoiSourceFormat {
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".zip") || file.type === "application/zip") return "shapefile";
  if (lower.endsWith(".kml") || file.type === "application/vnd.google-earth.kml+xml") {
    return "kml";
  }
  if (
    lower.endsWith(".geojson") ||
    lower.endsWith(".json") ||
    file.type === "application/geo+json" ||
    file.type === "application/json"
  ) {
    return "geojson";
  }
  throw new AoiParseError("unsupported_extension", file.name);
}

export async function parseAoiFile(file: File): Promise<AoiParseResult> {
  if (file.size > MAX_FILE_BYTES) {
    throw new AoiParseError("too_large", `${file.size} bytes`);
  }
  const format = detectFormat(file);
  let collection: FeatureCollection;
  if (format === "geojson") {
    collection = await parseGeoJsonText(await file.text());
  } else if (format === "shapefile") {
    collection = await parseShapefile(await file.arrayBuffer());
  } else {
    collection = await parseKml(await file.text());
  }
  if (collection.features.length === 0) {
    throw new AoiParseError("empty");
  }
  return { format, collection };
}

export type PolygonalFeature = Feature<Polygon | MultiPolygon>;

export function pickPolygonalFeatures(collection: FeatureCollection): PolygonalFeature[] {
  return collection.features.filter(
    (f: Feature): f is PolygonalFeature =>
      f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon",
  );
}
