/**
 * How a pile of work is cut into piles a scout can act on.
 *
 * Three questions, asked in this order:
 *
 *   1. **Which farm?** A scout who walks two farms in a day plans the farm
 *      first and everything else second. This is the outer grouping and it is
 *      not optional — it is skipped only when there is one farm, where a
 *      choice of one is not a choice.
 *   2. **Where, or when?** Inside a farm, blocks answer "what is my route" and
 *      time buckets answer "what is my day". Which one is right depends on the
 *      scout, so both are one tap apart and neither is hidden.
 *   3. The list itself.
 *
 * Origin — `recommendation`, `alert`, `ad_hoc` — groups nothing. It names the
 * subsystem that raised the row, and nobody plans a day around that.
 */

import type { WorkItem } from "@/api/client";
import type { MessageKey } from "@/i18n";
import { dueAtMs } from "@/time";

export type GroupBy = "block" | "time";

/** Ahead of now. Fixed, ordered and small — unlike blocks, of which a farm has
 *  dozens. */
export type Bucket = "overdue" | "today" | "week" | "next" | "later";

/** Behind now. Finished work has no deadline left to miss, so it is cut by the
 *  day it was closed instead — which is the question actually being asked of
 *  it: what did I get done, and when. */
export type DoneBucket = "doneToday" | "doneWeek" | "doneEarlier" | "doneUnknown";

export const BUCKETS: Bucket[] = ["overdue", "today", "week", "next", "later"];
export const DONE_BUCKETS: DoneBucket[] = ["doneToday", "doneWeek", "doneEarlier"];

export const BUCKET_LABEL: Record<Bucket | DoneBucket, MessageKey> = {
  overdue: "bucket.overdue",
  today: "bucket.today",
  week: "bucket.week",
  next: "bucket.next",
  later: "bucket.later",
  doneToday: "bucket.doneToday",
  doneWeek: "bucket.doneWeek",
  doneEarlier: "bucket.doneEarlier",
  doneUnknown: "bucket.doneUnknown",
};

/** Local end of today, so "today" means the whole day and not this instant. */
function endOfToday(now: number): number {
  const d = new Date(now);
  d.setHours(23, 59, 59, 999);
  return d.getTime();
}

/** Local start of today, the mirror of the above for work already behind us. */
function startOfToday(now: number): number {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function bucketOf(item: WorkItem, now: number): Bucket {
  const due = dueAtMs(item.due_at);
  // No deadline is neither late nor today: it is work with no clock on it,
  // which is what `later` is for.
  if (due === null) return "later";
  if (due < now) return "overdue";
  const today = endOfToday(now);
  if (due <= today) return "today";
  if (due <= today + 7 * 86_400_000) return "week";
  if (due <= today + 14 * 86_400_000) return "next";
  return "later";
}

export function doneBucketOf(item: WorkItem, now: number): DoneBucket {
  const at = dueAtMs(item.completed_at ?? null);
  // Board work carries no closure time. Saying so beats filing it under a day
  // it may not have been finished on.
  if (at === null) return "doneUnknown";
  const start = startOfToday(now);
  if (at >= start) return "doneToday";
  if (at >= start - 7 * 86_400_000) return "doneWeek";
  return "doneEarlier";
}

/** The key an item groups under, for the currently chosen grouping. */
export function groupKeyOf(item: WorkItem, groupBy: GroupBy, now: number, done: boolean): string {
  if (groupBy === "block") return item.block_name ?? "";
  return done ? doneBucketOf(item, now) : bucketOf(item, now);
}

/** Soonest first; undated last. Ordering inside a group, not across them. */
export function bySoonest(a: WorkItem, b: WorkItem): number {
  const x = dueAtMs(a.due_at);
  const y = dueAtMs(b.due_at);
  if (x === null) return y === null ? 0 : 1;
  if (y === null) return -1;
  return x - y;
}

/** Most recently closed first: the proof of today's work is what a scout came
 *  to this list for, not what they did three weeks ago. */
export function byLatestClosed(a: WorkItem, b: WorkItem): number {
  const x = dueAtMs(a.completed_at ?? null) ?? dueAtMs(a.due_at) ?? 0;
  const y = dueAtMs(b.completed_at ?? null) ?? dueAtMs(b.due_at) ?? 0;
  return y - x;
}

/**
 * Worst thing inside, so a tile carries the urgency of what it hides.
 *
 * Finished work is never toned. A closed job that was late is history, and
 * painting a farm tile red for it would send a scout to the one farm that
 * needs nothing from them.
 */
export function tileTone(items: WorkItem[], now: number, done: boolean): string {
  if (done) return "";
  if (items.some((i) => bucketOf(i, now) === "overdue")) return "crit";
  if (items.some((i) => i.severity === "critical")) return "crit";
  if (items.some((i) => i.severity === "warning")) return "warn";
  return "";
}

/**
 * The same question asked one level out, and it needs a coarser answer.
 *
 * `tileTone` paints crit for anything overdue *or* anything critical. At block
 * level that is right — a block is small enough that both mean "go here". At
 * farm level it is not: a farm is dozens of blocks, so at least one critical
 * finding is the normal state and every farm tile comes up red. A signal that
 * is always on is not a signal.
 *
 * So the farm tile reserves red for the one thing that is genuinely about this
 * farm rather than about a block inside it: work that is already late. A
 * critical finding drops to amber, which still says "there is something here"
 * without claiming the day starts here.
 */
export function farmTone(items: WorkItem[], now: number, done: boolean): string {
  if (done) return "";
  if (items.some((i) => bucketOf(i, now) === "overdue")) return "crit";
  if (items.some((i) => i.severity === "critical" || i.severity === "warning")) return "warn";
  return "";
}

/** Earliest deadline in the pile — how tiles are ordered against each other. */
export function soonestIn(items: WorkItem[]): number {
  return Math.min(...items.map((i) => dueAtMs(i.due_at) ?? Number.MAX_SAFE_INTEGER));
}
