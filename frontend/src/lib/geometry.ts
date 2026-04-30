import type {
  Feature,
  FeatureCollection,
  Geometry,
  MultiPolygon,
  Polygon,
  Position,
} from "geojson";
import { area, bbox, booleanValid, kinks } from "@turf/turf";

// Egypt sanity bbox per prompt-02. Server enforces too.
export const EGYPT_BBOX = { minLon: 24, minLat: 22, maxLon: 36, maxLat: 32 } as const;

export type ParsedGeoJson = FeatureCollection | Feature | Geometry;

export interface GeometryError {
  code:
    | "not_polygon"
    | "not_multipolygon"
    | "self_intersect"
    | "invalid"
    | "out_of_egypt"
    | "empty";
  detail?: string;
}

export class GeometryValidationError extends Error {
  public readonly code: GeometryError["code"];
  public readonly detail?: string;
  constructor(error: GeometryError) {
    super(error.detail ?? error.code);
    this.code = error.code;
    this.detail = error.detail;
  }
}

function flatten(value: ParsedGeoJson): Feature[] {
  if (value.type === "FeatureCollection") return value.features;
  if (value.type === "Feature") return [value];
  return [{ type: "Feature", properties: {}, geometry: value }];
}

export function asFeatures(value: ParsedGeoJson): Feature[] {
  return flatten(value);
}

export function bboxOfGeometry(geometry: Geometry): [number, number, number, number] {
  return bbox({ type: "Feature", properties: {}, geometry }) as [number, number, number, number];
}

export function isInEgyptBbox(geometry: Geometry): boolean {
  const [minLon, minLat, maxLon, maxLat] = bboxOfGeometry(geometry);
  return (
    minLon >= EGYPT_BBOX.minLon &&
    maxLon <= EGYPT_BBOX.maxLon &&
    minLat >= EGYPT_BBOX.minLat &&
    maxLat <= EGYPT_BBOX.maxLat
  );
}

export function geometryAreaM2(geometry: Polygon | MultiPolygon): number {
  return area({ type: "Feature", properties: {}, geometry });
}

export function ensureValidPolygon(geometry: Geometry): Polygon {
  if (geometry.type !== "Polygon") {
    throw new GeometryValidationError({
      code: "not_polygon",
      detail: `expected Polygon, got ${geometry.type}`,
    });
  }
  if (!hasRing(geometry.coordinates)) {
    throw new GeometryValidationError({ code: "empty" });
  }
  if (
    kinks({ type: "Feature", properties: {}, geometry }).features.length > 0 ||
    !booleanValid(geometry)
  ) {
    throw new GeometryValidationError({ code: "self_intersect" });
  }
  if (!isInEgyptBbox(geometry)) {
    throw new GeometryValidationError({ code: "out_of_egypt" });
  }
  return geometry;
}

export function ensureValidMultiPolygon(geometry: Geometry): MultiPolygon {
  if (geometry.type === "Polygon") {
    geometry = polygonToMultiPolygon(geometry);
  }
  if (geometry.type !== "MultiPolygon") {
    throw new GeometryValidationError({
      code: "not_multipolygon",
      detail: `expected MultiPolygon or Polygon, got ${geometry.type}`,
    });
  }
  if (geometry.coordinates.length === 0) {
    throw new GeometryValidationError({ code: "empty" });
  }
  for (const poly of geometry.coordinates) {
    if (!hasRing(poly)) {
      throw new GeometryValidationError({ code: "empty" });
    }
  }
  if (!booleanValid(geometry)) {
    throw new GeometryValidationError({ code: "self_intersect" });
  }
  if (!isInEgyptBbox(geometry)) {
    throw new GeometryValidationError({ code: "out_of_egypt" });
  }
  return geometry;
}

export function polygonToMultiPolygon(p: Polygon): MultiPolygon {
  return { type: "MultiPolygon", coordinates: [p.coordinates] };
}

function hasRing(coords: Position[][] | Position[][][]): boolean {
  if (coords.length === 0) return false;
  const first = coords[0];
  if (first.length > 0 && typeof first[0][0] === "number") {
    return (first as Position[]).length >= 4;
  }
  return (first as Position[][]).every((r) => r.length >= 4);
}

export function centerOfBbox(geometry: Geometry): [number, number] {
  const [minLon, minLat, maxLon, maxLat] = bboxOfGeometry(geometry);
  return [(minLon + maxLon) / 2, (minLat + maxLat) / 2];
}
