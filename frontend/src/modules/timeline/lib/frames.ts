// The replay's arithmetic: what a frame is, which raster it draws, and how
// long a datapoint stays on the map after its day.
//
// Everything here is pure, so it can be unit-tested without a map or a
// query client. The fetching lives in the page.

import type { FarmScene } from "@/api/imagery";
import type { TimelineDay, TimelineEvent } from "@/api/timeline";

/** Milliseconds in a day. Used only on UTC-midnight instants. */
const DAY_MS = 86_400_000;

/**
 * Days a datapoint keeps drawing after the day it happened.
 *
 * A mark that vanishes at midnight makes the replay unreadable at any
 * speed a person can watch: at 4 frames a second a flag is on screen for
 * 250 ms. Fading over three days keeps it legible while still saying,
 * through opacity, that it is behind the play head rather than on it.
 */
export const FADE_DAYS = 3;

/** `YYYY-MM-DD` for a UTC instant. */
export function toDayKey(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/**
 * Parse `YYYY-MM-DD` as UTC midnight.
 *
 * `new Date("2026-06-03")` already parses as UTC, but `new Date(2026, 5, 3)`
 * does not, and mixing the two is how a replay ends up one frame off for
 * every viewer west of Greenwich. Everything in this module goes through
 * here.
 */
export function parseDay(day: string): Date {
  return new Date(`${day}T00:00:00.000Z`);
}

/** Every calendar day from `from` to `to`, both inclusive. */
export function buildFrames(from: string, to: string): string[] {
  const start = parseDay(from).getTime();
  const end = parseDay(to).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
  const out: string[] = [];
  for (let t = start; t <= end; t += DAY_MS) out.push(toDayKey(new Date(t)));
  return out;
}

/** Whole days between two day keys; negative when `b` is before `a`. */
export function daysBetween(a: string, b: string): number {
  return Math.round((parseDay(b).getTime() - parseDay(a).getTime()) / DAY_MS);
}

export interface PassDay {
  /** The acquisition day, `YYYY-MM-DD`. */
  day: string;
  /** The instant to send as `at` on `/scene-assets` — the day's last sensing. */
  at: string;
}

/**
 * The passes worth drawing, oldest first.
 *
 * A day the satellite flew over but whose indices never ran has
 * `computed_count === 0` and renders nothing. Carrying such a day forward
 * would blank the map mid-replay under a scrubber that says a pass
 * happened — worse than showing the previous pass, which is at least true
 * of the ground. So they are dropped here rather than filtered at draw
 * time.
 */
export function drawablePasses(scenes: readonly FarmScene[]): PassDay[] {
  return scenes
    .filter((s) => s.computed_count > 0)
    .map((s) => ({ day: s.scene_date, at: s.at }))
    .sort((a, b) => a.day.localeCompare(b.day));
}

/**
 * Which pass each frame draws — the latest one at or before that day.
 *
 * This is the carry-forward rule the whole replay rests on. Sentinel-2
 * flies every ~5 days and cloud takes more, so most calendar days have no
 * image of their own; the honest thing to draw is the most recent one that
 * exists, and the scrubber marks which days were real acquisitions.
 *
 * Frames before the first pass in the window map to `null` — there is
 * nothing to carry forward yet, and drawing the FIRST pass backwards would
 * show a reader ground that had not been sensed on the date they are
 * looking at.
 */
export function passForFrames(
  frames: readonly string[],
  passes: readonly PassDay[],
): Map<string, PassDay | null> {
  const out = new Map<string, PassDay | null>();
  let i = 0;
  let current: PassDay | null = null;
  for (const frame of frames) {
    while (i < passes.length && passes[i].day <= frame) {
      current = passes[i];
      i += 1;
    }
    out.set(frame, current);
  }
  return out;
}

/**
 * The passes a window actually draws, in the order the replay reaches them.
 *
 * Distinct, because carry-forward means five consecutive frames usually
 * resolve to one pass, and the caller wants "what will be drawn next",
 * not "what is drawn tomorrow". This is the list the prefetch walks when
 * the reader presses play, and the list the preload window slides along.
 */
export function passSequence(
  frames: readonly string[],
  passByFrame: ReadonlyMap<string, PassDay | null>,
): PassDay[] {
  const out: PassDay[] = [];
  let last: string | null = null;
  for (const frame of frames) {
    const pass = passByFrame.get(frame) ?? null;
    if (pass && pass.at !== last) {
      out.push(pass);
      last = pass.at;
    }
  }
  return out;
}

/**
 * How strongly a datapoint draws on a given frame.
 *
 * 1 on its own day, stepping down to 0 once it is more than `fadeDays`
 * behind, and 0 for anything in the future. Future events return 0 rather
 * than being absent so the caller can keep one array and let opacity do
 * the work — a mark that pops into existence and one that fades in from
 * nothing look different, and only the second reads as time passing.
 */
export function eventOpacity(eventDay: string, frameDay: string, fadeDays = FADE_DAYS): number {
  const age = daysBetween(eventDay, frameDay);
  if (age < 0) return 0;
  if (age === 0) return 1;
  if (age > fadeDays) return 0;
  // Linear from 1 down to a floor of 0.25 at the last visible day, rather
  // than to 0: a mark at 0.02 opacity is invisible but still occupies a
  // collision slot, so it would hide the mark behind it while showing
  // nothing itself.
  return 1 - (age / (fadeDays + 1)) * 0.75;
}

/** Events on exactly this day, in the order the server sorted them. */
export function eventsOnDay(events: readonly TimelineEvent[], frameDay: string): TimelineEvent[] {
  return events.filter((e) => e.day === frameDay);
}

export interface FadedEvent {
  event: TimelineEvent;
  opacity: number;
}

/**
 * Events the map should draw on this frame, each with its own opacity.
 *
 * Sorted so the freshest is last. Marks are drawn in array order and the
 * caller's `symbol-sort-key` reads the index, so this ordering is what
 * makes today's flag win a collision against one from three days ago.
 */
export function visibleEvents(
  events: readonly TimelineEvent[],
  frameDay: string,
  fadeDays = FADE_DAYS,
): FadedEvent[] {
  const out: FadedEvent[] = [];
  for (const event of events) {
    const opacity = eventOpacity(event.day, frameDay, fadeDays);
    if (opacity > 0) out.push({ event, opacity });
  }
  out.sort((a, b) => a.opacity - b.opacity);
  return out;
}

/** Day key -> its counts, for the scrubber ticks. */
export function dayIndex(days: readonly TimelineDay[]): Map<string, TimelineDay> {
  return new Map(days.map((d) => [d.day, d]));
}

/**
 * The next frame index, or `null` when the play head has reached the end.
 *
 * Returning null rather than wrapping is deliberate: a replay that loops
 * silently makes "did I already watch June" unanswerable. The page stops
 * and the user presses play again.
 */
export function nextFrame(index: number, frameCount: number): number | null {
  const next = index + 1;
  return next < frameCount ? next : null;
}

/**
 * Clamp a day to the window and return its frame index, or -1.
 *
 * Used when the window changes under a parked play head: the date the user
 * was looking at is kept if it still exists, rather than snapping back to
 * the start of the new window.
 */
export function frameIndexOf(frames: readonly string[], day: string | null): number {
  if (day === null) return -1;
  return frames.indexOf(day);
}
