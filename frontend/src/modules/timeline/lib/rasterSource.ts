// The MapLibre source spec for one index raster.
//
// This is a pure function ONLY so it can be tested. The bug it exists to
// pin was invisible to every test in this module, because they all stub
// the map: the spec was built inline inside an effect, handed straight to
// `map.addSource`, and nothing between the two could be asserted on.
//
// What it got wrong is worth stating exactly, because it is not obvious
// from the MapLibre docs. `addSource` validates the PRESENCE of `bounds`,
// not its value. An explicit `bounds: undefined` is therefore not the same
// as omitting the key — it fails validation with "array expected,
// undefined found", `addSource` throws, and the `addLayer` that follows
// then fails with "source not found". Both errors go to the console and
// neither reaches React, so the map keeps rendering its satellite base,
// its block outlines and its marks, and simply never draws a pixel.
//
// A whole-farm raster has no per-block extent, so `bounds` is undefined on
// exactly the farms that draw one surface instead of 36 — which is every
// farm cut over to farm-AOI fetching. On those, the feature's whole point
// silently did not work.

import type { RasterSourceSpecification } from "maplibre-gl";

export interface RasterInput {
  tileUrl: string;
  /** `[west, south, east, north]`, or undefined for a whole-farm raster. */
  bounds?: [number, number, number, number];
  tileSize: number;
}

export function rasterSourceSpec(input: RasterInput): RasterSourceSpecification {
  return {
    type: "raster",
    tiles: [input.tileUrl],
    tileSize: input.tileSize,
    // Spread, never `bounds: input.bounds`. See the note above.
    ...(input.bounds ? { bounds: input.bounds } : {}),
  };
}
