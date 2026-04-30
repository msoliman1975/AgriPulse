import { describe, expect, it } from "vitest";
import {
  ensureValidMultiPolygon,
  ensureValidPolygon,
  GeometryValidationError,
  isInEgyptBbox,
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
  it("accepts a valid Egyptian polygon", () => {
    expect(() => ensureValidPolygon(cairoSquare())).not.toThrow();
  });

  it("rejects a non-polygon", () => {
    expect(() => ensureValidPolygon({ type: "Point", coordinates: [31.2, 30.0] })).toThrow(
      GeometryValidationError,
    );
  });

  it("rejects out-of-Egypt coordinates", () => {
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
    try {
      ensureValidPolygon(paris);
      throw new Error("should have thrown");
    } catch (e) {
      expect((e as GeometryValidationError).code).toBe("out_of_egypt");
    }
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

describe("isInEgyptBbox", () => {
  it("true for Cairo polygon", () => {
    expect(isInEgyptBbox(cairoSquare())).toBe(true);
  });
  it("false for Paris polygon", () => {
    expect(
      isInEgyptBbox({
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
      }),
    ).toBe(false);
  });
});

describe("polygonToMultiPolygon", () => {
  it("wraps coordinates", () => {
    const mp = polygonToMultiPolygon(cairoSquare());
    expect(mp.type).toBe("MultiPolygon");
    expect(mp.coordinates[0]).toEqual(cairoSquare().coordinates);
  });
});
