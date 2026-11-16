/** Pure helpers for the Activities tab (investor app v2, PR 8). */
import type { Activity } from "@/api/client";

export interface ActivitySummary {
  done: number;
  total: number;
  /** Whole percent done, 0 when there is nothing. */
  pct: number;
}

export function activitySummary(list: Activity[]): ActivitySummary {
  const done = list.filter((a) => a.status === "completed").length;
  const total = list.length;
  return { done, total, pct: total === 0 ? 0 : Math.round((done / total) * 100) };
}

/** The day an activity is shown under: when it was done, else its plan date. */
export function activityDay(a: Activity): string {
  return (a.status === "completed" && a.completed_at ? a.completed_at : a.scheduled_date).slice(0, 10);
}

/** Newest first; on the same day, the later-planned one first, then by id. */
export function newestFirst(list: Activity[]): Activity[] {
  return [...list].sort(
    (a, b) =>
      activityDay(b).localeCompare(activityDay(a)) ||
      b.scheduled_date.localeCompare(a.scheduled_date) ||
      a.id.localeCompare(b.id),
  );
}
