import type { FeatureCollection } from "geojson";
import shp from "shpjs";
import { AoiParseError } from "./parse";

export async function parseShapefile(buffer: ArrayBuffer): Promise<FeatureCollection> {
  let parsed: unknown;
  try {
    parsed = await shp(buffer);
  } catch (err) {
    throw new AoiParseError("invalid_content", (err as Error).message);
  }
  if (Array.isArray(parsed)) {
    // Multi-layer .zip — flatten into one collection.
    const features = (parsed as FeatureCollection[]).flatMap((c) => c.features ?? []);
    return { type: "FeatureCollection", features };
  }
  return parsed as FeatureCollection;
}
