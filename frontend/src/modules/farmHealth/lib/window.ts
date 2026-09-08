// The replay window, and the frame for one day inside it.
//
// The date axis is every calendar day. A day with no evaluation carries the
// previous verdict forward rather than being skipped — Mohamed chose that on
// 2026-09-07, and also chose not to label a carried value on screen: the
// screen shows the current state, and when it was produced is not what the
// reader is asking.
//
// The whole window is read once, as intervals, and each frame is rebuilt
// from them here. Asking the server per day would be 365 requests for a farm
// whose answers change a handful of times.

import type { Verdict } from "@/api/farmHealth";

export const DAY_MS = 86_400_000;

/** The fixed ranges, and the shape a custom one takes. */
export const RANGE_DAYS = { "30": 30, "90": 90, "365": 365 } as const;
export type RangeId = keyof typeof RANGE_DAYS | "custom";
export const DEFAULT_RANGE: RangeId = "30";

/** A custom window longer than five years is a mistake, not a request. */
export const MAX_RANGE_DAYS = 1830;

export interface DayWindow {
  /** Whole days since the epoch. Comparing these avoids time-of-day drift. */
  fromDay: number;
  toDay: number;
}

export function dayOf(date: Date): number {
  return Math.floor(date.getTime() / DAY_MS);
}

export function dateOf(day: number): Date {
  return new Date(day * DAY_MS);
}

/** `YYYY-MM-DD`, which is what a date input reads and writes. */
export function isoOf(day: number): string {
  const date = dateOf(day);
  const pad = (n: number) => (n < 10 ? `0${n}` : String(n));
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

export function dayOfIso(iso: string): number | null {
  const parsed = Date.parse(`${iso}T00:00:00Z`);
  return Number.isNaN(parsed) ? null : Math.floor(parsed / DAY_MS);
}

/** How many days the window covers, ends included. */
export function windowLength(win: DayWindow): number {
  return win.toDay - win.fromDay + 1;
}

/** A fixed range, ending today. */
export function rangeWindow(range: Exclude<RangeId, "custom">, today: number): DayWindow {
  const days = RANGE_DAYS[range];
  return { fromDay: today - (days - 1), toDay: today };
}

/**
 * A custom window, made usable.
 *
 * The end is clamped to today because there are no verdicts in the future;
 * reversed dates are swapped rather than refused, because a person who typed
 * them the wrong way round meant the range between them; and the length is
 * capped so one mistyped year does not ask for a decade.
 */
export function customWindow(fromIso: string, toIso: string, today: number): DayWindow | null {
  const from = dayOfIso(fromIso);
  const to = dayOfIso(toIso);
  if (from === null || to === null) return null;
  let start = from;
  let end = Math.min(to, today);
  if (start > end) [start, end] = [end, start];
  if (end - start + 1 > MAX_RANGE_DAYS) start = end - (MAX_RANGE_DAYS - 1);
  return { fromDay: start, toDay: end };
}

/**
 * One pass over the range in about the same time, whatever the range.
 *
 * A fixed interval makes a year unwatchable: 365 frames at 900ms is five and
 * a half minutes. The floor keeps a long range from outrunning the browser.
 */
export function frameMs(days: number, speed: number): number {
  return Math.max(55, Math.round(24_000 / Math.max(1, days - 1) / speed));
}

/**
 * The verdicts that stood on one day.
 *
 * The same interval test the SQL uses, so a frame the client draws and a row
 * the server would return for that instant cannot disagree:
 * `valid_from <= day AND (valid_to IS NULL OR valid_to > day)`.
 *
 * The comparison is made at the end of the chosen day. A verdict written at
 * 14:00 belongs to that day, and comparing against midnight would put it on
 * the next one.
 */
export function verdictsOn(verdicts: Verdict[], day: number): Verdict[] {
  const endOfDay = (day + 1) * DAY_MS - 1;
  return verdicts.filter((verdict) => {
    const from = Date.parse(verdict.valid_from);
    if (Number.isNaN(from) || from > endOfDay) return false;
    if (verdict.valid_to === null) return true;
    const to = Date.parse(verdict.valid_to);
    return Number.isNaN(to) ? true : to > endOfDay;
  });
}

/** Group a day's verdicts by block, which is how the rail reads them. */
export function byBlock(verdicts: Verdict[]): Map<string, Verdict[]> {
  const map = new Map<string, Verdict[]>();
  for (const verdict of verdicts) {
    const list = map.get(verdict.block_id);
    if (list) list.push(verdict);
    else map.set(verdict.block_id, [verdict]);
  }
  return map;
}
