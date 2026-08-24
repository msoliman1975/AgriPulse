import { describe, expect, it } from "vitest";

import type { FarmSceneAsset } from "@/api/imagery";
import { classesFor } from "./indexClasses";
import {
  aoiHashFromStacItemId,
  blockStatsUrl,
  blockTileUrl,
  indexAssetKey,
  readBlockCounts,
  summariseClassAreas,
  TILE_SIZE,
  type BlockPixelCounts,
} from "./pixelTiles";

const ASSET: FarmSceneAsset = {
  block_id: "block-1",
  product_id: "product-1",
  stac_item_id: "sentinel_hub/s2_l2a/S2B_MSIL2A_20260810.SAFE/aoihash",
  scene_datetime: "2026-08-10T08:41:47Z",
  resolution_m: "10.00",
};

const BASE = { tileServerBaseUrl: "https://tiles.example.test/", s3Bucket: "bucket" };

describe("asset keys", () => {
  it("appends the index to the scene's AOI-hashed prefix", () => {
    expect(indexAssetKey(ASSET, "ndvi")).toBe(
      "sentinel_hub/s2_l2a/S2B_MSIL2A_20260810.SAFE/aoihash/ndvi.tif",
    );
  });

  it("changes with the index, so switching index cannot serve stale tiles", () => {
    expect(indexAssetKey(ASSET, "ndwi")).not.toBe(indexAssetKey(ASSET, "ndvi"));
  });
});

describe("blockTileUrl", () => {
  const url = blockTileUrl({ ...BASE, asset: ASSET, code: "ndvi" });

  it("leaves the XYZ placeholders for MapLibre", () => {
    expect(url).toContain("/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png");
  });

  it("does not trail a double slash off the configured base", () => {
    expect(url.startsWith("https://tiles.example.test/cog/")).toBe(true);
  });

  it("smooths in value space, not colour space", () => {
    // `reproject` interpolates the VALUES before they are classified, so the
    // output still holds only class colours. Blending the COLOURS instead —
    // MapLibre raster-resampling: linear — would invent shades that are in no
    // legend row, which is the whole thing this design exists to prevent.
    const cm = new URL(url.replace("{z}/{x}/{y}", "0/0/0"));
    expect(cm.searchParams.get("reproject")).toBe("bilinear");
    // `resampling` governs decimation on read and is a no-op upsampling, so
    // sending it instead would silently change nothing.
    expect(cm.searchParams.get("resampling")).toBeNull();
  });

  it("asks for one big tile rather than four small ones", () => {
    // The cost is per REQUEST, not per pixel: measured on prod, one 512 tile
    // renders in ~246ms while the four 256 tiles covering the same ground cost
    // ~1288ms in total. A farm view drops from ~92 tiles to ~25.
    //
    // In TiTiler's own spelling. This test used to assert `tilesize=512`, a
    // parameter the tile endpoint does not have — FastAPI dropped it, the
    // server returned its 256 default, and MapLibre stretched that over the
    // 512 footprint its source declares, which is what put the pixel grid
    // back on the map. Checked against the prod tile server: `tilesize=512`
    // returns a 256x256 PNG byte-identical to sending nothing at all.
    const p = new URL(url.replace("{z}/{x}/{y}", "0/0/0")).searchParams;
    expect(p.get("scale")).toBe("2");
    expect(Number(p.get("scale")) * 256).toBe(TILE_SIZE);
    expect(p.get("tilesize")).toBeNull();
  });

  it("never sends rescale, which would break the interval colormap", () => {
    // rescale stretches values to 0-255 BEFORE the colormap is applied, so
    // every class boundary would then point at the wrong data.
    expect(url).not.toContain("rescale");
  });

  it("sends the class table as the colormap", () => {
    const cm = new URL(url.replace("{z}/{x}/{y}", "0/0/0")).searchParams.get("colormap");
    expect(cm).not.toBeNull();
    const intervals = JSON.parse(cm as string) as [[number, number], number[]][];
    expect(intervals).toHaveLength(classesFor("ndvi").length);
  });
});

