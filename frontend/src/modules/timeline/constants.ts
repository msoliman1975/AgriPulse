// Query keys and defaults for the Farm Timeline.
//
// Its own namespace, never the Farm Console's. The console answers "what
// does this farm look like now"; this screen answers "what did it look
// like on 3 June". Two of the four queries below take the same arguments
// the console's do, and a shared key would let one screen serve the other
// a warm answer for the wrong day.

import type { AnyIndexCode } from "@/api/indices";

export const TIMELINE_QK = {
  // The events read. Keyed on the whole window and the block: a narrower
  // window is a different answer, not a filter over a wider one.
  events: (farmId: string, from: string, to: string, blockId: string | null) =>
    ["timeline/events", farmId, from, to, blockId] as const,
  // Acquisition days. Keyed on the index because the request is — a farm
  // carrying both Sentinel-2 and Landsat has two independent streams.
  scenes: (farmId: string, index: string) => ["timeline/scenes", farmId, index] as const,
  // Which raster each block draws at one pass. `at` and the index are both
  // in the request, so both are in the key.
  sceneAssets: (farmId: string, at: string | null, index: string) =>
    ["timeline/sceneAssets", farmId, at, index] as const,
  blocks: (farmId: string) => ["timeline/blocks", farmId] as const,
  farm: (farmId: string) => ["timeline/farm", farmId] as const,
  trend: (farmId: string, index: string, from: string, to: string) =>
    ["timeline/trend", farmId, index, from, to] as const,
} as const;

/** The index the screen opens on, matching the Farm Console's default. */
export const DEFAULT_TIMELINE_INDEX: AnyIndexCode = "ndvi";

/** Window the screen opens on, in days back from today. */
export const DEFAULT_WINDOW_DAYS = 90;

/**
 * The widest window the API will answer. Mirrors `MAX_WINDOW_DAYS` in
 * `app/modules/timeline/service.py`; the two are checked against each
 * other in `windowGuard.test.ts`, because a frontend that lets a reader
 * pick 400 days only finds out at the 422.
 */
export const MAX_WINDOW_DAYS = 366;

/**
 * Frames per second at 1x. With speeds 1, 2 and 4 that is 1, 2 and 4 days
 * a second.
 *
 * It was 2, so the top speed ran 8 days a second and a frame lasted 125 ms.
 * Nothing on the screen could keep up with that: a datapoint lives for
 * `FADE_DAYS + 1` frames, which was 500 ms at 4x, and a tile that missed
 * its frame was already two frames late by the time it arrived. Halving the
 * clock buys every part of the screen twice as long, and the replay is
 * still 90 days in about 22 seconds at the top speed.
 */
export const BASE_FPS = 1;

/**
 * How many of the day's datapoints get a card beside the map.
 *
 * Six because the dock has to fit under the zoom control without reaching
 * the scrubber, and because a reader cannot hold more than a handful of
 * numbered references at once. Everything else is one row saying how many
 * were left out; the rail still lists all of them.
 */
export const CARD_SLOTS = 6;

/**
 * The shortest time a card keeps its slot, in milliseconds.
 *
 * Cards are chosen by rank, and on a busy day the ranking turns over
 * completely between frames — this farm has 108 alerts on 5 August. Without
 * a floor the dock would restack every frame and be unreadable at any
 * speed. A held slot is only protected from being DISPLACED by a
 * better-ranked event; a card whose datapoint has faded out leaves at once,
 * because the dock must never show something the map does not.
 */
export const CARD_MIN_SLOT_MS = 900;

/**
 * Passes kept on the map ahead of the play head, at zero opacity.
 *
 * A raster layer at zero opacity still loads its tiles, so this is how far
 * in advance TiTiler is asked for the picture the replay is about to need.
 * Sentinel-2 flies every ~5 days, so three passes is roughly a fortnight
 * of replay — about fifteen seconds at 1x, and about four at the 4x top
 * speed. Halving `BASE_FPS` doubled both without changing the depth.
 *
 * Three rather than more because each preloaded pass is a live set of tile
 * requests. Ten would put the whole window in flight at once and make the
 * frame the reader is actually looking at queue behind the rest.
 */
export const PRELOAD_PASSES = 3;

/**
 * Parallel scene-asset requests during the prepare step.
 *
 * The prepare step is JSON only — which raster each block draws for a
 * pass — so it is cheap per request but there is one per pass, and a year
 * of Sentinel-2 is ~70 of them. Six at a time keeps the browser's
 * per-host connection budget free for the tiles that follow.
 */
export const PREFETCH_CONCURRENCY = 6;
