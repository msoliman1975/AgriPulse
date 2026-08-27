import { describe, expect, it } from "vitest";
import type { MultiPolygon } from "geojson";

import { boundsOfMultiPolygon, padBounds, unionBounds, type SourceBounds } from "./mapBounds";

const AOI: MultiPolygon = {
  type: "MultiPolygon",
  coordinates: [
    [
      [
        [31.6, 30.6],
        [31.7, 30.6],
        [31.7, 30.7],
        [31.6, 30.7],
        [31.6, 30.6],
      ],
    ],
  ],
};

describe("boundsOfMultiPolygon", () => {
  it("returns a FLAT [west, south, east, north]", () => {
    // Flat, not the nested pair `fitBounds` takes. Swapping the two is
    // silent and puts the box on the equator.
    expect(boundsOfMultiPolygon(AOI)).toEqual([31.6, 30.6, 31.7, 30.7]);
  });

  it("is undefined for a farm with no stored boundary", () => {
    expect(boundsOfMultiPolygon(null)).toBeUndefined();
    expect(boundsOfMultiPolygon(undefined)).toBeUndefined();
  });

  it("covers every polygon of a multi-part farm", () => {
    const split: MultiPolygon = {
      type: "MultiPolygon",
      coordinates: [
        AOI.coordinates[0],
        [
          [
            [31.9, 30.9],
            [32.0, 30.9],
            [32.0, 31.0],
            [31.9, 31.0],
            [31.9, 30.9],
          ],
        ],
      ],
    };
    expect(boundsOfMultiPolygon(split)).toEqual([31.6, 30.6, 32.0, 31.0]);
  });
});

describe("unionBounds", () => {
  it("keeps whichever side exists when the other does not", () => {
    const a: SourceBounds = [1, 2, 3, 4];
    expect(unionBounds(a, undefined)).toEqual(a);
    expect(unionBounds(undefined, a)).toEqual(a);
    expect(unionBounds(undefined, undefined)).toBeUndefined();
  });

  it("widens to hold a block drawn outside the stored AOI", () => {
    // The case this exists for: the boundary and the blocks disagree, and
    // a block outside the AOI must not fall outside the request box.
    const aoi: SourceBounds = [31.6, 30.6, 31.7, 30.7];
    const strayBlock: SourceBounds = [31.55, 30.58, 31.62, 30.65];
    expect(unionBounds(aoi, strayBlock)).toEqual([31.55, 30.58, 31.7, 30.7]);
  });
});

describe("padBounds", () => {
  it("only ever widens", () => {
    // The whole safety property. `bounds` suppresses tile REQUESTS, so a
    // box that is too small does not save traffic, it drops the edge of
    // the image. Every step of this pipeline must grow the box.
    const box: SourceBounds = [31.6, 30.6, 31.7, 30.7];
    const padded = padBounds(box)!;
    expect(padded[0]).toBeLessThan(box[0]);
    expect(padded[1]).toBeLessThan(box[1]);
    expect(padded[2]).toBeGreaterThan(box[2]);
    expect(padded[3]).toBeGreaterThan(box[3]);
  });

  it("pads far beyond the raster's own pixel overhang", () => {
    // A COG keeps whole any pixel whose centre is inside the AOI, so
    // colour runs ~5 m past the boundary (15 m on the 30 m thermal
    // product). The pad must dwarf that or it would clip real pixels.
    const padded = padBounds([31.6, 30.6, 31.7, 30.7])!;
    const padDegrees = 31.6 - padded[0];
    const padMetres = padDegrees * 111_320;
    expect(padMetres).toBeGreaterThan(50);
  });

  it("is undefined in, undefined out, so a farm with no geometry omits the key", () => {
    // Never `bounds: undefined` — MapLibre validates the KEY and throws.
    // The caller spreads this, so undefined must stay undefined.
    expect(padBounds(undefined)).toBeUndefined();
  });
});
