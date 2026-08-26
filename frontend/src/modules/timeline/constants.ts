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

/** Frames per second at 1x. Eight is roughly a week a second at 8x. */
export const BASE_FPS = 2;
