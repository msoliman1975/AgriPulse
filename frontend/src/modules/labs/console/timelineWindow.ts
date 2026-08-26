// How much of the acquisition history the date bar opens on.
//
// A farm on Sentinel-2 accumulates a pass every two to five days, so two
// seasons is ~180 chips on one strip. Opened on all of them, the bar starts
// scrolled to one end and gives a reader no sense of where in the history
// they are; the passes that matter — the last few — are the ones they have to
// hunt for.
//
// Pure, and in its own file, so the windowing rule can be tested without a
// map, a query client or a farm.

import type { FarmScene } from "@/api/imagery";

/**
 * How far back the date bar opens, in days.
 *
 * Thirty covers three to five Sentinel-2 passes on an Egyptian farm and about
 * two on a cloudier one — the span a grower actually compares. The rest of the
 * history is one click away, it is just not the default.
 */
export const TIMELINE_DEFAULT_DAYS = 30;

/** The windows the date bar offers, in draw order. `null` is every pass held. */
export const TIMELINE_RANGES: readonly (number | null)[] = [30, 90, 365, null];

/**
 * The passes inside the window.
 *
 * Two rules that are easy to get wrong:
 *
 * 1. The window is anchored on the NEWEST PASS, not on today. A farm whose
 *    imagery stopped two months ago has nothing in the last 30 days, and
 *    anchoring on the clock would open its console on an empty date bar with
 *    nothing to say the history exists.
 * 2. A pass that is SELECTED is always kept, even when it falls outside.
 *    Otherwise scrubbing to an old date and then narrowing the window hides
 *    the very scene the map is drawing, and the bar disagrees with the map.
 *
 * `days === null` returns the list untouched.
 */
export function scenesWithin(
  scenes: readonly FarmScene[],
  days: number | null,
  selectedDate: string | null,
): readonly FarmScene[] {
  if (days === null || scenes.length === 0) return scenes;
  const newest = scenes.reduce((a, b) => (a.scene_date > b.scene_date ? a : b)).scene_date;
  const cutoff = new Date(`${newest}T00:00:00Z`);
  if (Number.isNaN(cutoff.getTime())) return scenes;
  cutoff.setUTCDate(cutoff.getUTCDate() - days);
  const from = cutoff.toISOString().slice(0, 10);
  // String comparison, not Date arithmetic: `scene_date` is an ISO calendar
  // day and lexical order IS chronological order for that shape. Parsing each
  // one back through a Date would reintroduce the timezone slide the strip's
  // own formatter documents.
  return scenes.filter((s) => s.scene_date >= from || s.scene_date === selectedDate);
}

/**
 * The instant the console reads the farm "as of", or null for "now".
 *
 * The END of the selected day. The satellite passes in the morning, so
 * cutting at the overpass instant would hide everything a scout recorded
 * later the same day — which is not what anyone means by "on the 12th".
 */
export function asOfInstant(sceneDate: string | null): string | null {
  return sceneDate ? `${sceneDate}T23:59:59.999Z` : null;
}
