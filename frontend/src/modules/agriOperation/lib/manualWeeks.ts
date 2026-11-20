// The manual week by week (owner's review, 2026-11-20): stage -> each week of
// the stage -> every task active that week. A task that runs over several
// weeks is listed in each of them; a repeating one says how many times it
// falls in that week. Week numbers only (Week 1, Week 2 …): a manual has no
// dates until a plan gives it a start. Pure.

import type { PlanTemplateActivity } from "@/api/planTemplates";
import { occurrenceOffsets } from "./occurrences";
import { activityWeek, type SeasonLayout, type StageWindow } from "./weeks";

export interface ManualWeekTask {
  activity: PlanTemplateActivity;
  /** The weeks the task's window covers. */
  firstWeek: number;
  lastWeek: number;
  /** Times the task falls in this week; null for a task done once. */
  timesThisWeek: number | null;
}

export interface ManualWeek {
  week: number;
  tasks: ManualWeekTask[];
}

export interface ManualStageGroup {
  /** Null for weeks no stage covers. */
  window: StageWindow | null;
  /** Year 1, 2 … of a manual timed from the start date (no stages). */
  year?: number;
  weeks: ManualWeek[];
}

export interface ManualWeeks {
  /** "stages": weeks of the season under each growth stage. "start": a
   *  manual timed from the block's start date only (e.g. a new planting),
   *  counted from its first task (Week 1) and grouped by year. */
  mode: "stages" | "start";
  groups: ManualStageGroup[];
  /** Tasks that have no week in this layout (e.g. a perennial task timed
   *  from the block's own start date): listed apart. */
  unplaced: PlanTemplateActivity[];
}

const YEAR_WEEKS = 52;

export function manualWeeks(layout: SeasonLayout, activities: PlanTemplateActivity[]): ManualWeeks {
  const fromStart = activities.filter((a) => a.anchor === "start");
  if (fromStart.length > 0 && !activities.some((a) => a.anchor === "stage")) {
    return startWeeks(activities);
  }
  const placed: Placed[] = [];
  const unplaced: PlanTemplateActivity[] = [];
  for (const a of activities) {
    const first = activityWeek(a, layout);
    if (first === null) unplaced.push(a);
    else placed.push(place(a, first, layout.totalWeeks));
  }
  const weekTasks = (week: number): ManualWeekTask[] => tasksIn(placed, week);

  const groups: ManualStageGroup[] = [];
  const covered = new Set<number>();
  for (const w of layout.windows) {
    const weeks: ManualWeek[] = [];
    for (let week = w.startWeek; week <= w.endWeek; week += 1) {
      if (covered.has(week)) continue;
      covered.add(week);
      weeks.push({ week, tasks: weekTasks(week) });
    }
    if (weeks.length) groups.push({ window: w, weeks });
  }
  // Weeks no stage covers but a task falls in (gaps, or a layout without stages).
  const loose: ManualWeek[] = [];
  const lastWeek = Math.max(layout.totalWeeks, ...placed.map((p) => p.last));
  for (let week = 1; week <= lastWeek; week += 1) {
    if (covered.has(week)) continue;
    const tasks = weekTasks(week);
    if (tasks.length) loose.push({ week, tasks });
  }
  if (loose.length) groups.push({ window: null, weeks: loose });
  groups.sort((a, b) => (a.weeks[0]?.week ?? 0) - (b.weeks[0]?.week ?? 0));
  return { mode: "stages", groups, unplaced };
}

interface Placed {
  activity: PlanTemplateActivity;
  first: number;
  last: number;
  perWeek: Map<number, number> | null;
}

function place(activity: PlanTemplateActivity, first: number, maxWeek: number): Placed {
  const duration = Math.max(1, activity.duration_days || 1);
  const last = Math.min(maxWeek, first + Math.floor((duration - 1) / 7));
  let perWeek: Map<number, number> | null = null;
  if (activity.repeat_count && activity.repeat_unit) {
    perWeek = new Map();
    for (const off of occurrenceOffsets(duration, activity.repeat_count, activity.repeat_unit)) {
      const w = first + Math.floor(off / 7);
      if (w <= last) perWeek.set(w, (perWeek.get(w) ?? 0) + 1);
    }
  }
  return { activity, first, last, perWeek };
}

function tasksIn(placed: Placed[], week: number): ManualWeekTask[] {
  return placed
    .filter((p) => p.first <= week && week <= p.last)
    .map((p) => ({
      activity: p.activity,
      firstWeek: p.first,
      lastWeek: p.last,
      timesThisWeek: p.perWeek ? (p.perWeek.get(week) ?? 0) : null,
    }))
    .sort(
      (x, y) =>
        x.firstWeek - y.firstWeek || (x.activity.sort_order ?? 0) - (y.activity.sort_order ?? 0),
    );
}

/** A manual timed from the start date only: Week 1 is the week of its first
 *  task (which may come before planting), every week after it to the last
 *  task, grouped by year (owner's call, 2026-11-20). */
function startWeeks(activities: PlanTemplateActivity[]): ManualWeeks {
  const fromStart = activities.filter((a) => a.anchor === "start");
  const unplaced = activities.filter((a) => a.anchor !== "start");
  const origin = Math.min(...fromStart.map((a) => a.offset_days ?? 0));
  const placed = fromStart.map((a) =>
    place(a, Math.floor(((a.offset_days ?? 0) - origin) / 7) + 1, Number.MAX_SAFE_INTEGER),
  );
  const lastWeek = Math.max(1, ...placed.map((p) => p.last));
  const groups: ManualStageGroup[] = [];
  for (let start = 1; start <= lastWeek; start += YEAR_WEEKS) {
    const weeks: ManualWeek[] = [];
    for (let week = start; week < start + YEAR_WEEKS && week <= lastWeek; week += 1) {
      weeks.push({ week, tasks: tasksIn(placed, week) });
    }
    groups.push({ window: null, year: groups.length + 1, weeks });
  }
  return { mode: "start", groups, unplaced };
}
