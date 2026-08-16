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
    for (const key of ["colormap", "reproject", "tilesize"]) {
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

describe("the surface must be the pass the blocks resolved to", () => {
  it("draws the farm raster when it is the same pass", () => {
    expect(farmRasterForPass(FARM, [BLOCK])).toBe(FARM);
  });

  it("refuses a farm raster from a different pass", () => {
    // Reproduces what prod returns for a historical date: the requested
    // pass's blocks alongside the LATEST farm surface. Drawing it would put
    // today's pixels under a timeline reading two years ago.
    const oldPass = { ...BLOCK, scene_datetime: "2024-05-17T08:41:48.000Z" };
    expect(farmRasterForPass(FARM, [oldPass])).toBeNull();
  });

  it("accepts a farm raster when there are no blocks to disagree with", () => {
    expect(farmRasterForPass(FARM, [])).toBe(FARM);
  });

  it("stays on the per-block path when there is no farm raster", () => {
    expect(farmRasterForPass(null, [BLOCK])).toBeNull();
    expect(farmRasterForPass(undefined, [BLOCK])).toBeNull();
  });

  it("compares instants, not strings", () => {
    // The same moment written two ways is the same pass.
    const sameMoment = { ...BLOCK, scene_datetime: "2026-08-10T09:41:47.000+01:00" };
    const farm = { ...FARM, scene_datetime: "2026-08-10T08:41:47.000Z" };
    expect(farmRasterForPass(farm, [sameMoment])).toBe(farm);
  });

  it("tolerates blocks sensed minutes apart within one pass", () => {
    // Two Sentinel tiles, one grower's pass. `items` is ordered by block id,
    // so which of the two instants lands first is arbitrary — requiring them
    // to be identical threw the surface away on a coin flip.
    const laterTile = { ...BLOCK, scene_datetime: "2026-08-10T08:44:12.000Z" };
    expect(farmRasterForPass(FARM, [laterTile])).toBe(FARM);
  });

  it("still refuses a surface from the day before", () => {
    // The cut-over failure this guard exists for: block rows stop being
    // written, so an unbounded "latest at or before" resolves them to the
    // last pre-cutover pass. A day apart is not one pass.
    const yesterday = { ...BLOCK, scene_datetime: "2026-08-09T23:59:59.000Z" };
    expect(farmRasterForPass(FARM, [yesterday])).toBeNull();
  });

  it("refuses an unparseable instant rather than guessing", () => {
    expect(farmRasterForPass({ ...FARM, scene_datetime: "not a date" }, [BLOCK])).toBeNull();
  });
});
