// Talking to the tile server: index pixels in, class areas out.
//
// Both directions are driven by `indexClasses.ts`. The tiles are coloured by
// the class table as a TiTiler interval colormap, and the areas are counted by
// the SAME boundaries handed to TiTiler as histogram bins — so the number in
// the legend row and the colour beside it describe one thing.
//
// Everything here is a pure function of (config, asset, index). No fetching,
// so it can be unit-tested; the queries live in useIndexPixels.
import type { FarmSceneAsset } from "@/api/imagery";
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { histogramBins, titilerColormap } from "./indexClasses";

/**
 * Per-index COG key. The pipeline writes one raster per index beside the raw
 * bands under the scene's AOI-hashed prefix (`build_asset_key` in
 * `app/modules/imagery/storage.py`), and registers them on the pgstac item.
 */
export function indexAssetKey(asset: FarmSceneAsset, code: ApiIndexCode): string {
  return `${asset.stac_item_id}/${code}.tif`;
}

function assetUri(bucket: string, asset: FarmSceneAsset, code: ApiIndexCode): string {
  return `s3://${bucket}/${indexAssetKey(asset, code)}`;
}

function trimTrailingSlash(s: string): string {
  return s.endsWith("/") ? s.slice(0, -1) : s;
}

/**
 * XYZ template for one block's index raster, for a MapLibre raster source.
 *
 * `{z}/{x}/{y}` are left intact for MapLibre to interpolate. There is
 * deliberately NO `rescale`: rescale stretches values into 0–255 before the
 * colormap is applied, which would leave every interval in the class table
 * pointing at the wrong data. Pixels outside every interval — nodata, cloud —
 * come back transparent, so the satellite base shows through wherever there
 * is no reading, and the legend accounts for that area separately.
 */
export function blockTileUrl(input: {
  tileServerBaseUrl: string;
  s3Bucket: string;
  asset: FarmSceneAsset;
  code: ApiIndexCode;
}): string {
  const params = new URLSearchParams({
    url: assetUri(input.s3Bucket, input.asset, input.code),
    colormap: titilerColormap(input.code),
  });
  return `${trimTrailingSlash(input.tileServerBaseUrl)}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?${params.toString()}`;
}

/**
 * Statistics URL for one block's index raster, binned on the class edges.
 *
 * `max_size` overrides TiTiler's 1024px default, under which a larger raster
 * is decimated before counting — which would silently understate every area
 * on a big block. Real blocks here are ~50–500px square at 10m, so 4096 costs
 * nothing and removes the failure mode.
 */
export function blockStatsUrl(input: {
  tileServerBaseUrl: string;
  s3Bucket: string;
  asset: FarmSceneAsset;
  code: ApiIndexCode;
}): string {
  const params = new URLSearchParams({
    url: assetUri(input.s3Bucket, input.asset, input.code),
    histogram_bins: histogramBins(input.code).join(","),
    max_size: "4096",
  });
  return `${trimTrailingSlash(input.tileServerBaseUrl)}/cog/statistics?${params.toString()}`;
}

/** The slice of TiTiler's /cog/statistics response this module reads. */
export interface BandStatistics {
  /** `[counts, edges]` — counts has one entry per class, edges has one more. */
  histogram: [number[], number[]];
  valid_pixels: number;
  masked_pixels: number;
  /** Mean over the valid pixels — the block's own reading for this scene. */
  mean: number;
}

export interface BlockPixelCounts {
  blockId: string;
  /** Pixel count per class, in the class table's own order (lowest first). */
  perClass: number[];
  /** Pixels with a reading. Equals the sum of `perClass`. */
  validPixels: number;
  /** Pixels inside the AOI with no usable reading — cloud, shadow, nodata. */
  maskedPixels: number;
  /** Square metres one pixel covers. */
  pixelAreaM2: number;
  /**
   * The block's mean for this index and scene. Taken from the same statistics
   * the areas come from, rather than from the map summary — which carries
   * only three of the seven indices, so a block would go uncoloured on the
   * other four.
   */
  meanValue: number;
}

/**
 * Read one block's statistics response into pixel counts per class.
 *
 * TiTiler keys statistics by band name; these rasters are single-band, so
 * take the first band rather than hard-coding "b1" — a renamed band would
 * otherwise silently zero the legend.
 */
export function readBlockCounts(
  blockId: string,
  body: Record<string, BandStatistics | undefined>,
  resolutionM: number,
): BlockPixelCounts | null {
  const band = Object.values(body).find((b): b is BandStatistics => Boolean(b?.histogram));
  if (!band) return null;
  const [counts] = band.histogram;
  return {
    blockId,
    perClass: counts,
    validPixels: band.valid_pixels,
    maskedPixels: band.masked_pixels,
    pixelAreaM2: resolutionM * resolutionM,
    meanValue: band.mean,
  };
}

export interface ClassAreaSummary {
  /** Square metres per class, in the class table's order (lowest first). */
  areaM2ByClass: number[];
  /** Total area carrying a reading. */
  coveredM2: number;
  /** Area inside the blocks with no reading for this scene. */
  noDataM2: number;
}

/**
 * Sum per-class areas across blocks.
 *
 * `scopeBlockId` narrows to one block; pass null for the whole farm. A block
 * whose statistics failed is simply absent from `counts` and contributes
 * nothing — better an area that is short by one block than one inflated by a
 * block counted with a guessed resolution.
 */
export function summariseClassAreas(
  counts: readonly BlockPixelCounts[],
  classCount: number,
  scopeBlockId: string | null,
): ClassAreaSummary {
  const areaM2ByClass = new Array<number>(classCount).fill(0);
  let coveredM2 = 0;
  let noDataM2 = 0;
  for (const c of counts) {
    if (scopeBlockId && c.blockId !== scopeBlockId) continue;
    for (let i = 0; i < classCount; i += 1) {
      const area = (c.perClass[i] ?? 0) * c.pixelAreaM2;
      areaM2ByClass[i] += area;
      coveredM2 += area;
    }
    noDataM2 += c.maskedPixels * c.pixelAreaM2;
  }
  return { areaM2ByClass, coveredM2, noDataM2 };
}
