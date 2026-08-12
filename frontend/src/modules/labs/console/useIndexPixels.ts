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

import { listFarmSceneAssets, type FarmSceneAsset } from "@/api/imagery";
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

interface PixelStats {
  counts: BlockPixelCounts[];
  /** Blocks whose raster could not be read — no object behind the asset row. */
  failedBlockIds: string[];
}

export interface IndexPixels {
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

export function useIndexPixels(input: {
  farmId: string;
  code: ApiIndexCode;
  sceneAt: string | null;
  config: ConfigResponse | null;
  /** Block extents, so each raster source is bounded to its own block. */
  boundsByBlockId: Map<string, [number, number, number, number]>;
  enabled: boolean;
}): IndexPixels {
  const { farmId, code, sceneAt, config, boundsByBlockId } = input;

  const assetsQ = useQuery({
    queryKey: CONSOLE_QK.sceneAssets(farmId, sceneAt),
    queryFn: () => listFarmSceneAssets(farmId, sceneAt ?? undefined),
    enabled: Boolean(farmId) && input.enabled,
    staleTime: 5 * 60_000,
  });
  const assets = useMemo<FarmSceneAsset[]>(() => assetsQ.data?.items ?? [], [assetsQ.data]);

  // Statistics are fetched even when the pixel LAYER is hidden: the block
  // fill and the legend both read them, and they are what the panel would
  // otherwise have nothing to say. Bounded concurrency for the same reason
  // the grid route exists — a 36-block farm must not open 36 sockets at once.
  const statsQ = useQuery({
    queryKey: CONSOLE_QK.pixelStats(farmId, code, sceneAt, assets.length),
    queryFn: async (): Promise<PixelStats> => {
      if (!config) return { counts: [], failedBlockIds: [] };
      const results = await mapWithConcurrency(assets, 8, async (asset) => {
        const url = blockStatsUrl({
          tileServerBaseUrl: config.tile_server_base_url,
          s3Bucket: config.s3_bucket,
          asset,
          code,
        });
        try {
          const resp = await fetch(url);
          if (!resp.ok) return null;
          const body = (await resp.json()) as Record<string, BandStatistics | undefined>;
          const resolution = Number(asset.resolution_m);
          return readBlockCounts(
            asset.block_id,
            body,
            Number.isFinite(resolution) && resolution > 0 ? resolution : FALLBACK_RESOLUTION_M,
          );
        } catch {
          // One block's statistics failing must not empty the whole legend.
          // The block is simply absent from the totals, which is visible as a
          // smaller covered area rather than as a wrong one.
          return null;
        }
      });
      const counts = results.filter((r): r is BlockPixelCounts => r !== null);
      const ok = new Set(counts.map((c) => c.blockId));
      return { counts, failedBlockIds: assets.map((a) => a.block_id).filter((id) => !ok.has(id)) };
    },
    enabled: Boolean(config) && assets.length > 0 && input.enabled,
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
  }, [assets, config, code, boundsByBlockId, failedBlockIds]);

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
      summariseClassAreas(statsQ.data?.counts ?? [], classCount, scopeBlockId);
  }, [statsQ.data, code]);

  return {
    layers,
    assetCount: statsQ.data ? statsQ.data.counts.length : assets.length,
    counts: statsQ.data?.counts,
    meanByBlockId,
    classAreas,
    assetsLoading: assetsQ.isLoading,
    statsLoading: statsQ.isLoading,
    unsupported: assetsQ.data === null,
  };
}
