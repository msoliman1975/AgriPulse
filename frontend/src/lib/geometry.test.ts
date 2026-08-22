import { describe, expect, it } from "vitest";
import {
  ensureValidMultiPolygon,
  ensureValidPolygon,
  GeometryValidationError,
  polygonToMultiPolygon,
} from "./geometry";
import type { Polygon } from "geojson";

const cairoSquare = (): Polygon => ({
  type: "Polygon",
  coordinates: [
    [
      [31.2, 30.0],
      [31.21, 30.0],
      [31.21, 30.01],
      [31.2, 30.01],
      [31.2, 30.0],
    ],
  ],
});

describe("ensureValidPolygon", () => {
  it("accepts a valid polygon", () => {
    expect(() => ensureValidPolygon(cairoSquare())).not.toThrow();
  });

  it("rejects a non-polygon", () => {
    expect(() => ensureValidPolygon({ type: "Point", coordinates: [31.2, 30.0] })).toThrow(
      GeometryValidationError,
    );
  });

  it("accepts a polygon outside Egypt", () => {
    const paris: Polygon = {
      type: "Polygon",
      coordinates: [
        [
          [2.3, 48.8],
          [2.31, 48.8],
          [2.31, 48.81],
          [2.3, 48.81],
          [2.3, 48.8],
        ],
      ],
    };
    // The metric coordinate system is per farm (`farms.utm_srid`), so a
    // boundary anywhere on Earth gets a correct area. There is no country box.
    expect(() => ensureValidPolygon(paris)).not.toThrow();
  });

  it("rejects a self-intersecting polygon", () => {
    const bowtie: Polygon = {
      type: "Polygon",
      coordinates: [
        [
          [31.2, 30.0],
          [31.21, 30.01],
          [31.21, 30.0],
          [31.2, 30.01],
          [31.2, 30.0],
        ],
      ],
    };
    try {
      ensureValidPolygon(bowtie);
      throw new Error("should have thrown");
    } catch (e) {
      expect((e as GeometryValidationError).code).toBe("self_intersect");
    }
  });
});

describe("ensureValidMultiPolygon", () => {
  it("upgrades a Polygon to MultiPolygon", () => {
    const mp = ensureValidMultiPolygon(cairoSquare());
    expect(mp.type).toBe("MultiPolygon");
    expect(mp.coordinates.length).toBe(1);
  });

  it("rejects empty multipolygons", () => {
    try {
      ensureValidMultiPolygon({ type: "MultiPolygon", coordinates: [] });
      throw new Error("should have thrown");
    } catch (e) {
      expect((e as GeometryValidationError).code).toBe("empty");
    }
  });
});

describe("polygonToMultiPolygon", () => {
  it("wraps coordinates", () => {
    const mp = polygonToMultiPolygon(cairoSquare());
    expect(mp.type).toBe("MultiPolygon");
    expect(mp.coordinates[0]).toEqual(cairoSquare().coordinates);
  });
});
