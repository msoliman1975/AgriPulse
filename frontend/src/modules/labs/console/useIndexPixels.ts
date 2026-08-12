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
  readBlockCounts,
  summariseClassAreas,
  type BandStatistics,
  type BlockPixelCounts,
  type ClassAreaSummary,
} from "./pixelTiles";

/** Fallback ground sample distance when the product row could not be read. */
const FALLBACK_RESOLUTION_M = 10;

export interface IndexPixels {
  /** Raster layers for MapCanvas; empty when there is nothing to draw. */
  layers: PixelLayer[];
  /** Blocks with a raster for this scene — the pixel layer's real coverage. */
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

  const layers = useMemo<PixelLayer[]>(() => {
    if (!config) return [];
    return assets.map((asset) => ({
      id: asset.block_id,
      tileUrl: blockTileUrl({
        tileServerBaseUrl: config.tile_server_base_url,
        s3Bucket: config.s3_bucket,
        asset,
        code,
      }),
      bounds: boundsByBlockId.get(asset.block_id),
    }));
  }, [assets, config, code, boundsByBlockId]);

  // Statistics are fetched even when the pixel LAYER is hidden: the block
  // fill and the legend both read them, and they are what the panel would
  // otherwise have nothing to say. Bounded concurrency for the same reason
  // the grid route exists — a 36-block farm must not open 36 sockets at once.
  const statsQ = useQuery({
    queryKey: CONSOLE_QK.pixelStats(farmId, code, sceneAt, assets.length),
    queryFn: async (): Promise<BlockPixelCounts[]> => {
      if (!config) return [];
      const results = await mapWithConcurrency(assets, 4, async (asset) => {
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
      return results.filter((r): r is BlockPixelCounts => r !== null);
    },
    enabled: Boolean(config) && assets.length > 0 && input.enabled,
    staleTime: 5 * 60_000,
  });

  // The block's own mean for this index and scene. Read off the same
  // statistics the tiles are drawn from rather than from the map summary,
  // which only carries three of the seven indices.
  const meanByBlockId = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of statsQ.data ?? []) {
      if (c.validPixels > 0 && Number.isFinite(c.meanValue)) m.set(c.blockId, c.meanValue);
    }
    return m;
  }, [statsQ.data]);

  const classAreas = useMemo(() => {
    const classCount = classesFor(code).length;
    return (scopeBlockId: string | null): ClassAreaSummary =>
      summariseClassAreas(statsQ.data ?? [], classCount, scopeBlockId);
  }, [statsQ.data, code]);

  return {
    layers,
    assetCount: assets.length,
    counts: statsQ.data,
    meanByBlockId,
    classAreas,
    assetsLoading: assetsQ.isLoading,
    statsLoading: statsQ.isLoading,
    unsupported: assetsQ.data === null,
  };
}
