// Everything the Farm Timeline page fetches and derives.
//
// The page is the layout; this is the machine. Split so the frame
// arithmetic can be read without JSX around it, and so the derivations
// that must not run per render (marks, rasters, frames) sit in one place
// with their dependencies visible.

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { listBlocks } from "@/api/blocks";
import { getFarm } from "@/api/farms";
import { listFarmScenes, listFarmSceneAssets } from "@/api/imagery";
import { getFarmIndexTimeseries } from "@/api/insights";
import type { AnyIndexCode } from "@/api/indices";
import { getFarmTimeline, type TimelineEvent } from "@/api/timeline";
import { blockTileUrl, farmRasterForPass } from "@/modules/labs/console/pixelTiles";
import { useOptionalConfig } from "@/config/ConfigContext";
import type { TrendPoint } from "./components/Scrubber";
import type { RasterLayer } from "./components/TimelineMap";
import { BASE_FPS, TIMELINE_QK } from "./constants";
import {
  buildFrames,
  dayIndex,
  drawablePasses,
  frameIndexOf,
  passForFrames,
  visibleEvents,
} from "./lib/frames";
import { buildBlockAnchors, buildBlockHighlights, buildMarks } from "./lib/marks";

/** Id the whole-farm raster is drawn under. Matches the console's scope id. */
const FARM_RASTER_ID = "__farm__";

export interface TimelineInput {
  farmId: string;
  blockId: string | null;
  from: string;
  to: string;
  index: AnyIndexCode;
}

