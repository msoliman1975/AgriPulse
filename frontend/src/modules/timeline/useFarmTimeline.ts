// Everything the Farm Timeline page fetches and derives.
//
// The page is the layout; this is the machine. Split so the frame
// arithmetic can be read without JSX around it, and so the derivations
// that must not run per render (marks, rasters, frames) sit in one place
// with their dependencies visible.

import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { listBlocks } from "@/api/blocks";
import { getFarm } from "@/api/farms";
import { listFarmScenes, listFarmSceneAssets } from "@/api/imagery";
import { getFarmIndexTimeseries } from "@/api/insights";
import type { AnyIndexCode } from "@/api/indices";
import { getFarmTimeline, type TimelineEvent, type TimelineEventKind } from "@/api/timeline";
import { blockTileUrl, farmRasterForPass } from "@/modules/labs/console/pixelTiles";
import { useOptionalConfig } from "@/config/ConfigContext";
import type { TrendPoint } from "./components/Scrubber";
import type { RasterFrame, RasterLayer } from "./components/TimelineMap";
import {
  BASE_FPS,
  CARD_MIN_SLOT_MS,
  CARD_SLOTS,
  PREFETCH_CONCURRENCY,
  PRELOAD_PASSES,
  TIMELINE_QK,
} from "./constants";
import { cardKey, selectCards, type SlotState } from "./lib/cards";
import {
  buildFrames,
  dayIndex,
  drawablePasses,
  frameIndexOf,
  passForFrames,
  passSequence,
  visibleEvents,
  type PassDay,
} from "./lib/frames";
import { boundsOfMultiPolygon, padBounds, unionBounds, type SourceBounds } from "./lib/mapBounds";
import { buildBlockAnchors, buildBlockHighlights, buildMarks } from "./lib/marks";

/** Id the whole-farm raster is drawn under. Matches the console's scope id. */
const FARM_RASTER_ID = "__farm__";

export interface TimelineInput {
  farmId: string;
  blockId: string | null;
  from: string;
  to: string;
  index: AnyIndexCode;
  /**
   * Datapoint kinds the reader has switched on.
   *
   * Applied to the map AND the rail from one place, because the screen's
   * rule is that the two halves read the same frame. Filtering only the
   * map would let the rail list a flag that is not drawn.
   */
  visibleKinds: ReadonlySet<TimelineEventKind>;
}

