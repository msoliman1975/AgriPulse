// Talking to the tile server: index pixels in, class areas out.
//
// Both directions are driven by `indexClasses.ts`. The tiles are coloured by
// the class table as a TiTiler interval colormap, and the areas are counted by
// the SAME boundaries handed to TiTiler as histogram bins — so the number in
// the legend row and the colour beside it describe one thing.
//
// Everything here is a pure function of (config, asset, index). No fetching,
// so it can be unit-tested; the queries live in useIndexPixels.
import type { AnyIndexCode as ApiIndexCode } from "@/api/indices";
import { histogramBins, titilerColormap } from "./indexClasses";

/**
 * Per-index COG key. The pipeline writes one raster per index beside the raw
 * bands under the scene's AOI-hashed prefix (`build_asset_key` in
 * `app/modules/imagery/storage.py`), and registers them on the pgstac item.
 */
export function indexAssetKey(
  asset: { stac_item_id: string },
  code: ApiIndexCode,
): string {
  return `${asset.stac_item_id}/${code}.tif`;
}

function assetUri(
  bucket: string,
  asset: { stac_item_id: string },
  code: ApiIndexCode,
): string {
  return `s3://${bucket}/${indexAssetKey(asset, code)}`;
}

function trimTrailingSlash(s: string): string {
  return s.endsWith("/") ? s.slice(0, -1) : s;
}

/**
 * How the tile server resamples when warping a 10 m raster onto a much finer
 * web-mercator tile — i.e. at every zoom a grower actually works at.
 *
 * Nearest gives literal 10 m squares, which read as a mosaic of boxes rather
 * than as a field. Bilinear interpolates the VALUES before they are
 * classified, so class edges follow the shape of the crop instead of the pixel
 * grid — and because interpolation happens in value space, the output still
 * contains ONLY class colours. Verified against prod: a tile rendered this way
 * decodes to the same four class colours as the nearest one, no blends.
 *
 * Note this is `reproject`, not `resampling`: the latter governs decimation on
 * READ and is a no-op when upsampling, which is the case here.
 *
 * The legend's areas are NOT affected — those come from /cog/statistics at
 * native resolution, so the numbers still describe the measured pixels while
 * the map draws their smoothed shape.
 */
const REPROJECT = "bilinear";

/**
 * Tile edge in pixels, for both the request and the MapLibre source.
 *
 * 512 rather than the 256 default because the cost here is per REQUEST, not
 * per pixel: measured against prod, one 512 tile renders in ~246ms while the
 * four 256 tiles covering the same ground cost ~1288ms in total and three
 * more round trips. A farm-wide view drops from ~92 tiles to ~25.
 */
export const TILE_SIZE = 512;

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
  /** A block asset or a whole-farm raster — only the prefix is read. */
  asset: { stac_item_id: string };
  code: ApiIndexCode;
}): string {
  const params = new URLSearchParams({
    url: assetUri(input.s3Bucket, input.asset, input.code),
    colormap: titilerColormap(input.code),
    reproject: REPROJECT,
    tilesize: String(TILE_SIZE),
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
  asset: { stac_item_id: string };
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

/** The UTC calendar day an instant falls in, or NaN if it will not parse. */
function utcDay(iso: string): number {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? Number.NaN : Math.floor(t / 86_400_000);
}

/**
 * The farm surface to draw for a pass, or null to fall back to per-block.
 *
 * A farm raster is only the right thing to draw when it is the SAME pass the
 * blocks resolved to. An api that hands back the LATEST farm raster next to a
 * historical pass's block rasters would paint today's pixels under a timeline
 * reading two years ago — a wrong answer wearing the shape of a right one, and
 * the seamed per-block path is the better failure: ugly rather than untrue.
 *
 * Agreement is judged on the acquisition DAY, not the instant. Blocks in
 * different Sentinel tiles are sensed minutes apart for what a grower calls
 * one pass, and the strip offers days; requiring identical instants threw away
 * a correct surface whenever the first block by id happened to be the one
 * sensed a minute later. Days are the unit both ends of this already speak.
 */
export function farmRasterForPass<T extends { scene_datetime: string }>(
  farm: T | null | undefined,
  items: readonly { scene_datetime: string }[],
): T | null {
  if (!farm) return null;
  // With no blocks there is no pass to disagree with — which is the normal
  // shape for a cut-over farm, whose block table stopped gaining rows.
  if (items.length === 0) return farm;
  const day = utcDay(farm.scene_datetime);
  return Number.isNaN(day) || day !== utcDay(items[0].scene_datetime) ? null : farm;
}

export interface ClassAreaSummary {
  /** Square metres per class, in the class table's order (lowest first). */
  areaM2ByClass: number[];
  /** Total area carrying a reading. */
  coveredM2: number;
  /** Ground in scope with no reading for this scene. */
  noDataM2: number;
}

/**
 * Sum per-class areas across blocks.
 *
 * `scopeBlockId` narrows to one block; pass null for the whole farm. A block
 * whose statistics failed is simply absent from `counts` and contributes
 * nothing — better an area that is short by one block than one inflated by a
 * block counted with a guessed resolution.
 *
 * `scopeAreaM2` is the ground the scope actually occupies, and it exists
 * because masked pixels are not it. A COG is a rectangle; the raster inside
 * it is clipped to a polygon, so every pixel in the bounding box that the
 * polygon misses counts as masked. Reported raw, that says a farm has
 * unread ground where it has no ground at all — on Bashier Elkhier, 56.9
 * feddan of "no reading" against a 203.4 feddan farm that only adds up if
 * you include six feddan of neighbouring desert. Given the farm's own area,
 * the honest figure is what is left of it after the readings.
 */
export function summariseClassAreas(
  counts: readonly BlockPixelCounts[],
  classCount: number,
  scopeBlockId: string | null,
  scopeAreaM2?: number | null,
): ClassAreaSummary {
  const areaM2ByClass = new Array<number>(classCount).fill(0);
  let coveredM2 = 0;
  let maskedM2 = 0;
  for (const c of counts) {
    if (scopeBlockId && c.blockId !== scopeBlockId) continue;
    for (let i = 0; i < classCount; i += 1) {
      const area = (c.perClass[i] ?? 0) * c.pixelAreaM2;
      areaM2ByClass[i] += area;
      coveredM2 += area;
    }
    maskedM2 += c.maskedPixels * c.pixelAreaM2;
  }
  // Pixels straddling the boundary are counted whole, so coverage can edge
  // past the surveyed area — clamp rather than report negative unread ground.
  const noDataM2 =
    scopeAreaM2 && scopeAreaM2 > 0 ? Math.max(0, scopeAreaM2 - coveredM2) : maskedM2;
  return { areaM2ByClass, coveredM2, noDataM2 };
}