export function useFarmTimeline(input: TimelineInput) {
  const { farmId, blockId, from, to, index } = input;
  const config = useOptionalConfig().config;

  // ---- reads ------------------------------------------------------------

  const farmQ = useQuery({
    queryKey: TIMELINE_QK.farm(farmId),
    queryFn: () => getFarm(farmId),
    enabled: Boolean(farmId),
    staleTime: 5 * 60_000,
  });

  const blocksQ = useQuery({
    queryKey: TIMELINE_QK.blocks(farmId),
    // Boundaries ride along on the list call. Fetching them one block at a
    // time is the fan-out that exhausted the API's connection pool on a
    // 36-block farm and took the whole map down with it.
    queryFn: () => listBlocks(farmId, { limit: 200, include_boundary: true }),
    enabled: Boolean(farmId),
    staleTime: 5 * 60_000,
  });

  const scenesQ = useQuery({
    queryKey: TIMELINE_QK.scenes(farmId, index),
    // 500 is the route's cap. A year of Sentinel-2 is ~70 passes, so this
    // covers the widest window the API will answer without paging.
    queryFn: () => listFarmScenes(farmId, index, 500),
    enabled: Boolean(farmId),
    staleTime: 5 * 60_000,
  });

  const eventsQ = useQuery({
    queryKey: TIMELINE_QK.events(farmId, from, to, blockId),
    queryFn: () => getFarmTimeline(farmId, { from, to, blockId }),
    enabled: Boolean(farmId) && from <= to,
    staleTime: 60_000,
  });

  const trendQ = useQuery({
    queryKey: TIMELINE_QK.trend(farmId, index, from, to),
    queryFn: () =>
      getFarmIndexTimeseries(farmId, {
        index_code: index,
        granularity: "daily",
        since: `${from}T00:00:00Z`,
        until: `${to}T23:59:59Z`,
      }),
    enabled: Boolean(farmId) && from <= to,
    staleTime: 5 * 60_000,
  });

  // ---- frames -----------------------------------------------------------

  const frames = useMemo(() => buildFrames(from, to), [from, to]);
  const passes = useMemo(() => drawablePasses(scenesQ.data?.items ?? []), [scenesQ.data]);
  const passByFrame = useMemo(() => passForFrames(frames, passes), [frames, passes]);
  const passDays = useMemo(() => new Set(passes.map((p) => p.day)), [passes]);

  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [focusedEventId, setFocusedEventId] = useState<string | null>(null);

  // Keep the reader's place when the window moves under them. Snapping to
  // the start of a new window on every date edit makes the controls feel
  // like they reset the screen rather than reframe it.
  const parkedDayRef = useRef<string | null>(null);
  useEffect(() => {
    const kept = frameIndexOf(frames, parkedDayRef.current);
    // -1 means there is no parked day yet (first mount) or it fell outside
    // the new window. The END of the window is the right landing for both:
    // the screen should open on the most recent day it holds, not on a
    // picture three months old, and a reader who widens the window is
    // almost always reaching further back from "now".
    setFrameIndex(kept >= 0 ? kept : Math.max(frames.length - 1, 0));
  }, [frames]);

  const frameDay = frames[frameIndex] ?? null;

  // Parked in an EFFECT, not during render. Writing the ref while rendering
  // parks frame 0 before the effect above has ever run, so the effect finds
  // it, keeps index 0, and the screen opens on the OLDEST day in the
  // window — a three-month-old picture under today's controls.
  useEffect(() => {
    parkedDayRef.current = frameDay;
  }, [frameDay]);

  // ---- playback ---------------------------------------------------------

  useEffect(() => {
    if (!playing || frames.length === 0) return;
    const id = window.setInterval(
      () => {
        setFrameIndex((i) => {
          const next = i + 1;
          if (next < frames.length) return next;
          // Stop at the end rather than looping. A replay that wraps
          // silently makes "have I already watched June" unanswerable.
          setPlaying(false);
          return i;
        });
      },
      1000 / (BASE_FPS * speed),
    );
    return () => window.clearInterval(id);
  }, [playing, speed, frames.length]);

  // Pressing play at the end restarts from the beginning; otherwise the
  // button would look broken on the last frame.
  const togglePlay = useCallback(() => {
    setPlaying((was) => {
      if (!was && frameIndex >= frames.length - 1) setFrameIndex(0);
      return !was;
    });
  }, [frameIndex, frames.length]);

  const seek = useCallback((next: number) => {
    setPlaying(false);
    setFrameIndex(next);
  }, []);

  // ---- rasters ----------------------------------------------------------

  const currentPass = frameDay ? (passByFrame.get(frameDay) ?? null) : null;

  const assetsQ = useQuery({
    queryKey: TIMELINE_QK.sceneAssets(farmId, currentPass?.at ?? null, index),
    queryFn: () => listFarmSceneAssets(farmId, currentPass?.at, index),
    enabled: Boolean(farmId) && currentPass !== null,
    staleTime: 5 * 60_000,
    // Holding the previous pass's assets while the next load is what keeps
    // the map from blanking between two frames that share no cache entry.
    placeholderData: keepPreviousData,
  });

  const blocks = useMemo(() => blocksQ.data?.items ?? [], [blocksQ.data]);

  const boundsByBlockId = useMemo(() => {
    const out = new Map<string, [number, number, number, number]>();
    for (const b of blocks) {
      if (!b.boundary) continue;
      let w = Infinity;
      let s = Infinity;
      let e = -Infinity;
      let n = -Infinity;
      for (const ring of b.boundary.coordinates) {
        for (const [lon, lat] of ring) {
          if (lon < w) w = lon;
          if (lon > e) e = lon;
          if (lat < s) s = lat;
          if (lat > n) n = lat;
        }
      }
      if (Number.isFinite(w)) out.set(b.id, [w, s, e, n]);
    }
    return out;
  }, [blocks]);

  const rasters = useMemo<RasterLayer[]>(() => {
    if (!config) return [];
    const data = assetsQ.data;
    if (!data) return [];
    // Only draw assets that belong to the pass this frame resolved to. The
    // query is keyed on `at`, but `keepPreviousData` deliberately serves the
    // previous pass during a load, and painting that under a scrubber
    // parked elsewhere would be a wrong answer wearing the shape of a right
    // one.
    const items = blockId ? data.items.filter((a) => a.block_id === blockId) : data.items;

    // The farm raster must be the surface for the pass this frame is parked
    // on; `farmRasterForPass` is where that is judged. It used to be judged
    // against the blocks' day, which threw the surface away on every farm
    // that had cut over to farm-level fetching — those farms stop writing
    // block jobs, so their block rows freeze while the surfaces carry on. In
    // block scope a farm raster is never right: it covers the whole farm.
    const farmRaster = blockId ? null : farmRasterForPass(data.farm, currentPass?.at ?? null);
    if (farmRaster) {
      return [
        {
          id: FARM_RASTER_ID,
          tileUrl: blockTileUrl({
            tileServerBaseUrl: config.tile_server_base_url,
            s3Bucket: config.s3_bucket,
            asset: farmRaster,
            code: index,
          }),
        },
      ];
    }
    return items.map((asset) => ({
      id: asset.block_id,
      tileUrl: blockTileUrl({
        tileServerBaseUrl: config.tile_server_base_url,
        s3Bucket: config.s3_bucket,
        asset,
        code: index,
      }),
      bounds: boundsByBlockId.get(asset.block_id),
    }));
  }, [assetsQ.data, config, index, blockId, boundsByBlockId, currentPass?.at]);

  // ---- events on this frame ---------------------------------------------

  const events: TimelineEvent[] = useMemo(() => eventsQ.data?.events ?? [], [eventsQ.data]);
  const days = useMemo(() => dayIndex(eventsQ.data?.days ?? []), [eventsQ.data]);

  const visible = useMemo(
    () => (frameDay ? visibleEvents(events, frameDay) : []),
    [events, frameDay],
  );

  const anchors = useMemo(
    () => buildBlockAnchors(blocks.map((b) => ({ id: b.id, boundary: b.boundary ?? null }))),
    [blocks],
  );

  const marks = useMemo(() => buildMarks(visible, anchors), [visible, anchors]);
  const highlights = useMemo(() => buildBlockHighlights(visible), [visible]);

  // ---- trend ------------------------------------------------------------

  const trend = useMemo<TrendPoint[]>(() => {
    const points = trendQ.data?.points ?? [];
    // The endpoint answers per BLOCK. Farm scope averages the blocks that
    // reported on a day, rather than summing them — a day when only four of
    // 36 blocks were cloud-free must not read as a collapse.
    const byDay = new Map<string, { sum: number; n: number }>();
    for (const p of points) {
      if (blockId && p.block_id !== blockId) continue;
      const value = Number(p.value);
      if (!Number.isFinite(value)) continue;
      const day = p.time.slice(0, 10);
      const bucket = byDay.get(day) ?? { sum: 0, n: 0 };
      bucket.sum += value;
      bucket.n += 1;
      byDay.set(day, bucket);
    }
    return [...byDay.entries()]
      .map(([day, b]) => ({ day, value: b.sum / b.n }))
      .sort((a, b) => a.day.localeCompare(b.day));
  }, [trendQ.data, blockId]);

  return {
    farmQ,
    blocksQ,
    eventsQ,
    blocks,
    frames,
    frameIndex,
    frameDay,
    seek,
    playing,
    togglePlay,
    speed,
    setSpeed,
    passDays,
    currentPass,
    rasters,
    marks,
    highlights,
    visible,
    days,
    trend,
    focusedEventId,
    setFocusedEventId,
    omittedKinds: eventsQ.data?.omitted_kinds ?? [],
    truncated: eventsQ.data?.truncated ?? false,
    /** True while the screen has no pixels to draw for this frame. */
    noImageYet: currentPass === null,
  };
}
