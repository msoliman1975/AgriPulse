import { describe, expect, it } from "vitest";

import type { Polygon } from "geojson";
import {
  areaBounds,
  boundsOfPolygon,
  farmBounds,
  padBounds,
  toLngLatBounds,
} from "./fit";

function square(west: number, south: number, size = 0.01): Polygon {
  return {
    type: "Polygon",
    coordinates: [
      [
        [west, south],
        [west + size, south],
        [west + size, south + size],
        [west, south + size],
        [west, south],
      ],
    ],
  };
}

describe("boundsOfPolygon", () => {
  it("covers the polygon", () => {
    expect(boundsOfPolygon(square(31, 30))).toEqual({
      west: 31,
      south: 30,
      east: 31.01,
      north: 30.01,
    });
  });

  it("is null for a block with no polygon", () => {
    expect(boundsOfPolygon(null)).toBeNull();
    expect(boundsOfPolygon(undefined)).toBeNull();
  });
});

describe("farmBounds", () => {
  it("covers every block", () => {
    const box = farmBounds([square(31, 30), square(31.5, 30.5)]);
    expect(box).toEqual({ west: 31, south: 30, east: 31.51, north: 30.51 });
  });

  it("ignores the blocks that have no polygon", () => {
    // A farm mid-import can hold a block without a boundary. Letting one
    // through as zeroes would frame the map on the Gulf of Guinea.
    const box = farmBounds([square(31, 30), null, undefined]);
    expect(box).toEqual({ west: 31, south: 30, east: 31.01, north: 30.01 });
  });

  it("is null when no block has a polygon", () => {
    expect(farmBounds([null, undefined])).toBeNull();
  });
});

describe("padBounds", () => {
  it("leaves room around what it frames", () => {
    const box = padBounds({ west: 0, south: 0, east: 1, north: 1 }, 0.1);
    expect(box).toEqual({ west: -0.1, south: -0.1, east: 1.1, north: 1.1 });
  });

  it("gives a single point something to occupy", () => {
    // One cell is a zero-width box, and fitting to that zooms to the
    // maximum, which reads as the map breaking.
    const box = padBounds({ west: 31, south: 30, east: 31, north: 30 });
    expect(box.east).toBeGreaterThan(box.west);
    expect(box.north).toBeGreaterThan(box.south);
  });
});

describe("areaBounds", () => {
  it("covers only the cells given", () => {
    const cells: [number, number][][] = [
      [
        [31, 30],
        [31.001, 30],
        [31.001, 30.001],
        [31, 30.001],
      ],
      [
        [31.002, 30],
        [31.003, 30],
        [31.003, 30.001],
        [31.002, 30.001],
      ],
    ];

    expect(areaBounds(cells)).toEqual({
      west: 31,
      south: 30,
      east: 31.003,
      north: 30.001,
    });
  });

  it("is null for an area with no cells", () => {
    expect(areaBounds([])).toBeNull();
  });
});

describe("toLngLatBounds", () => {
  it("puts the south-west corner first, which is what fitBounds reads", () => {
    // The other order mirrors the map and is not an error anywhere.
    expect(toLngLatBounds({ west: 1, south: 2, east: 3, north: 4 })).toEqual([
      [1, 2],
      [3, 4],
    ]);
  });
});
