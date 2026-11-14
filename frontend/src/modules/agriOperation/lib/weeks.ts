// Week arithmetic for operation manuals: where each stage sits in the season,
// and which week a manual activity falls in. Pure.
//
// Perennial crops (calendar_doy stages) run a 52-week cycle that starts on
// the first stage's start date. Annual crops (days_from_planting stages)
// count weeks from planting, and the cycle ends with the last stage.

import type { PhenologyStage } from "@/api/agriOperation";
import type { PlanTemplateActivity } from "@/api/planTemplates";

export const PERENNIAL_WEEKS = 52;

export interface StageWindow {
  code: string;
  stage: PhenologyStage;
  startWeek: number;
  endWeek: number;
}

export interface SeasonLayout {
  perennial: boolean;
  totalWeeks: number;
  windows: StageWindow[];
}

/** Day of a fixed non-leap year (1-365) for "MM-DD". */
export function dayOfYear(mmdd: string): number {
  const [m, d] = mmdd.split("-").map(Number);
  const days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  return (days[(m ?? 1) - 1] ?? 0) + (d ?? 1);
}

function weekFromDays(days: number): number {
  return Math.floor(days / 7) + 1;
}

/** Stage windows in weeks. Stages keep the order the catalog gives them. */
export function seasonLayout(stages: PhenologyStage[], perennial: boolean): SeasonLayout {
  const windows: StageWindow[] = [];
  if (perennial) {
    const doyStages = stages.filter((s) => s.advance.mode === "calendar_doy");
    const first = doyStages[0];
    if (!first) return { perennial, totalWeeks: PERENNIAL_WEEKS, windows };
    const cycleStart = dayOfYear(String(first.advance.start_doy));
    const offset = (mmdd: string): number => (dayOfYear(mmdd) - cycleStart + 365) % 365;
    doyStages.forEach((s, i) => {
      const startDays = offset(String(s.advance.start_doy));
      const next = doyStages[i + 1];
      const endDays =
        typeof s.advance.end_doy === "string"
          ? offset(s.advance.end_doy)
          : next
            ? offset(String(next.advance.start_doy)) - 1
            : 364;
      windows.push({
        code: s.code,
        stage: s,
        startWeek: Math.min(PERENNIAL_WEEKS, weekFromDays(startDays)),
        endWeek: Math.min(PERENNIAL_WEEKS, weekFromDays(Math.max(endDays, startDays))),
      });
    });
    return { perennial, totalWeeks: PERENNIAL_WEEKS, windows: noOverlap(windows) };
  }
  const dayStages = stages.filter((s) => s.advance.mode === "days_from_planting");
  dayStages.forEach((s, i) => {
    const start = Number(s.advance.start_day);
    const next = dayStages[i + 1];
    const end =
      typeof s.advance.end_day === "number"
        ? s.advance.end_day
        : next
          ? Number(next.advance.start_day) - 1
          : start + 27;
    windows.push({
      code: s.code,
      stage: s,
      startWeek: weekFromDays(Math.max(0, start)),
      endWeek: weekFromDays(Math.max(start, end)),
    });
  });
  const totalWeeks = windows.reduce((m, w) => Math.max(m, w.endWeek), 1);
  return { perennial, totalWeeks, windows: noOverlap(windows) };
}

/** A stage ends the week before the next one starts, so each week belongs to
 *  one stage on the ribbon. */
function noOverlap(windows: StageWindow[]): StageWindow[] {
  return windows.map((w, i) => {
    const next = windows[i + 1];
    if (!next || next.startWeek <= w.startWeek) return w;
    return { ...w, endWeek: Math.min(w.endWeek, next.startWeek - 1) };
  });
}

/**
 * The week an activity falls in, or null when it has no fixed week (a
 * perennial activity anchored to the block's own start date, or a milestone
 * the layout can't place).
 */
export function activityWeek(
  activity: Pick<PlanTemplateActivity, "anchor" | "offset_days"> & {
    stage_code?: string | null;
  },
  layout: SeasonLayout,
): number | null {
  const offset = activity.offset_days ?? 0;
  if (activity.anchor === "stage") {
    const w = layout.windows.find((x) => x.code === activity.stage_code);
    if (!w) return null;
    const week = w.startWeek + Math.floor(offset / 7);
    return Math.max(1, Math.min(layout.totalWeeks, week));
  }
  if (activity.anchor === "start" && !layout.perennial) {
    return Math.max(1, weekFromDays(offset));
  }
  return null;
}

/** Evidence tags like "[EG-FAO]" in older notes; the tier is shown on its own. */
export function stripEvidenceTags(notes: string | null | undefined): string {
  return (notes ?? "")
    .replace(/\s*\[(EG-FAO|EG|GENERIC)[^\]]*\](\/\[(EG-FAO|EG|GENERIC)[^\]]*\])?/g, "")
    .trim();
}
