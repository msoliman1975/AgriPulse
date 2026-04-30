import type { Feature, FeatureCollection } from "geojson";
import { AoiParseError } from "./parse";

export function parseGeoJsonText(text: string): Promise<FeatureCollection> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    throw new AoiParseError("invalid_content", (err as Error).message);
  }
  return Promise.resolve(normalize(parsed));
}

export function normalize(value: unknown): FeatureCollection {
  if (!value || typeof value !== "object") {
    throw new AoiParseError("invalid_content");
  }
  const obj = value as { type?: string };
  if (obj.type === "FeatureCollection") {
    return value as FeatureCollection;
  }
  if (obj.type === "Feature") {
    return { type: "FeatureCollection", features: [value as Feature] };
  }
  if (
    obj.type === "Polygon" ||
    obj.type === "MultiPolygon" ||
    obj.type === "Point" ||
    obj.type === "LineString"
  ) {
    return {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: value as Feature["geometry"],
        },
      ],
    };
  }
  throw new AoiParseError("invalid_content", `unknown type: ${obj.type}`);
}
