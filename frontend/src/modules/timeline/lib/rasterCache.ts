// The replay's raster cache: which pass is painted, which are quietly
// loading, and which have been paid for and kept.
//
// Its own module, and it imports only TYPES from maplibre-gl, so it can be
// tested against a fake map. Importing the library itself pulls in a
// worker `createObjectURL` that jsdom has no implementation for, which is
// why the swap logic had no test while it lived inside the component — and
// the swap logic is where the replay's lag lived.

import type { Map as MlMap } from "maplibre-gl";

import { TILE_SIZE } from "@/modules/labs/console/pixelTiles";
import { rasterSourceSpec } from "./rasterSource";

/** Prefix for every raster layer/source the timeline owns. */
const RASTER_PREFIX = "tl-raster-";

/** Opacity a painted index raster is drawn at. */
const RASTER_OPACITY = 0.85;

/**
 * How many passes may stay on the map at once.
 *
 * Frames are cached rather than removed, because removing a source throws
 * away its tiles and scrubbing back one day would then re-fetch every one
 * of them. The cap is what stops a 366-day window from holding seventy
 * passes of tiles in GPU memory: anything past it that is neither active
 * nor in the caller's preload list is dropped, oldest first.
 */
const MAX_CACHED_FRAMES = 12;

/** Layer/source ids are style keys, so a frame key must survive as one. */
function safeKey(key: string): string {
  return key.replace(/[^A-Za-z0-9_-]/g, "_");
}

/** One raster to draw for the current pass. */
export interface RasterLayer {
  /** Stable within a pass — the block id, or `__farm__` for a farm raster. */
  id: string;
  /** XYZ template with `{z}/{x}/{y}` intact. */
  tileUrl: string;
  /**
   * `[west, south, east, north]`. Bounding each block's source is what
   * stops 35 sources from each requesting tiles across the whole farm —
   * without it a farm-wide view costs 35x the tiles it needs.
   */
  bounds?: [number, number, number, number];
}

/**
 * Every raster of one pass, under a key that identifies the pass.
 *
 * The caller hands over the frame the play head is parked on AND the next
 * few, and names which of them is active. Everything in the list is put on
 * the map; only the active one is painted. That is the whole of the
 * preloading strategy: a layer at zero opacity still loads its tiles, so a
 * pass three acquisitions ahead of the play head is already in the tile
 * cache by the time the replay reaches it.
 */
export interface RasterFrame {
  /** Identity of the pass, index and scope this frame draws. */
  key: string;
  layers: readonly RasterLayer[];
}

/** Frame key -> the layer/source ids that frame owns, in insertion order. */
export type RasterCache = Map<string, string[]>;

export interface SyncInput {
  /** Every frame that should be ON the map: the active one and its preloads. */
  frames: readonly RasterFrame[];
  /** The one frame that should be PAINTED, or null to paint none. */
  activeKey: string | null;
  fadeMs: number;
  cache: { current: RasterCache };
  genRef: { current: number };
  /** Every raster is inserted before this layer, so it stays under it. */
  beforeLayerId?: string;
}

/**
 * Put the frames on the map and cross-fade to the active one.
 *
 * This replaces a remove-then-add swap, and the difference is the whole of
 * why the replay used to lag the scrubber.
 *
 * The old code built one generation of layers per pass, added it, and
 * removed the previous generation on the next `idle`. Three things went
 * wrong with that at playback speed. Tiles for a pass were only ever
 * requested at the moment the play head reached it, so the map showed the
 * previous pass for as long as TiTiler took — seconds, not frames. During
 * continuous playback the map rarely goes idle, so the removals queued up
 * and fired late, which is why passes kept swapping after the scrubber had
 * already stopped at the end of the window. And a scrub backwards threw
 * away tiles that had just been paid for.
 *
 * So frames are CACHED instead. Every frame the caller hands over is added
 * once, at zero opacity; a zero-opacity raster layer still loads its
 * tiles, so the passes ahead of the play head arrive before the play head
 * does. Making one active is then two paint writes and no style surgery.
 *
 * The fade waits for the incoming frame's tiles. Fading to a source that
 * has not loaded shows bare satellite for the length of the fade, which is
 * the gap this is meant to close; so when the new frame is not ready the
 * old one is HELD at full strength and the swap happens on the
 * `sourcedata` that completes it. `genRef` is what stops a held swap from
 * painting a pass the reader has since scrubbed away from.
 */
