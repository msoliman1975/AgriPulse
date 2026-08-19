// One block-level index series, shared by every surface in the Block Dock
// that renders a reading.
//
// Why this exists: the dock used to take three series from the block-detail
// bundle (`loadUnitDetail` fetches ndvi/ndre/ndwi and nothing else) and file
// the other ten indices as "grid only" — shown, disabled, no number. That was
// never a property of the API. `/blocks/{id}/indices/{code}/timeseries` reads
// the daily continuous aggregate filtered by `index_code`, with no
// allowed-list, and the ingest task writes one `block_index_aggregates` row
// per index it computed from the scene. Checked on prod 2026-08-19:
// `block_index_daily` carried all thirteen codes for the same blocks, 1435
// rows each.
//
// So every tile fetches its own series, and the tab charts whichever tile you
// pick. The queries are keyed on (block, code, from, to) and shared through
// react-query, so the tab's chart and its card read ONE request, and the
// title bar's featured value joins the same one when it is looking at the
// same index over the same window.
import { keepPreviousData } from "@tanstack/react-query";

import { getTimeseries, type AnyIndexCode, type IndexTimeseriesResponse } from "@/api/indices";

import type { IndexSeries } from "../map/types";

export interface SeriesPoint {
  time: string;
  value: number;
}

/** 30 days is what the block-detail bundle loads, so the dock's default range
 *  reuses that request rather than opening a second one for the same numbers. */
export const DEFAULT_RANGE_DAYS = 30;

export const DOCK_SERIES_STALE_MS = 60_000;

export function dockSeriesKey(
  blockId: string,
  code: AnyIndexCode,
  from: string,
  to: string,
): readonly unknown[] {
  return ["labs/mapnext/dockSeries", blockId, code, from, to] as const;
}

/** Query options for one index over one window. Shared verbatim by the cards,
 *  the chart and the title bar so react-query dedupes them into one request. */
export function dockSeriesOptions(
  blockId: string,
  code: AnyIndexCode,
  from: string,
  to: string,
): {
  queryKey: readonly unknown[];
  queryFn: () => Promise<IndexTimeseriesResponse>;
  staleTime: number;
  placeholderData: typeof keepPreviousData;
} {
  return {
    queryKey: dockSeriesKey(blockId, code, from, to),
    queryFn: () => getTimeseries(blockId, code, { granularity: "daily", from, to }),
    staleTime: DOCK_SERIES_STALE_MS,
    // Dragging the date range re-fetches thirteen-odd series; without this the
    // whole tab blanks to skeletons on every keystroke of the date input.
    placeholderData: keepPreviousData,
  };
}

/** API points → plottable points. The API serves NUMERIC as a string, and a
 *  scene with no clear pixels serves `mean: null` — both drop out here rather
 *  than reaching a chart as NaN. */
export function toPoints(res: IndexTimeseriesResponse | undefined): SeriesPoint[] {
  const raw = res?.points ?? [];
  return raw
    .map((p) => ({ time: p.time, value: p.mean == null ? Number.NaN : Number(p.mean) }))
    .filter((p): p is SeriesPoint => Number.isFinite(p.value));
}

export function latestValue(points: SeriesPoint[]): number | null {
  return points.length ? points[points.length - 1].value : null;
}

/** The reading `days` before the last one, or the oldest point in the window
 *  when the window is shorter than that. Null with fewer than two points. */
function earlierValue(points: SeriesPoint[], days: number): number | null {
  if (points.length < 2) return null;
  const cutoff = Date.parse(points[points.length - 1].time) - days * 86_400_000;
  const before = points.filter((p) => Date.parse(p.time) <= cutoff);
  return before.length ? before[before.length - 1].value : points[0].value;
}

/** Change in the index's own units — 0.03 of NDVI, 1.4 °C of LST. */
export function deltaOver(points: SeriesPoint[], days: number): number | null {
  const now = latestValue(points);
  const then = earlierValue(points, days);
  return now == null || then == null ? null : now - then;
}

/** Change as a percentage of the earlier reading. Undefined against a zero
 *  baseline, and meaningless for an index that crosses zero — which is why
 *  the cards use `deltaOver` and only the headline figure uses this. */
export function deltaPctOver(points: SeriesPoint[], days: number): number | null {
  const now = latestValue(points);
  const then = earlierValue(points, days);
  if (now == null || then == null || then === 0) return null;
  return ((now - then) / Math.abs(then)) * 100;
}

/** Points in the shape the block-detail bundle publishes, so a surface can
 *  take EITHER without branching: `loadUnitDetail` still fetches ndvi/ndre/ndwi
 *  with the rest of the block, and the other ten arrive through this. */
export function seriesFromPoints(points: SeriesPoint[]): IndexSeries {
  return {
    current: latestValue(points),
    trend_7d_delta: deltaOver(points, 7),
    series_30d: points.map((p) => ({ time: p.time, value: p.value })),
  };
}
