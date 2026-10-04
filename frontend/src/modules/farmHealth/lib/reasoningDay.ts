// The day the map is showing, for the reasoning panel.
//
// A verdict whose answer did not change stands for weeks, and every sweep
// in between re-checked it. The panel used to show the last check of all,
// so on a past day its readings came from a later image and its "Checked
// on" date was later than the day on the map. With the day, the server
// returns the latest check on or before it.
//
// A context rather than a prop: three different sections render the
// panel, and threading a prop through each is how one of them gets missed.

import { createContext } from "react";

import { DAY_MS } from "./window";

/** Whole days since the epoch, as `window.ts` counts them. Null: no day. */
export const ReasoningDayContext = createContext<number | null>(null);

/** The last instant of `day`, which is the instant the map's frame shows. */
export function endOfDayIso(day: number): string {
  return new Date((day + 1) * DAY_MS - 1).toISOString();
}