describe("blockStatsUrl", () => {
  const url = blockStatsUrl({ ...BASE, asset: ASSET, code: "ndvi" });

  it("bins the histogram on the class edges", () => {
    const bins = new URL(url).searchParams.get("histogram_bins");
    expect(bins).toBe("-3,0,0.1,0.2,0.4,0.6,0.8,3");
  });

  it("does not smooth the statistics, which must describe measured pixels", () => {
    // The map may draw an interpolated shape; the AREAS may not be interpolated
    // or the number stops being a measurement.
    expect(new URL(url).searchParams.get("reproject")).toBeNull();
  });

  it("raises max_size above the decimating default", () => {
    // TiTiler decimates above 1024px before counting, which would silently
    // understate every area on a large block.
    expect(Number(new URL(url).searchParams.get("max_size"))).toBeGreaterThan(1024);
  });
});

describe("readBlockCounts", () => {
  it("reads the first band rather than assuming it is named b1", () => {
    const counts = readBlockCounts(
      "block-1",
      {
        ndvi_band: {
          histogram: [
            [1, 2, 3],
            [-3, 0, 0.1, 3],
          ],
          valid_pixels: 6,
          masked_pixels: 4,
          mean: 0.21,
        },
      },
      10,
    );
    expect(counts?.perClass).toEqual([1, 2, 3]);
    expect(counts?.pixelAreaM2).toBe(100);
    // The block's own reading, for the fill it paints when pixels are off.
    expect(counts?.meanValue).toBe(0.21);
  });

  it("returns null when the response carries no histogram", () => {
    expect(readBlockCounts("block-1", {}, 10)).toBeNull();
  });
});

