/**
 * Pure helpers for the holdings list and the Details tab (investor app v2,
 * PR 7): the portfolio stats, stage colours and the stage ribbon.
 */
import type { Activity, Holding, Stage } from "@/api/client";

/** Growth-stage colours, in season order; a stage takes its index's colour. */
export const STAGE_COLORS = [
  "#8fb98a",
  "#e7b9d8",
  "#f2c14e",
  "#7fb069",
  "#e0873b",
  "#6c9a8b",
  "#a3b86c",
] as const;
export const NO_STAGE_COLOR = "#9aa59a";

/** The colour of a stage code among a holding's stages. */
export function stageColor(stages: Stage[] | undefined, code: string | null | undefined): string {
  if (!code || !stages) return NO_STAGE_COLOR;
  const i = stages.findIndex((s) => s.code === code);
  return i < 0 ? NO_STAGE_COLOR : STAGE_COLORS[i % STAGE_COLORS.length];
}

export interface RibbonSegment {
  code: string;
  name_en: string | null;
  name_ar: string | null;
  color: string;
  /** Share of the ribbon, 0-100. */
  widthPct: number;
}

export interface Ribbon {
  segments: RibbonSegment[];
  /**
   * Where today sits, 0-100 from the reading start (left in English, right
   * in Arabic: drawn with inset-inline-start). Null when it cannot be placed.
   */
  markerPct: number | null;
}

const DAY_MS = 86_400_000;
const days = (iso: string): number => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / DAY_MS;

/**
 * The season's stages as a ribbon. When every stage has expected dates the
 * widths follow them and today is placed by date; otherwise every stage gets
 * the same width (GDD or manual stages cannot be dated) and the marker sits
 * in the middle of the current stage.
 */
export function stageRibbon(
  stages: Stage[] | undefined,
  currentCode: string | null | undefined,
  today: string,
): Ribbon {
  if (!stages || stages.length === 0) return { segments: [], markerPct: null };
  const dated = stages.every(
    (s) => s.expected_start && s.expected_end && days(s.expected_end) >= days(s.expected_start),
  );
  const spans = stages.map((s) =>
    dated ? days(s.expected_end as string) - days(s.expected_start as string) + 1 : 1,
  );
  const total = spans.reduce((a, b) => a + b, 0);
  const segments = stages.map((s, i) => ({
    code: s.code,
    name_en: s.name_en,
    name_ar: s.name_ar,
    color: STAGE_COLORS[i % STAGE_COLORS.length],
    widthPct: (spans[i] / total) * 100,
  }));

  let markerPct: number | null = null;
  if (dated) {
    const start = days(stages[0].expected_start as string);
    const end = days(stages[stages.length - 1].expected_end as string) + 1;
    const now = days(today) + 0.5;
    if (now >= start && now <= end) markerPct = ((now - start) / (end - start)) * 100;
  }
  if (markerPct === null && currentCode) {
    const i = stages.findIndex((s) => s.code === currentCode);
    if (i >= 0) {
      const before = segments.slice(0, i).reduce((a, s) => a + s.widthPct, 0);
      markerPct = before + segments[i].widthPct / 2;
    }
  }
  return { segments, markerPct };
}

export interface PortfolioStats {
  currentCount: number;
  currentAreaM2: number;
}

export function portfolioStats(holdings: Holding[]): PortfolioStats {
  const current = holdings.filter((h) => h.period === "current");
  return {
    currentCount: current.length,
    currentAreaM2: current.reduce((a, h) => a + Number(h.area_m2), 0),
  };
}

/**
 * Decision D6: activities completed this season across current holdings.
 * Two holdings on one block share its activities, so each counts once.
 */
export function completedActivities(perHolding: Activity[][]): number {
  const done = new Set<string>();
  for (const list of perHolding) {
    for (const a of list) if (a.status === "completed") done.add(a.id);
  }
  return done.size;
}

/** Up to two initials, for the header avatar. */
export function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => [...w][0])
    .join("")
    .toUpperCase();
}

/** Today as YYYY-MM-DD in the phone's own calendar. */
export function todayIso(now = new Date()): string {
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${m}-${d}`;
}
