// The index-pixel layer: which raster each block draws, and what the pixels
// add up to.
//
// One statistics call per block does double duty. It gives the legend its
// per-class AREA — counted from pixels inside the CURRENT boundary, which is
// what makes the total land on the farm's real area instead of the inflated
// figure a stale grid produced — and it gives each block its own MEAN, which
// is what the block polygon paints when the pixel layer is off. Both come from
// the same numbers the tiles are drawn from, so nothing on screen can disagree
// with anything else on screen.
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { listFarmSceneAssets, type FarmRaster, type FarmSceneAsset } from "@/api/imagery";
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import type { ConfigResponse } from "@/api/config";
import { mapWithConcurrency } from "../map/api";
import type { PixelLayer } from "../map/MapCanvas";
import { CONSOLE_QK } from "./constants";
import { classesFor } from "./indexClasses";
import {
  blockStatsUrl,
  blockTileUrl,
  TILE_SIZE,
  readBlockCounts,
  summariseClassAreas,
  type BandStatistics,
  type BlockPixelCounts,
  type ClassAreaSummary,
} from "./pixelTiles";

/** Fallback ground sample distance when the product row could not be read. */
const FALLBACK_RESOLUTION_M = 10;

/** Source id for the single farm-wide surface, distinct from any block id. */
export const FARM_SCOPE_ID = "__farm__";

interface PixelStats {
  counts: BlockPixelCounts[];
  /** Blocks whose raster could not be read — no object behind the asset row. */
  failedBlockIds: string[];
}

export interface IndexPixels {
  /** True when the whole farm is drawn from one stitched raster. */
  isFarmRaster: boolean;
  /** Raster layers for MapCanvas; empty when there is nothing to draw. */
  layers: PixelLayer[];
  /**
   * Blocks whose raster was actually READABLE for this scene.
   *
   * Not the number of assets the api named: an ingestion job can be recorded
   * as succeeded, carry a stac_item_id, and still have no object behind it —
   * older scenes on a reshaped block are the case that bit us. The api row is
   * a claim; the statistics call is the proof, so everything downstream counts
   * proven blocks.
   */
  assetCount: number;
  /** Per-block pixel counts, or undefined until the statistics land. */
  counts: BlockPixelCounts[] | undefined;
  /** Block id → mean index value for this scene, for the block-fill class. */
  meanByBlockId: Map<string, number>;
  /** Class areas across the farm, or narrowed to one block. */
  classAreas: (scopeBlockId: string | null) => ClassAreaSummary;
  assetsLoading: boolean;
  statsLoading: boolean;
  /** True when the api predates the scene-assets route. */
  unsupported: boolean;
}

/**
 * Read one raster's class histogram. Shared by both paths so the farm surface
 * and a single block are counted by identical arithmetic — the pilot's whole
 * test is that block means do not move when the source changes shape.
 *
 * A failure returns null rather than throwing: one raster failing must not
 * empty the legend, and a missing object is common enough on prod (3,787
 * AOI-scenes claim success with nothing behind them) that it is a normal
 * outcome, not an exception.
 */
async function readStats(input: {
  config: ConfigResponse;
  asset: { stac_item_id: string };
  code: ApiIndexCode;
  id: string;
  resolutionM: number;
}): Promise<BlockPixelCounts | null> {
  const url = blockStatsUrl({
    tileServerBaseUrl: input.config.tile_server_base_url,
    s3Bucket: input.config.s3_bucket,
    asset: input.asset,
    code: input.code,
  });
  try {
    const resp = await fetch(url);
    if (!resp.ok) return null;
    const body = (await resp.json()) as Record<string, BandStatistics | undefined>;
    const resolution = input.resolutionM;
    return readBlockCounts(
      input.id,
      body,
      Number.isFinite(resolution) && resolution > 0 ? resolution : FALLBACK_RESOLUTION_M,
    );
  } catch {
    return null;
  }
}

