import type { Feature, FeatureCollection, Geometry } from "geojson";
import { kml as kmlToGeoJson } from "@tmcw/togeojson";
import { DOMParser } from "@xmldom/xmldom";
import { AoiParseError } from "./parse";

export function parseKml(text: string): Promise<FeatureCollection> {
  // @xmldom/xmldom's Document is structurally close enough for togeojson's
  // input shape; the unknown bridge works around the nominal mismatch.
  let doc: unknown;
  try {
    doc = new DOMParser().parseFromString(text, "text/xml");
  } catch (err) {
    throw new AoiParseError("invalid_content", (err as Error).message);
  }
  try {
    const fc = kmlToGeoJson(doc as Document);
    const features = fc.features.filter((f): f is Feature<Geometry> => f.geometry !== null);
    return Promise.resolve({ type: "FeatureCollection", features });
  } catch (err) {
    throw new AoiParseError("invalid_content", (err as Error).message);
  }
}