export function useFarmTimeline(input: TimelineInput) {
  const { farmId, blockId, from, to, index, visibleKinds } = input;
  const config = useOptionalConfig().config;
  const queryClient = useQueryClient();

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
  /** The passes this window draws, in the order the replay reaches them. */
  const sequence = useMemo(() => passSequence(frames, passByFrame), [frames, passByFrame]);

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

  // ---- prepare ----------------------------------------------------------
  //
  // Pressing play used to start the replay against an empty cache. Every
  // pass then cost a scene-assets request the moment the play head reached
  // it, and the tiles behind it a second more, so the map ran seconds
  // behind the scrubber and kept catching up after the run had ended.
  //
  // So play now PREPARES first: it fetches, for every pass in the window,
  // the answer to "which raster does each block draw here". That is the
  // whole of the per-frame network work removed from playback. The tiles
  // themselves are handled by the map's preload window, which can only
  // start once these answers exist.
  //
  // Preparing is visible — the button says so and the run starts when it
  // finishes — rather than silent, because it takes a second or two on a
  // wide window and a play button that does nothing for two seconds reads
  // as broken.

  const [preparing, setPreparing] = useState(false);
  /** The window/scope/index the cache was prepared for, so it runs once. */
  const preparedKeyRef = useRef<string | null>(null);
  /** Bumped to abandon a prepare the reader cancelled by pressing again. */
  const prepareTokenRef = useRef(0);

  const prepareKey = `${farmId}|${blockId ?? ""}|${index}|${from}|${to}`;

  const prepare = useCallback(async (): Promise<void> => {
    const queue = [...sequence];
    let cursor = 0;
    const worker = async (): Promise<void> => {
      while (cursor < queue.length) {
        const pass = queue[cursor];
        cursor += 1;
        await queryClient.prefetchQuery({
          queryKey: TIMELINE_QK.sceneAssets(farmId, pass.at, index),
          queryFn: () => listFarmSceneAssets(farmId, pass.at, index),
          staleTime: 5 * 60_000,
        });
      }
    };
    await Promise.all(Array.from({ length: Math.min(PREFETCH_CONCURRENCY, queue.length) }, worker));
  }, [queryClient, sequence, farmId, index]);

  const startPlaying = useCallback(() => {
    // Pressing play at the end restarts from the beginning; otherwise the
    // button would look broken on the last frame.
    setFrameIndex((i) => (i >= frames.length - 1 ? 0 : i));
    setPlaying(true);
  }, [frames.length]);

  const togglePlay = useCallback(() => {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (preparing) {
      // A second press during the prepare is a cancel, not a queue.
      prepareTokenRef.current += 1;
      setPreparing(false);
      return;
    }
    if (preparedKeyRef.current === prepareKey || sequence.length === 0) {
      startPlaying();
      return;
    }
    prepareTokenRef.current += 1;
    const token = prepareTokenRef.current;
    setPreparing(true);
    void prepare().then(
      () => {
        if (prepareTokenRef.current !== token) return;
        preparedKeyRef.current = prepareKey;
        setPreparing(false);
        startPlaying();
      },
      () => {
        // A failed prefetch is not a reason to refuse to play: the
        // per-frame queries below still run, and the replay is merely as
        // slow as it used to be rather than broken.
        if (prepareTokenRef.current !== token) return;
        setPreparing(false);
        startPlaying();
      },
    );
  }, [playing, preparing, prepareKey, prepare, sequence.length, startPlaying]);

  const seek = useCallback((next: number) => {
    setPlaying(false);
    setFrameIndex(next);
  }, []);

  // ---- rasters ----------------------------------------------------------

  const currentPass = frameDay ? (passByFrame.get(frameDay) ?? null) : null;

  /**
   * The passes to hold on the map: the current one and the next few.
   *
   * A window rather than a single pass, because a raster layer at zero
   * opacity still loads its tiles — so the passes the replay is about to
   * reach are already drawn-but-dark by the time it reaches them. This is
   * the fix for the map trailing the scrubber; the pass swap becomes two
   * paint writes instead of an asset request plus a tile fetch.
   *
   * When no pass covers the current day — the frames before the window's
   * first acquisition — the window starts at the sequence's own head, so
   * the first image is loading while the reader is still on bare ground.
   */
  const windowPasses = useMemo<PassDay[]>(() => {
    if (sequence.length === 0) return [];
    const at = currentPass
      ? sequence.findIndex((p) => p.at === currentPass.at)
      : /* before the first pass */ 0;
    const start = at < 0 ? 0 : at;
    return sequence.slice(start, start + 1 + PRELOAD_PASSES);
  }, [sequence, currentPass]);

  const assetData = useQueries({
    queries: windowPasses.map((pass) => ({
      queryKey: TIMELINE_QK.sceneAssets(farmId, pass.at, index),
      queryFn: () => listFarmSceneAssets(farmId, pass.at, index),
      enabled: Boolean(farmId),
      staleTime: 5 * 60_000,
      // Half an hour, against react-query's five-minute default. A replay
      // scrubbed back and forth over one window must not re-fetch a pass it
      // already answered for, and the answer cannot go stale within a
      // sitting: which raster a block drew on 3 June is history.
      gcTime: 30 * 60_000,
    })),
    // `combine`, not the raw results, and it matters. `useQueries` returns
    // a NEW array every render; react-query structurally shares what
    // `combine` returns, so this keeps its identity while the answers are
    // the same. Without it `rasterFrames` is a new array on every frame
    // tick — eight a second at the 4x top speed — and the map re-syncs its
    // rasters each time, re-registering the listener that waits for tiles.
    combine: (results) => results.map((r) => r.data ?? null),
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

  /**
   * The ground the whole-farm raster covers, for its source `bounds`.
   *
   * Without it MapLibre requests tiles for the entire viewport, and the
   * viewport is mostly desert: measured on prod that was 24 tile 404s from
   * TiTiler on one frame, none of which could ever have returned an image.
   * A per-block source already avoids this because it carries its block's
   * extent; the farm surface had no per-block extent to carry, so the key
   * was omitted entirely.
   *
   * Taken from the farm AOI and widened by the blocks, because the two do
   * not always agree: a block drawn slightly outside the stored boundary
   * would otherwise fall outside the box and stop being requested. Padded
   * on top of that — see `padBounds`. Every step here only ever widens.
   */
  const farmRasterBounds = useMemo<SourceBounds | undefined>(() => {
    let box = boundsOfMultiPolygon(farmQ.data?.boundary ?? null);
    for (const b of boundsByBlockId.values()) box = unionBounds(box, b);
    return padBounds(box);
  }, [farmQ.data, boundsByBlockId]);

  /** Identity of one pass's raster set, stable across renders. */
  const rasterKey = useCallback(
    (at: string): string => `${index}|${blockId ?? "farm"}|${at}`,
    [index, blockId],
  );

  const rasterFrames = useMemo<RasterFrame[]>(() => {
    if (!config) return [];
    const out: RasterFrame[] = [];
    windowPasses.forEach((pass, n) => {
      const data = assetData[n];
      if (!data) return;
      // Only assets that belong to THIS pass. The query is keyed on `at`,
      // so a frame can never be built from another pass's answer — which is
      // what `keepPreviousData` used to allow, painting the previous pass
      // under a scrubber parked elsewhere: a wrong answer wearing the shape
      // of a right one. Holding the picture is now the map's job, and it
      // holds the LAYER rather than reusing the data.
      const items = blockId ? data.items.filter((a) => a.block_id === blockId) : data.items;

      // The farm raster must be the surface for this pass; `farmRasterForPass`
      // is where that is judged. It used to be judged against the blocks'
      // day, which threw the surface away on every farm that had cut over to
      // farm-level fetching — those farms stop writing block jobs, so their
      // block rows freeze while the surfaces carry on. In block scope a farm
      // raster is never right: it covers the whole farm.
      const farmRaster = blockId ? null : farmRasterForPass(data.farm, pass.at);

      const layers: RasterLayer[] = farmRaster
        ? [
            {
              id: FARM_RASTER_ID,
              tileUrl: blockTileUrl({
                tileServerBaseUrl: config.tile_server_base_url,
                s3Bucket: config.s3_bucket,
                asset: farmRaster,
                code: index,
              }),
              bounds: farmRasterBounds,
            },
          ]
        : items.map((asset) => ({
            id: asset.block_id,
            tileUrl: blockTileUrl({
              tileServerBaseUrl: config.tile_server_base_url,
              s3Bucket: config.s3_bucket,
              asset,
              code: index,
            }),
            bounds: boundsByBlockId.get(asset.block_id),
          }));

      if (layers.length === 0) return;
      out.push({ key: rasterKey(pass.at), layers });
    });
    return out;
  }, [
    assetData,
    windowPasses,
    config,
    index,
    blockId,
    boundsByBlockId,
    farmRasterBounds,
    rasterKey,
  ]);

  /** Which of the held frames is painted; null while there is no image. */
  const activeRasterKey = currentPass ? rasterKey(currentPass.at) : null;

  /**
   * The date of the pixels on screen, which is NOT the date on the
   * scrubber. Sentinel-2 flies every ~5 days, so most frames carry an
   * older pass forward, and the caption has to say which.
   */
  const imageDay = currentPass?.day ?? null;

  // ---- events on this frame ---------------------------------------------

  const events: TimelineEvent[] = useMemo(() => eventsQ.data?.events ?? [], [eventsQ.data]);
  const days = useMemo(() => dayIndex(eventsQ.data?.days ?? []), [eventsQ.data]);

  const visible = useMemo(() => {
    if (!frameDay) return [];
    // Filtered ONCE, here, so the map and the rail cannot disagree about
    // what is on screen. `days` — the scrubber's ticks — is deliberately
    // NOT filtered: the ticks say where in the window something happened,
    // and a reader who has hidden alerts still needs to find the day one
    // was raised in order to switch them back on.
    return visibleEvents(events, frameDay).filter((f) => visibleKinds.has(f.event.kind));
  }, [events, frameDay, visibleKinds]);

  const anchors = useMemo(
    () => buildBlockAnchors(blocks.map((b) => ({ id: b.id, boundary: b.boundary ?? null }))),
    [blocks],
  );

  // ---- the dock ---------------------------------------------------------
  //
  // Which six datapoints get a card, and which slot each holds. The slot
  // table is carried between frames in a ref rather than in state: it is an
  // input to the next selection, not something the screen renders, and
  // putting it in state would re-run this on its own answer.
  //
  // Written during the memo, which is safe because `selectCards` is
  // idempotent — fed its own output for the same frame it returns the same
  // slots, with the same `since` values, so React running the memo twice
  // changes nothing.
  const slotsRef = useRef<SlotState[]>([]);
  const cardSelection = useMemo(() => {
    const selection = selectCards(
      visible,
      anchors,
      slotsRef.current,
      Date.now(),
      CARD_SLOTS,
      CARD_MIN_SLOT_MS,
    );
    slotsRef.current = selection.slots;
    return selection;
  }, [visible, anchors]);

  const cardedKeys = useMemo(() => new Set(cardSelection.cards.map((c) => c.key)), [cardSelection]);

  // The carded six are drawn as DOM markers, so they must NOT also be in
  // the symbol source — a datapoint drawn twice is two marks the reader has
  // to work out are one thing, and the symbol underneath would take part in
  // collision against its own badge.
  const marks = useMemo(
    () =>
      buildMarks(
        visible.filter((f) => !cardedKeys.has(cardKey(f.event))),
        anchors,
      ),
    [visible, anchors, cardedKeys],
  );
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
    preparing,
    togglePlay,
    speed,
    setSpeed,
    passDays,
    currentPass,
    rasterFrames,
    activeRasterKey,
    imageDay,
    marks,
    cards: cardSelection.cards,
    cardOverflow: cardSelection.overflow,
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
