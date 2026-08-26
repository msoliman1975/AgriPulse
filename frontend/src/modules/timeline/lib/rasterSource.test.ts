// Regression tests for the bug that shipped: a whole-farm raster drew no
// pixels at all on prod, and 46 green tests said nothing, because they all
// stub the map and the spec was built inline inside an effect.
//
// These assert the SHAPE handed to MapLibre. That is the layer the defect
// lived in — asserting the props the component received, which is what the
// page test does, cannot see it.

import { describe, expect, it } from "vitest";

import { rasterSourceSpec } from "./rasterSource";

const BOUNDS: [number, number, number, number] = [31.6, 30.6, 31.61, 30.61];

describe("rasterSourceSpec", () => {
  it("OMITS the bounds key entirely for a whole-farm raster", () => {
    // Not "bounds is undefined" — the key must not be present. MapLibre
    // validates presence, so `{bounds: undefined}` fails with "array
    // expected, undefined found" and addSource throws.
    const spec = rasterSourceSpec({ tileUrl: "https://t/{z}/{x}/{y}.png", tileSize: 512 });
    expect("bounds" in spec).toBe(false);
    expect(Object.keys(spec)).not.toContain("bounds");
  });

  it("keeps bounds for a per-block raster", () => {
    const spec = rasterSourceSpec({
      tileUrl: "https://t/{z}/{x}/{y}.png",
      bounds: BOUNDS,
      tileSize: 512,
    });
    expect(spec.bounds).toEqual(BOUNDS);
  });

  it("survives a JSON round-trip with the key still absent", () => {
    // The guard that would have caught the original: `{bounds: undefined}`
    // and `{}` are indistinguishable after JSON.stringify, so a test that
    // compared serialised output would have passed on the broken version.
    // `in` is the check that actually discriminates.
    const broken = { type: "raster", bounds: undefined };
    const fixed = rasterSourceSpec({ tileUrl: "https://t/{z}/{x}/{y}.png", tileSize: 512 });
    expect(JSON.stringify(broken)).toBe(JSON.stringify({ type: "raster" }));
    expect("bounds" in broken).toBe(true);
    expect("bounds" in fixed).toBe(false);
  });

  it("leaves the z/x/y placeholders intact for MapLibre to interpolate", () => {
    const spec = rasterSourceSpec({ tileUrl: "https://t/{z}/{x}/{y}.png?a=1", tileSize: 512 });
    expect(spec.tiles?.[0]).toContain("{z}/{x}/{y}");
  });

  it("passes the tile size through, because 256 would stretch the image", () => {
    expect(rasterSourceSpec({ tileUrl: "u", tileSize: 512 }).tileSize).toBe(512);
  });
});
