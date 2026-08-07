import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  getFarmAnnotations,
  getFarmIndexTimeseries,
  type AnnotationSeverity,
  type FarmIndexTimeseriesPoint,
} from "@/api/insights";
import { Card } from "@/components/Card";
import { Skeleton } from "@/components/Skeleton";
import { makeDateLabelFmt, makeDateTickFmt } from "@/lib/chartFormat";

import { toIsoRange, type TimeRange } from "../lib/timeRange";
import { IndexPicker, SUPPORTED_INDICES, type IndexCode } from "./IndexPicker";

interface Props {
  farmId: string;
  /** The overview's shared time range; the page owns it (see TimeRangeBar). */
  range: TimeRange;
  /** Block ids to draw, or null for every block the farm returns. */
  blockIds?: readonly string[] | null;
  /** Optional initial index; otherwise restored from localStorage. */
  indexCode?: IndexCode;
}

const LS_KEY = "insights.farmTrend.prefs";

interface StoredPrefs {
  index: IndexCode;
}

function _loadPrefs(farmId: string): StoredPrefs | null {
  try {
    const raw = window.localStorage.getItem(`${LS_KEY}.${farmId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredPrefs;
    if (!SUPPORTED_INDICES.includes(parsed.index)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function _savePrefs(farmId: string, prefs: StoredPrefs): void {
  try {
    window.localStorage.setItem(`${LS_KEY}.${farmId}`, JSON.stringify(prefs));
  } catch {
    /* localStorage may be disabled; selection still applies for the session */
  }
}

/**
 * Multi-block NDVI (or other index) trend chart for the Farm health
 * overview. Replaces the V1 TrendChartCard's "first block only"
 * stopgap with the farm-rollup endpoint (B.2).
 *
 * Layout: one Line per block, colour cycle (10-stop d3-category palette).
 * The y-axis is auto-scaled — NDVI ranges [-1, 1] but most farm
 * conditions sit in [0.2, 0.9]; letting recharts pick keeps the lines
 * readable without forcing the viewer to stare at half-empty axis.
 *
 * The legend is selectable: a farm with a dozen blocks draws a dozen lines,
 * which is past what any categorical palette separates, so the reader can
 * mute the ones they are not asking about. Colour is pinned to the block's
 * position in the FULL series list, never to its position among the visible
 * ones — hiding a block must not repaint the others.
 *
 * The time range belongs to the page, not to this card.
 */
export function FarmTrendChart({
  farmId,
  range,
  blockIds = null,
  indexCode: indexCodeProp,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("insights");
  const dateTickFmt = useMemo(() => makeDateTickFmt(i18n.language), [i18n.language]);
  const dateLabelFmt = useMemo(() => makeDateLabelFmt(i18n.language), [i18n.language]);

  const stored = useMemo(() => _loadPrefs(farmId), [farmId]);
  const [indexCode, setIndexCode] = useState<IndexCode>(indexCodeProp ?? stored?.index ?? "ndvi");
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());

  // Re-anchor state if the active farm changes (different localStorage scope,
  // and another farm's block names mean nothing here).
  useEffect(() => {
    const fresh = _loadPrefs(farmId);
    if (fresh) setIndexCode(fresh.index);
    setHidden(new Set());
  }, [farmId]);

  useEffect(() => {
    _savePrefs(farmId, { index: indexCode });
  }, [farmId, indexCode]);

  const apiRange = useMemo(() => toIsoRange(range), [range]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["insights", "trend", farmId, indexCode, apiRange] as const,
    queryFn: () =>
      getFarmIndexTimeseries(farmId, {
        index_code: indexCode,
        ...apiRange,
      }),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
  // B.3 annotations — independent query so a slow alerts join can't
  // delay the chart's first paint. The trend chart renders without
  // annotations if this fails or is still loading.
  const annotationsQ = useQuery({
    queryKey: ["insights", "annotations", farmId] as const,
    queryFn: () => getFarmAnnotations(farmId),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });

  // Reshape: flat [{time, block_id, block_name, value}] → keyed
  // [{time, <blockName1>: value, <blockName2>: value, ...}] so
  // recharts can render one Line per block from one chartData prop.
  // Block names are used as dataKey because they're stable per query
  // result; if two blocks share a name (rare; codes are unique) the
  // later wins — acceptable for V1 visual exploration.
  // Crop filtering is applied to the points before reshaping, so a filtered
  // block leaves the palette entirely rather than keeping a dead legend slot.
  const points = useMemo(() => {
    const all = data?.points ?? [];
    if (!blockIds) return all;
    const keep = new Set(blockIds);
    return all.filter((p) => keep.has(p.block_id));
  }, [data?.points, blockIds]);

  const { chartData, blockNames } = useMemo(() => _reshapeForRecharts(points), [points]);

  const visibleCount = blockNames.filter((n) => !hidden.has(n)).length;
  // Muting every block used to be blocked, because an empty plot under a full
  // legend reads as "no data" — a different and more alarming message. The
  // guard is gone now that the plot says so in words (`trend.allHidden`)
  // instead: with a bulk "hide all" control, a rule that lets you hide three
  // of four blocks but silently ignores the fourth click reads as a bug.
  const allHidden = blockNames.length > 0 && visibleCount === 0;
  const toggle = (name: string): void =>
    setHidden((cur) => {
      const next = new Set(cur);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  return (
    <Card noPadding className="p-4" aria-labelledby="farm-trend-heading">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2
          id="farm-trend-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          {t("trend.title")}
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <IndexPicker value={indexCode} onChange={setIndexCode} />
        </div>
      </header>

      <p className="mt-1 text-xs text-ap-muted">{t(`trend.indexDesc.${indexCode}`)}</p>

      <div className="mt-3 min-h-[260px]">
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : isError ? (
          <p className="py-12 text-center text-sm text-ap-crit">{t("trend.loadFailed")}</p>
        ) : chartData.length === 0 ? (
          <p className="py-12 text-center text-sm text-ap-muted">{t("trend.empty")}</p>
        ) : allHidden ? (
          // Distinct from `trend.empty`: the farm HAS observations, the reader
          // just muted them all. Saying so is what makes hiding everything safe.
          <div className="py-12 text-center">
            <p className="text-sm text-ap-muted">{t("trend.allHidden")}</p>
            <button
              type="button"
              onClick={() => setHidden(new Set())}
              className="mt-1 text-xs font-medium text-ap-primary hover:underline"
            >
              {t("trend.showAllBlocks")}
            </button>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" />
              <XAxis
                dataKey="time"
                tickFormatter={(v: string) => dateTickFmt.format(new Date(v))}
                fontSize={11}
              />
              <YAxis fontSize={11} />
              <Tooltip
                labelFormatter={(label: string) => dateLabelFmt.format(new Date(label))}
                formatter={(value: number) => value.toFixed(3)}
              />
              {/* No <Legend>: the selectable one below the plot replaces it,
                  so identity and visibility live in the same control. */}
              {blockNames.map((name, i) => (
                <Line
                  key={name}
                  type="monotone"
                  dataKey={name}
                  stroke={_lineColor(i)}
                  strokeWidth={1.75}
                  dot={false}
                  connectNulls
                  hide={hidden.has(name)}
                />
              ))}
              {/* B.3: alert-opened markers. ReferenceLine stroke
                  carries the severity colour; recharts doesn't
                  expose per-line tooltips so the label rides in
                  the line's `label` prop. */}
              {(annotationsQ.data?.annotations ?? []).map((a) => (
                <ReferenceLine
                  key={`${a.time}-${a.block_id ?? "farm"}`}
                  x={a.time}
                  stroke={_annotationColor(a.severity)}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  ifOverflow="hidden"
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {chartData.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <ul
            className="flex flex-wrap gap-x-3 gap-y-1.5"
            role="group"
            aria-label={t("trend.legendLabel")}
          >
            {blockNames.map((name, i) => {
              const on = !hidden.has(name);
              return (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => toggle(name)}
                    aria-pressed={on}
                    className={
                      "flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] transition-colors " +
                      (on
                        ? "border-ap-line bg-ap-panel text-ap-ink"
                        : "border-ap-line/60 bg-transparent text-ap-muted line-through")
                    }
                  >
                    <span
                      aria-hidden="true"
                      className="inline-block h-2.5 w-2.5 rounded-sm"
                      // Muted swatches keep the hue so the reader can still
                      // tell which line comes back when they re-enable it.
                      style={{ backgroundColor: _lineColor(i), opacity: on ? 1 : 0.35 }}
                    />
                    {name}
                  </button>
                </li>
              );
            })}
          </ul>
          {/* Both controls are always mounted, each disabled when it would be
              a no-op. Showing/hiding them by state moves the legend's other
              entries under the reader's cursor mid-click. */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setHidden(new Set())}
              disabled={hidden.size === 0}
              className="text-[11px] font-medium text-ap-primary hover:underline disabled:cursor-default disabled:text-ap-muted/50 disabled:no-underline disabled:hover:no-underline"
            >
              {t("trend.showAllBlocks")}
            </button>
            <span aria-hidden="true" className="text-[11px] text-ap-line">
              ·
            </span>
            <button
              type="button"
              onClick={() => setHidden(new Set(blockNames))}
              disabled={allHidden}
              className="text-[11px] font-medium text-ap-primary hover:underline disabled:cursor-default disabled:text-ap-muted/50 disabled:no-underline disabled:hover:no-underline"
            >
              {t("trend.hideAllBlocks")}
            </button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

// d3-category10 — distinct enough at 10 blocks; >10 wraps. Real
// farms rarely exceed 10 active blocks; B.3 can add a smarter
// hashing scheme if needed.
const PALETTE = [
  "#1f77b4",
  "#ff7f0e",
  "#2ca02c",
  "#d62728",
  "#9467bd",
  "#8c564b",
  "#e377c2",
  "#7f7f7f",
  "#bcbd22",
  "#17becf",
];

function _lineColor(index: number): string {
  return PALETTE[index % PALETTE.length];
}

// Annotation colour palette — matches the HEALTH_CHIP scheme in
// BlockHealthScorecard so the operator's eye reads the same colour
// language across both surfaces.
function _annotationColor(severity: AnnotationSeverity): string {
  if (severity === "critical") return "#A32D2D";
  if (severity === "warning") return "#854F0B";
  return "#9C9C9C";
}

interface ReshapedRow {
  time: string;
  [blockName: string]: string | number;
}

export function _reshapeForRecharts(points: readonly FarmIndexTimeseriesPoint[]): {
  chartData: ReshapedRow[];
  blockNames: string[];
} {
  const byTime = new Map<string, ReshapedRow>();
  const names = new Set<string>();
  for (const p of points) {
    names.add(p.block_name);
    const existing = byTime.get(p.time);
    const value = Number(p.value);
    if (existing) {
      existing[p.block_name] = value;
    } else {
      byTime.set(p.time, { time: p.time, [p.block_name]: value });
    }
  }
  const chartData = Array.from(byTime.values()).sort((a, b) =>
    a.time < b.time ? -1 : a.time > b.time ? 1 : 0,
  );
  return { chartData, blockNames: Array.from(names) };
}
