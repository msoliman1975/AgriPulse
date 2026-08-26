import { describe, expect, it } from "vitest";

import type { FarmRaster, FarmSceneAsset } from "@/api/imagery";
import { blockStatsUrl, blockTileUrl, farmRasterForPass, indexAssetKey } from "./pixelTiles";

/**
 * A farm raster and a block asset are the same thing to the URL builders:
 * a prefix that a raster lives under. That is what lets the console draw
 * either without a second code path, and what makes the cutover a per-farm
 * data question rather than a rendering one.
 */
const BLOCK: FarmSceneAsset = {
  block_id: "block-1",
  product_id: "product-1",
  stac_item_id: "sentinel_hub/s2_l2a/S2B_20260810.SAFE/blockhash",
  scene_datetime: "2026-08-10T08:41:47Z",
  resolution_m: "10.00",
};

const FARM: FarmRaster = {
  stac_item_id: "sentinel_hub/s2_l2a/S2B_20260810.SAFE/farmhash",
  scene_datetime: "2026-08-10T08:41:47Z",
  resolution_m: "10.00",
  blocks_merged: 36,
  source: "stitched",
};

const BASE = { tileServerBaseUrl: "https://tiles.example.test", s3Bucket: "bucket" };

describe("farm raster and block asset are interchangeable", () => {
  it("builds an index key from either", () => {
    expect(indexAssetKey(FARM, "ndvi")).toBe(
      "sentinel_hub/s2_l2a/S2B_20260810.SAFE/farmhash/ndvi.tif",
    );
    expect(indexAssetKey(BLOCK, "ndvi")).toBe(
      "sentinel_hub/s2_l2a/S2B_20260810.SAFE/blockhash/ndvi.tif",
    );
  });

  it("points the tiles at the farm prefix, with the same colours and smoothing", () => {
    const farmUrl = blockTileUrl({ ...BASE, asset: FARM, code: "ndvi" });
    const blockUrl = blockTileUrl({ ...BASE, asset: BLOCK, code: "ndvi" });
    const p = (u: string) => new URL(u.replace("{z}/{x}/{y}", "0/0/0")).searchParams;

    expect(p(farmUrl).get("url")).toContain("/farmhash/ndvi.tif");
    // Everything that decides what the pixels LOOK like is identical, so a
    // farm draws in exactly the classes its blocks did.
    for (const key of ["colormap", "reproject", "scale"]) {
      // Not `toBe` alone: two nulls would satisfy that, which is how the old
      // `tilesize` spelling passed this test while sending nothing the server
      // understood. Each value has to be present as well as equal.
      expect(p(farmUrl).get(key)).not.toBeNull();
      expect(p(farmUrl).get(key)).toBe(p(blockUrl).get(key));
    }
  });

  it("counts the farm surface with the same histogram bins as a block", () => {
    const farmStats = blockStatsUrl({ ...BASE, asset: FARM, code: "ndvi" });
    const blockStats = blockStatsUrl({ ...BASE, asset: BLOCK, code: "ndvi" });
    const p = (u: string) => new URL(u).searchParams;

    expect(p(farmStats).get("histogram_bins")).toBe(p(blockStats).get("histogram_bins"));
    expect(p(farmStats).get("max_size")).toBe(p(blockStats).get("max_size"));
    // Areas must describe measured pixels, so neither is smoothed.
    expect(p(farmStats).get("reproject")).toBeNull();
  });

  it("keeps the farm and block prefixes distinct", () => {
    // Same scene, different AOI hash: a farm raster can never be confused for
    // one of its blocks, which is what stops a reshape serving stale ground.
    expect(indexAssetKey(FARM, "ndvi")).not.toBe(indexAssetKey(BLOCK, "ndvi"));
  });
});

describe("the surface must be the surface for the date asked for", () => {
  const ASKED = "2026-08-10T08:41:47Z";

  it("draws the farm raster for the requested day", () => {
    expect(farmRasterForPass(FARM, ASKED)).toBe(FARM);
  });

  it("draws the latest farm raster when no date is asked for", () => {
    // "Latest" is what an empty timeline selection means, and the latest
    // surface is the answer to it.
    expect(farmRasterForPass(FARM, null)).toBe(FARM);
    expect(farmRasterForPass(FARM, undefined)).toBe(FARM);
  });

  it("refuses a surface from a different day than the one asked for", () => {
    // Drawing it would put one day's pixels under a date bar reading another.
    expect(farmRasterForPass(FARM, "2024-05-17T08:41:48.000Z")).toBeNull();
  });

  it("keeps the surface when the blocks froze on an older pass", () => {
    // The regression this replaced. A farm on farm-level fetching stops
    // writing block ingestion jobs, so its block rows freeze on the cut-over
    // day while the surfaces carry on daily. Judging the surface against the
    // blocks rejected every pass after the cut-over: on prod, agrosina's
    // Bashier Elkhier had a 2026-08-25 surface and a newest block job from
    // 2026-08-10, so the console drew 36 stale block rasters instead of one
    // current surface. The blocks are not the reference any more, so a farm
    // in that shape is unaffected by how old they are.
    const surface = { ...FARM, scene_datetime: "2026-08-25T08:41:46.290Z" };
    expect(farmRasterForPass(surface, "2026-08-25T08:41:46.290Z")).toBe(surface);
  });

  it("stays on the per-block path when there is no farm raster", () => {
    expect(farmRasterForPass(null, ASKED)).toBeNull();
    expect(farmRasterForPass(undefined, ASKED)).toBeNull();
  });

  it("compares instants, not strings", () => {
    // The same moment written two ways is the same day.
    expect(farmRasterForPass(FARM, "2026-08-10T09:41:47.000+01:00")).toBe(FARM);
  });

  it("tolerates a surface sensed minutes from the instant asked for", () => {
    // The strip offers days; the instant behind a day is whichever pass it
    // resolved to, and a surface is stitched from tiles sensed minutes apart.
    const laterTile = { ...FARM, scene_datetime: "2026-08-10T08:44:12.000Z" };
    expect(farmRasterForPass(laterTile, ASKED)).toBe(laterTile);
  });

  it("refuses a surface from the day before the one asked for", () => {
    const yesterday = { ...FARM, scene_datetime: "2026-08-09T23:59:59.000Z" };
    expect(farmRasterForPass(yesterday, ASKED)).toBeNull();
  });

  it("refuses an unparseable surface instant rather than guessing", () => {
    expect(farmRasterForPass({ ...FARM, scene_datetime: "not a date" }, ASKED)).toBeNull();
  });

  it("draws the surface rather than nothing when the asked-for instant is junk", () => {
    // A date the console could not parse is its own bug; falling back to the
    // seamed per-block path would hide it behind a merely uglier map.
    expect(farmRasterForPass(FARM, "not a date")).toBe(FARM);
  });
});
