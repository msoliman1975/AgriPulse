import { describe, it, expect } from "vitest";
import type { Polygon } from "geojson";

import {
  approxPolygonAreaM2,
  formatArea,
  formatDistance,
  haversineMeters,
  polygonPerimeterM,
} from "./geo";

// ~111 km north-south arc-degree at the equator is the canonical unit-test
// distance. Everywhere else we compare against the spherical model the
// helpers themselves use, so the tolerances stay tight.
const KM = 1_000;

describe("haversineMeters", () => {
  it("returns 0 for identical points", () => {
    expect(haversineMeters([10, 20], [10, 20])).toBe(0);
  });

  it("matches the canonical equatorial degree (~111 km)", () => {
    const d = haversineMeters([0, 0], [0, 1]);
    expect(d).toBeGreaterThan(110 * KM);
    expect(d).toBeLessThan(112 * KM);
  });

  it("is symmetric", () => {
    const a: [number, number] = [31.0, 30.5];
    const b: [number, number] = [31.01, 30.51];
    expect(haversineMeters(a, b)).toBeCloseTo(haversineMeters(b, a), 6);
  });
});

describe("approxPolygonAreaM2", () => {
  it("returns 0 for degenerate rings", () => {
    const tri: Polygon = {
      type: "Polygon",
      coordinates: [
        [
          [0, 0],
          [0, 0],
        ],
      ],
    };
    expect(approxPolygonAreaM2(tri)).toBe(0);
  });

  it("computes a ~1 ha plot near Cairo at the right order of magnitude", () => {
    // ~100 m × 100 m square at lat 30.5, lon 31.0 (≈ 1 hectare).
    // 100 m at lat 30.5 = ~0.000898° lat = ~0.00104° lon (cos(30.5°) ≈ 0.862).
    const dLat = 0.000898;
    const dLon = 0.00104;
    const sq: Polygon = {
      type: "Polygon",
      coordinates: [
        [
          [31.0, 30.5],
          [31.0 + dLon, 30.5],
          [31.0 + dLon, 30.5 + dLat],
          [31.0, 30.5 + dLat],
          [31.0, 30.5],
        ],
      ],
    };
    const area = approxPolygonAreaM2(sq);
    expect(area).toBeGreaterThan(9_500);
    expect(area).toBeLessThan(10_500);
  });
});

describe("polygonPerimeterM", () => {
  it("returns 0 for under-2-vertex rings", () => {
    expect(polygonPerimeterM({ type: "Polygon", coordinates: [[]] })).toBe(0);
    expect(polygonPerimeterM({ type: "Polygon", coordinates: [[[0, 0]]] })).toBe(0);
  });

  it("sums consecutive edges for an open in-progress polyline", () => {
    // Two ~111 km segments → ~222 km perimeter.
    const open: Polygon = {
      type: "Polygon",
      coordinates: [
        [
          [0, 0],
          [0, 1],
          [1, 1],
        ],
      ],
    };
    const p = polygonPerimeterM(open);
    expect(p).toBeGreaterThan(220 * KM);
    expect(p).toBeLessThan(225 * KM);
  });

  it("includes the closing edge for a closed ring (first == last)", () => {
    // Closed triangle. Open form would report 2 edges; closed form reports 3.
    const closed: Polygon = {
      type: "Polygon",
      coordinates: [
        [
          [0, 0],
          [0, 1],
          [1, 1],
          [0, 0],
        ],
      ],
    };
    const p = polygonPerimeterM(closed);
    // Two ~111 km edges + closing hypotenuse ≈ 157 km → ~378 km.
    expect(p).toBeGreaterThan(370 * KM);
    expect(p).toBeLessThan(385 * KM);
  });
});

describe("formatArea", () => {
  it.each([
    [0, "—"],
    [-5, "—"],
    [NaN, "—"],
    [120, "120 m²"],
    [9_999, "9999 m²"],
    [10_000, "1.00 ha"],
    [12_345, "1.23 ha"],
    [1_000_000, "100.00 ha"],
  ])("formats %s as %s", (m2, expected) => {
    expect(formatArea(m2)).toBe(expected);
  });
});

describe("formatDistance", () => {
  it.each([
    [0, "—"],
    [-1, "—"],
    [NaN, "—"],
    [42, "42 m"],
    [999, "999 m"],
    [1_000, "1.00 km"],
    [12_345, "12.35 km"],
  ])("formats %s as %s", (m, expected) => {
    expect(formatDistance(m)).toBe(expected);
  });
});