describe("summariseClassAreas", () => {
  // Two blocks at 10m: one 3-pixel class each, plus cloud.
  const counts: BlockPixelCounts[] = [
    {
      blockId: "a",
      perClass: [0, 2, 1],
      validPixels: 3,
      maskedPixels: 2,
      pixelAreaM2: 100,
      meanValue: 0.3,
    },
    {
      blockId: "b",
      perClass: [1, 0, 0],
      validPixels: 1,
      maskedPixels: 0,
      pixelAreaM2: 100,
      meanValue: 0.05,
    },
  ];

  it("sums the farm when no block is scoped", () => {
    const s = summariseClassAreas(counts, 3, null);
    expect(s.areaM2ByClass).toEqual([100, 200, 100]);
    expect(s.coveredM2).toBe(400);
    expect(s.noDataM2).toBe(200);
  });

  it("narrows to one block when scoped", () => {
    const s = summariseClassAreas(counts, 3, "a");
    expect(s.areaM2ByClass).toEqual([0, 200, 100]);
    expect(s.coveredM2).toBe(300);
    expect(s.scopedToBlock).toBe(true);
  });

  it("measures a block against its masked pixels, not the farm area", () => {
    // A block has no surveyed area of its own here, so the farm's must not be
    // borrowed: 600 m² of FARM minus 300 m² read is not this block's unread
    // ground.
    const s = summariseClassAreas(counts, 3, "a", 600);
    expect(s.noDataM2).toBe(200);
  });

  it("gives the whole farm when the reading is not held per block", () => {
    // A farm drawn from one stitched surface is measured once, under
    // FARM_SCOPE_ID. Filtering that to a block matched nothing and every
    // class read 0.0 — a farm with 219 measured passes reporting no land in
    // any colour. The farm figures are the honest answer, and `scopedToBlock`
    // is how the legend knows not to caption them with the block's name.
    const farmOnly: BlockPixelCounts[] = [
      {
        blockId: "__farm__",
        perClass: [1, 2, 1],
        validPixels: 4,
        maskedPixels: 2,
        pixelAreaM2: 100,
        meanValue: 0.3,
      },
    ];
    const s = summariseClassAreas(farmOnly, 3, "a", 600);
    expect(s.scopedToBlock).toBe(false);
    expect(s.areaM2ByClass).toEqual([100, 200, 100]);
    expect(s.coveredM2).toBe(400);
    // Farm-wide, so the farm's own area applies.
    expect(s.noDataM2).toBe(200);
  });

  it("gives the whole farm when the scoped block's statistics failed", () => {
    // Same rule, other cause: a block absent from `counts` cannot be narrowed
    // to. Zero would read as "no land in any class" rather than "not measured".
    const s = summariseClassAreas(counts, 3, "missing");
    expect(s.scopedToBlock).toBe(false);
    expect(s.coveredM2).toBe(400);
  });

  it("reports no block scope when none was asked for", () => {
    expect(summariseClassAreas(counts, 3, null).scopedToBlock).toBe(false);
  });

  it("counts covered area as exactly the sum of the classes", () => {
    // The invariant that makes the footer trustworthy: no pixel is in the
    // total but in no row, which is how the old cell-based legend drifted.
    const s = summariseClassAreas(counts, 3, null);
    expect(s.areaM2ByClass.reduce((a, b) => a + b, 0)).toBe(s.coveredM2);
  });

  it("ignores a block whose statistics never arrived", () => {
    const s = summariseClassAreas([counts[0]], 3, null);
    expect(s.coveredM2).toBe(300);
  });

  it("measures unread ground against the farm, not the bounding box", () => {
    // Masked pixels include everything in the COG's rectangle that the
    // boundary misses, so raw they claim unread ground outside the farm.
    // 600 m² of farm, 400 m² read: 200 m² unread — regardless of how much
    // desert the bounding box happens to enclose.
    const s = summariseClassAreas(counts, 3, null, 600);
    expect(s.coveredM2).toBe(400);
    expect(s.noDataM2).toBe(200);
  });

  it("never reports negative unread ground when coverage overhangs", () => {
    // Boundary pixels are counted whole, so a fully-read farm can measure
    // slightly larger than its surveyed area.
    const s = summariseClassAreas(counts, 3, null, 350);
    expect(s.noDataM2).toBe(0);
  });

  it("falls back to masked pixels when the farm area is unknown", () => {
    expect(summariseClassAreas(counts, 3, null, null).noDataM2).toBe(200);
    expect(summariseClassAreas(counts, 3, null, 0).noDataM2).toBe(200);
  });
});

describe("cutline", () => {
  it("reads the AOI hash off the end of the item id", () => {
    expect(aoiHashFromStacItemId(ASSET.stac_item_id)).toBe("aoihash");
  });

  it("has no hash to send when the item id carries no AOI segment", () => {
    expect(aoiHashFromStacItemId("")).toBeNull();
    expect(aoiHashFromStacItemId("abc")).toBeNull();
  });

  it("sends the cutline on both the tiles and the statistics", () => {
    const tile = new URL(
      blockTileUrl({ ...BASE, asset: ASSET, code: "ndvi", cutlineAoi: "aoihash" }).replace(
        "{z}/{x}/{y}",
        "0/0/0",
      ),
    ).searchParams;
    const stats = new URL(
      blockStatsUrl({ ...BASE, asset: ASSET, code: "ndvi", cutlineAoi: "aoihash" }),
    ).searchParams;

    // One rule cuts both. The areas do not move today, because statistics
    // are read at the raster's own resolution — this keeps them tied.
    for (const p of [tile, stats]) {
      expect(p.get("algorithm")).toBe("cutline");
      expect(JSON.parse(p.get("algorithm_params") as string)).toEqual({ aoi: "aoihash" });
    }
  });

  it("sends nothing at all when there is no AOI to cut to", () => {
    // A raster with no published boundary must render as it did before the
    // cutline existed, rather than not at all.
    const url = blockTileUrl({ ...BASE, asset: ASSET, code: "ndvi" });
    expect(url).not.toContain("algorithm");
    expect(blockStatsUrl({ ...BASE, asset: ASSET, code: "ndvi" })).not.toContain("algorithm");
  });
});
