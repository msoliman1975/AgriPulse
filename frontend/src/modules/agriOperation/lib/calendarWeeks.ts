// The calendar step's weeks (pure): every week from the plan's first task to
// its last, grouped by growth stage, with every task active in each week.
// A dated item is one time a task is done (it gets a date field); a span item
// is a task whose window covers the week without a time falling in it (a task
// done once somewhere in weeks a–b, or a repeating task between two times).

import type {
  AllocatedActivityPreview,
  AllocationBlockSchedule,
  BlockStageDates,
} from "@/api/agriOperation";
import { addDays, daysBetween } from "./planDraft";

export interface CalendarItem {
  blockId: string;
  blockCode: string | null;
  activity: AllocatedActivityPreview;
}

export interface CalendarSpanItem {
  blockId: string;
  blockCode: string | null;
  /** The task's first time, for its title and repeat. */
  activity: AllocatedActivityPreview;
  /** The calendar weeks its window covers. */
  firstWeek: number;
  lastWeek: number;
  /** The next time after this week; null when none is left. */
  nextDate: string | null;
}

export interface CalendarWeek {
  /** 1 is the week of the plan's first task, then 2, 3 … */
  number: number;
  from: string;
  to: string;
  items: CalendarItem[];
  spans: CalendarSpanItem[];
}

export interface CalendarStageGroup {
  /** Null for weeks no stage of the first block covers. */
  stage: BlockStageDates | null;
  weeks: CalendarWeek[];
}

/** Every week from the first task to the last, each with the tasks active
 *  inside it. Weeks run from the earliest block start date's weekday; Week 1
 *  is the week of the first task, even when it comes before the start
 *  (owner's call, 2026-11-20). Pure. */
export function calendarWeeks(blocks: AllocationBlockSchedule[]): CalendarWeek[] {
  const items: CalendarItem[] = blocks.flatMap((b) =>
    b.activities.map((activity) => ({ blockId: b.block_id, blockCode: b.block_code, activity })),
  );
  if (items.length === 0) return [];
  const origin =
    [...blocks.map((b) => b.start_date)].sort()[0] ?? items[0]?.activity.scheduled_date ?? "";
  const index = (d: string): number => Math.floor(daysBetween(origin, d) / 7);
  const firstIndex = Math.min(
    ...items.map((it) => index(it.activity.window_start ?? it.activity.scheduled_date)),
    ...items.map((it) => index(it.activity.scheduled_date)),
  );
  const number = (i: number): number => i - firstIndex + 1;
  const byWeek = new Map<number, CalendarItem[]>();
  for (const it of items) {
    const i = index(it.activity.scheduled_date);
    byWeek.set(i, [...(byWeek.get(i) ?? []), it]);
  }

  // One entry per task (block + manual code) whose window spans weeks.
  const tasks = new Map<string, CalendarItem[]>();
  for (const it of items) {
    const a = it.activity;
    if (!a.window_start || !a.window_end) continue;
    if (index(a.window_end) === index(a.window_start)) continue;
    const k = `${it.blockId}|${a.activity_code ?? a.activity_key}`;
    tasks.set(k, [...(tasks.get(k) ?? []), it]);
  }
  const spanByWeek = new Map<number, CalendarSpanItem[]>();
  for (const times of tasks.values()) {
    const first = times.reduce((m, x) =>
      (x.activity.occurrence ?? 1) < (m.activity.occurrence ?? 1) ? x : m,
    );
    const a = first.activity;
    const lo = index(a.window_start as string);
    const hi = index(a.window_end as string);
    const dates = times.map((x) => x.activity.scheduled_date).sort();
    const timedWeeks = new Set(dates.map(index));
    for (let i = lo; i <= hi; i += 1) {
      if (timedWeeks.has(i)) continue;
      const weekEnd = addDays(origin, i * 7 + 6);
      spanByWeek.set(i, [
        ...(spanByWeek.get(i) ?? []),
        {
          blockId: first.blockId,
          blockCode: first.blockCode,
          activity: a,
          firstWeek: number(lo),
          lastWeek: number(hi),
          nextDate: dates.find((d) => d > weekEnd) ?? null,
        },
      ]);
    }
  }

  const keys = [...byWeek.keys(), ...spanByWeek.keys()];
  const first = Math.min(...keys);
  const last = Math.max(...keys);
  const weeks: CalendarWeek[] = [];
  for (let i = first; i <= last; i += 1) {
    const from = addDays(origin, i * 7);
    weeks.push({
      number: number(i),
      from,
      to: addDays(from, 6),
      items: (byWeek.get(i) ?? []).sort(
        (x, y) =>
          x.activity.scheduled_date.localeCompare(y.activity.scheduled_date) ||
          x.activity.activity_key.localeCompare(y.activity.activity_key),
      ),
      spans: (spanByWeek.get(i) ?? []).sort((x, y) =>
        x.activity.activity_key.localeCompare(y.activity.activity_key),
      ),
    });
  }
  return weeks;
}

/** Consecutive weeks grouped by the growth stage their first day falls in
 *  (else a stage that starts inside the week). Pure. */
export function groupWeeksByStage(
  weeks: CalendarWeek[],
  stages: BlockStageDates[] | undefined,
): CalendarStageGroup[] {
  const list = stages ?? [];
  const stageOf = (w: CalendarWeek): BlockStageDates | null =>
    list.find((s) => s.start_date <= w.from && w.from <= s.end_date) ??
    list.find((s) => w.from <= s.start_date && s.start_date <= w.to) ??
    null;
  const groups: CalendarStageGroup[] = [];
  for (const w of weeks) {
    const stage = stageOf(w);
    const prev = groups[groups.length - 1];
    if (prev && (prev.stage?.code ?? null) === (stage?.code ?? null)) prev.weeks.push(w);
    else groups.push({ stage, weeks: [w] });
  }
  return groups;
}