export function syncRasters(map: MlMap, input: SyncInput): void {
  const { frames, activeKey, fadeMs, cache, genRef, beforeLayerId } = input;
  genRef.current += 1;
  const gen = genRef.current;

  for (const frame of frames) {
    if (cache.current.has(frame.key)) continue;
    const ids: string[] = [];
    frame.layers.forEach((raster, n) => {
      const layerId = `${RASTER_PREFIX}${safeKey(frame.key)}-${n}-${safeKey(raster.id)}`;
      if (map.getSource(layerId)) return;
      // Built by `rasterSourceSpec` rather than inline, so the shape handed
      // to MapLibre is testable. An explicit `bounds: undefined` throws here
      // and takes the whole pixel layer with it; see that module for why.
      // 512 rather than 256 on tileSize: the cost is per REQUEST, not per
      // pixel, and `pixelTiles` already asks TiTiler for that size via `scale`.
      map.addSource(
        layerId,
        rasterSourceSpec({ tileUrl: raster.tileUrl, bounds: raster.bounds, tileSize: TILE_SIZE }),
      );
      map.addLayer(
        {
          id: layerId,
          type: "raster",
          source: layerId,
          paint: {
            // Added dark. Whether this frame is the one to paint is decided
            // below, once, for every frame in the cache.
            "raster-opacity": 0,
            "raster-resampling": "linear",
            // MapLibre's own zoom cross-fade, which is a different thing
            // from ours and only adds latency to a frame swap.
            "raster-fade-duration": 0,
          },
        },
        // Under the outlines and the marks, above the satellite. Inserting
        // before the highlight also means the newest frame sits on top of
        // the older ones, so a cross-fade reads as the new pass arriving.
        beforeLayerId && map.getLayer(beforeLayerId) ? beforeLayerId : undefined,
      );
      ids.push(layerId);
    });
    cache.current.set(frame.key, ids);
  }

  const wanted = new Set(frames.map((f) => f.key));
  evict(map, cache.current, wanted, activeKey);

  const active = activeKey !== null ? cache.current.get(activeKey) : undefined;
  const ready = active === undefined || active.every((id) => map.isSourceLoaded(id));

  const paint = (): void => {
    if (genRef.current !== gen) return;
    for (const [key, ids] of cache.current) {
      const target = key === activeKey ? RASTER_OPACITY : 0;
      for (const id of ids) {
        if (!map.getLayer(id)) continue;
        map.setPaintProperty(id, "raster-opacity-transition", { duration: fadeMs, delay: 0 });
        map.setPaintProperty(id, "raster-opacity", target);
      }
    }
  };

  if (ready) {
    paint();
    return;
  }

  // Not ready: hold whatever is on screen and swap when the tiles land.
  // `sourcedata` fires per tile, so the readiness test is re-run each time
  // rather than assumed from the first event.
  const onData = (): void => {
    if (genRef.current !== gen) {
      map.off("sourcedata", onData);
      return;
    }
    if (!active?.every((id) => map.getLayer(id) && map.isSourceLoaded(id))) return;
    map.off("sourcedata", onData);
    paint();
  };
  map.on("sourcedata", onData);
}

/**
 * Drop cached frames past the cap.
 *
 * Never the active frame, and never one the caller still lists — those are
 * the preloads, and evicting a preload would undo the work it exists to
 * do. Oldest first, which is insertion order, which for a forward replay
 * is the frames furthest behind the play head.
 */
function evict(
  map: MlMap,
  cache: RasterCache,
  wanted: ReadonlySet<string>,
  activeKey: string | null,
): void {
  if (cache.size <= MAX_CACHED_FRAMES) return;
  for (const key of [...cache.keys()]) {
    if (cache.size <= MAX_CACHED_FRAMES) return;
    if (key === activeKey || wanted.has(key)) continue;
    for (const id of cache.get(key) ?? []) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
    }
    cache.delete(key);
  }
}
