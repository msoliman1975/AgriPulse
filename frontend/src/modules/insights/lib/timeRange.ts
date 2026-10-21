import type { TimeSpanKey } from "../components/TimeSpanChips";

/**
 * The overview's one time range.
 *
 * Every graph on the Farm health overview used to carry its own control —
 * the vegetation chart had chips plus a From/To pair, the weather section had
 * its own chips, and nothing stopped them showing different windows at the
 * same time. This is the single value they all read.
 *
 * `span` is the selected preset. `from`/`to` are set ONLY for a custom range;
 * when they are set the preset is not selected and `span` is "custom".
 * Dates are calendar days (YYYY-MM-DD) rather than instants, because that is
 * what the reader picked and what the weather endpoints take; the timeseries
 * endpoints want ISO instants, so `toIsoRange` widens a day to its bounds.
 */
export type SpanSelection = TimeSpanKey | "custom";

export interface TimeRange {
  span: SpanSelection;
  /** Inclusive first day, or null for "everything stored". */
  from: string | null;
  /** Inclusive last day, or null for "up to now". */
  to: string | null;
}

const PRESET_DAYS: Record<TimeSpanKey, number | null> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
  // Season stays the 180-day stopgap TimeSpanChips has always used: the
  // backend still exposes no season_start. Kept here, in one place, so
  // wiring real season dates later is a single edit rather than a hunt.
  season: 180,
  all: null,
};

export const DEFAULT_SPAN: TimeSpanKey = "90d";

export function presetRange(span: TimeSpanKey, now: Date = new Date()): TimeRange {
  const days = PRESET_DAYS[span];
  if (days === null) return { span, from: null, to: null };
  const start = new Date(now);
  start.setDate(start.getDate() - days);
  return { span, from: isoDay(start), to: null };
}

export function customRange(from: string, to: string): TimeRange {
  return { span: "custom", from, to };
}

export function isCustom(range: TimeRange): boolean {
  return range.span === "custom";
}

/** ISO instants for the endpoints that take `since`/`until` timestamps. */
export function toIsoRange(range: TimeRange): { since?: string; until?: string } {
  const out: { since?: string; until?: string } = {};
  if (range.from) out.since = `${range.from}T00:00:00Z`;
  if (range.to) out.until = `${range.to}T23:59:59Z`;
  return out;
}

/**
 * How far past today an open-ended weather range reaches, in days.
 *
 * The weather indices are now projected across the provider's forecast
 * horizon (`weather_forecast_hours`, 5 days) as well as observed history, so
 * an upper bound of "tomorrow" would clip off everything that was added — the
 * series would still stop at today and look exactly as it did before.
 *
 * Deliberately one day past the 5-day horizon rather than matched to it: the
 * bound is exclusive, and a horizon the backend widens later should show up
 * without a frontend release. Asking for days the projection does not reach
 * simply returns fewer points.
 */
export const FORECAST_LOOKAHEAD_DAYS = 6;

/** Calendar-day bounds for the endpoints that take `from`/`to` dates. The
 * weather timeseries wants an exclusive upper bound past the last day worth
 * drawing, so an open `to` resolves to the end of the forecast horizon. A
 * custom range is left exactly as the reader set it — if they picked an end
 * date, that is the end date. */
export function toDayRange(
  range: TimeRange,
  now: Date = new Date(),
): { from?: string; to: string } {
  const ahead = new Date(now.getTime() + FORECAST_LOOKAHEAD_DAYS * 86_400_000);
  return {
    ...(range.from ? { from: range.from } : {}),
    to: range.to ?? isoDay(ahead),
  };
}

/**
 * How many days of observed history a stitched past+forecast chart should
 * draw. Clamped, because "all" over a farm with years of weather would put
 * thousands of daily bars beside a 7-day forecast and read as a solid block.
 */
export function pastDays(range: TimeRange, max = 90, now: Date = new Date()): number {
  if (!range.from) return max;
  const from = new Date(`${range.from}T00:00:00Z`);
  // Both ends truncated to day boundaries before subtracting: `now` carries a
  // time of day, and a half-day remainder used to round a 7-day preset up to
  // 8 — so the outlook asked for one more day of history than the range it
  // was handed.
  const end = new Date(`${(range.to ?? isoDay(now))}T00:00:00Z`);
  const days = Math.round((end.getTime() - from.getTime()) / 86_400_000);
  if (!Number.isFinite(days) || days <= 0) return 1;
  return Math.min(days, max);
}

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}