export function useIndexPixels(input: {
  farmId: string;
  code: ApiIndexCode;
  sceneAt: string | null;
  config: ConfigResponse | null;
  /** Block extents, so each raster source is bounded to its own block. */
  boundsByBlockId: Map<string, [number, number, number, number]>;
  /** The farm's own extent, for the single-source path. */
  farmBounds: [number, number, number, number] | null;
  /** The farm's surveyed area, so unread ground is measured against it. */
  farmAreaM2: number | null;
  enabled: boolean;
}): IndexPixels {
  const { farmId, code, sceneAt, config, boundsByBlockId, farmBounds, farmAreaM2 } = input;

  const assetsQ = useQuery({
    queryKey: CONSOLE_QK.sceneAssets(farmId, sceneAt),
    queryFn: () => listFarmSceneAssets(farmId, sceneAt ?? undefined),
    enabled: Boolean(farmId) && input.enabled,
    staleTime: 5 * 60_000,
  });
  const assets = useMemo<FarmSceneAsset[]>(() => assetsQ.data?.items ?? [], [assetsQ.data]);
  /**
   * When the farm has been stitched into one raster, that IS the layer: same
   * ground as all 36 block rasters, one file, and no seam where blocks meet
   * (each block's raster carries the shared boundary pixel, so drawing both
   * stacked two translucent copies of it). Null keeps the per-block path,
   * which is how the cutover runs one farm at a time.
   */
  const farmRaster = useMemo<FarmRaster | null>(() => assetsQ.data?.farm ?? null, [assetsQ.data]);

  // Statistics are fetched even when the pixel LAYER is hidden: the block
  // fill and the legend both read them, and they are what the panel would
  // otherwise have nothing to say. Bounded concurrency for the same reason
  // the grid route exists — a 36-block farm must not open 36 sockets at once.
  const statsQ = useQuery({
    queryKey: CONSOLE_QK.pixelStats(
      farmId,
      code,
      sceneAt,
      farmRaster ? -1 : assets.length,
    ),
    queryFn: async (): Promise<PixelStats> => {
      if (!config) return { counts: [], failedBlockIds: [] };
      if (farmRaster) {
        // One surface, one histogram. The id is the farm, not a block, so
        // scoping the legend to a block cannot narrow it — that arrives with
        // per-block zonal statistics over this raster.
        const counts = await readStats({
          config,
          asset: farmRaster,
          code,
          id: FARM_SCOPE_ID,
          resolutionM: Number(farmRaster.resolution_m),
        });
        return counts
          ? { counts: [counts], failedBlockIds: [] }
          : { counts: [], failedBlockIds: [FARM_SCOPE_ID] };
      }
      const results = await mapWithConcurrency(assets, 8, (asset) =>
        readStats({
          config,
          asset,
          code,
          id: asset.block_id,
          resolutionM: Number(asset.resolution_m),
        }),
      );
      const counts = results.filter((r): r is BlockPixelCounts => r !== null);
      const ok = new Set(counts.map((c) => c.blockId));
      return { counts, failedBlockIds: assets.map((a) => a.block_id).filter((id) => !ok.has(id)) };
    },
    enabled: Boolean(config) && (assets.length > 0 || farmRaster !== null) && input.enabled,
    staleTime: 5 * 60_000,
  });

  // Blocks whose raster could NOT be read. A missing object makes the tile
  // server answer 404 for every tile of that block, which MapLibre retries per
  // tile per zoom — so those layers have to go.
  //
  // But only once we KNOW they are bad. Waiting for the statistics before
  // drawing anything cost about 1.8s on every index switch, for an answer the
  // tiles do not need: they are drawn optimistically and the failures are
  // pruned when the probe lands. The scene strip greys out passes that were
  // never processed, so the optimistic path is nearly always right.
  const failedBlockIds = useMemo(
    () => new Set(statsQ.data?.failedBlockIds ?? []),
    [statsQ.data],
  );

  const layers = useMemo<PixelLayer[]>(() => {
    if (!config) return [];
    if (farmRaster) {
      if (failedBlockIds.has(FARM_SCOPE_ID)) return [];
      return [
        {
          id: FARM_SCOPE_ID,
          tileUrl: blockTileUrl({
            tileServerBaseUrl: config.tile_server_base_url,
            s3Bucket: config.s3_bucket,
            asset: farmRaster,
            code,
          }),
          bounds: farmBounds ?? undefined,
          tileSize: TILE_SIZE,
        },
      ];
    }
    return assets
      .filter((a) => !failedBlockIds.has(a.block_id))
      .map((asset) => ({
        id: asset.block_id,
        tileUrl: blockTileUrl({
          tileServerBaseUrl: config.tile_server_base_url,
          s3Bucket: config.s3_bucket,
          asset,
          code,
        }),
        bounds: boundsByBlockId.get(asset.block_id),
        tileSize: TILE_SIZE,
      }));
  }, [assets, config, code, boundsByBlockId, failedBlockIds, farmRaster, farmBounds]);

  // The block's own mean for this index and scene. Read off the same
  // statistics the tiles are drawn from rather than from the map summary,
  // which only carries three of the seven indices.
  const meanByBlockId = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of statsQ.data?.counts ?? []) {
      if (c.validPixels > 0 && Number.isFinite(c.meanValue)) m.set(c.blockId, c.meanValue);
    }
    return m;
  }, [statsQ.data]);

  const classAreas = useMemo(() => {
    const classCount = classesFor(code).length;
    return (scopeBlockId: string | null): ClassAreaSummary =>
      summariseClassAreas(
        statsQ.data?.counts ?? [],
        classCount,
        scopeBlockId,
        // Only the whole-farm scope has a known area to measure against; a
        // block scope falls back to masked pixels until per-block zonal
        // statistics over the farm raster land.
        scopeBlockId ? null : farmAreaM2,
      );
  }, [statsQ.data, code, farmAreaM2]);

  return {
    isFarmRaster: farmRaster !== null,
    layers,
    assetCount: statsQ.data ? statsQ.data.counts.length : farmRaster ? 1 : assets.length,
    counts: statsQ.data?.counts,
    meanByBlockId,
    classAreas,
    assetsLoading: assetsQ.isLoading,
    statsLoading: statsQ.isLoading,
    unsupported: assetsQ.data === null,
  };
}
