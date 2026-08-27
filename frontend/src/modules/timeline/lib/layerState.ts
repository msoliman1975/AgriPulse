// What the replay is switched on to draw.
//
// Its own module rather than sitting beside the checkboxes, because the
// page derives the hook's kind filter from it and a component file that
// also exports plain values loses fast refresh.

import type { TimelineEventKind } from "@/api/timeline";

/** Every datapoint kind the screen can draw, in reading order. */
export const LAYER_KINDS: readonly TimelineEventKind[] = [
  "alert",
  "recommendation",
  "flag",
  "signal",
  "visit",
  "activity",
  "stage",
];

export interface TimelineLayerState {
  /** The index raster. Off keeps the loaded tiles, so on is instant. */
  pixels: boolean;
  farmBoundary: boolean;
  blocks: boolean;
  kinds: Record<TimelineEventKind, boolean>;
}

/** Everything on. The screen's whole point is to show what happened. */
export function defaultLayerState(): TimelineLayerState {
  return {
    pixels: true,
    farmBoundary: true,
    blocks: true,
    kinds: {
      alert: true,
      recommendation: true,
      flag: true,
      signal: true,
      visit: true,
      activity: true,
      stage: true,
    },
  };
}
