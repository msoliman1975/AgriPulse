// The calendar step's weeks (pure): every week from the plan's first task to
// its last, with the tasks dated inside it.

import type { AllocationBlockSchedule, AllocatedActivityPreview } from "@/api/agriOperation";
import { addDays, daysBetween } from "./planDraft";

export interface CalendarItem {
  blockId: string;
  blockCode: string | null;
  activity: AllocatedActivityPreview;
}

export interface CalendarWeek {
  /** 1 is the week the plan starts; weeks before it are -1, -2 … */
  number: number;
  from: string;
  to: string;
  items: CalendarItem[];
}

/** Every week from the first task to the last, counted from the earliest
 *  block start date, each with the tasks dated inside it. Pure. */
export function calendarWeeks(blocks: AllocationBlockSchedule[]): CalendarWeek[] {
  const items: CalendarItem[] = blocks.flatMap((b) =>
    b.activities.map((activity) => ({ blockId: b.block_id, blockCode: b.block_code, activity })),
  );
  if (items.length === 0) return [];
  const origin =
    [...blocks.map((b) => b.start_date)].sort()[0] ?? items[0]?.activity.scheduled_date ?? "";
  const index = (d: string): number => Math.floor(daysBetween(origin, d) / 7);
  const byWeek = new Map<number, CalendarItem[]>();
  for (const it of items) {
    const i = index(it.activity.scheduled_date);
    byWeek.set(i, [...(byWeek.get(i) ?? []), it]);
  }
  const keys = [...byWeek.keys()];
  const first = Math.min(0, ...keys);
  const last = Math.max(...keys);
  const weeks: CalendarWeek[] = [];
  for (let i = first; i <= last; i += 1) {
    const from = addDays(origin, i * 7);
    weeks.push({
      number: i >= 0 ? i + 1 : i,
      from,
      to: addDays(from, 6),
      items: (byWeek.get(i) ?? []).sort(
        (x, y) =>
          x.activity.scheduled_date.localeCompare(y.activity.scheduled_date) ||
          x.activity.activity_key.localeCompare(y.activity.activity_key),
      ),
    });
  }
  return weeks;
}
