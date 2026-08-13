import { useQueries } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
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

import { getWeatherIndexTimeseries, type WeatherIndexCatalogItem } from "@/api/weatherIndices";
import { Skeleton } from "@/components/Skeleton";
import i18n from "@/i18n";
import { makeDateLabelFmt, makeDateTickFmt } from "@/lib/chartFormat";

import { splitForecastSeries } from "../lib/forecastSeries";
import { WeatherIndexChart } from "./WeatherIndexChart";

/**
 * "How has it moved" — the trend half of the weather section.
 *
 * The indices are on incompatible scales (°C, mm, W/m², m/s, %), so this
 * offers two honest views instead of one dual-axis plot, plus a third when
 * the reader has picked a single index off the strip:
 *
 *   units    — small multiples. One compact chart per index, each with its
 *              OWN y-axis in its real unit. Nothing is comparable across
 *              facets, and nothing pretends to be.
 *   compare  — z-scores against each index's day-of-year climatology on ONE
 *              axis, so co-movement (hot AND dry AND high ET together) is
 *              readable. Capped at COMPARE_LIMIT series — see below.
 *   single   — the selected index with its climatology band, which is the
 *              only view that can show the normal it is being judged against.
 *
 * `zscore` is served per point by the timeseries endpoint, so compare needs
 * no extra request.
 */

// Categorical slots, assigned per index code in catalog order and never
// cycled, so a hidden series never repaints the others. There must be at
// least one slot per catalog index: the lookup wraps modulo, so a short
// palette does not fail loudly, it silently repaints a new index in an
// existing one's colour. That is how humidity once landed on temperature's
// blue, and why the count is now eleven — the gap-audit indices
// (leaf_wetness, frost_risk, heat_stress) took the catalog from eight.
//
// The first eight were validated for CVD separation and contrast against each
// mode's own surface (adjacent-pair check). Eleven mutually separable hues do
// not exist, and the three added here are not claimed to be: brown, magenta
// and slate are chosen to sit away from the existing eight rather than to
// pass an all-pairs check.
//
// That is defensible only because of how the palette is actually used. In
// `units` mode each index owns its own chart, so nothing shares an axis; in
// `compare` mode COMPARE_LIMIT caps the view at four series, all directly
// labelled with an unconditional legend. The palette's job here is stable
// identity per index across renders, not simultaneous separability of eleven.
const SERIES_LIGHT = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#4a3aa7",
  "#0f9bb0",
  "#8c5a2b",
  "#b5379c",
  "#5c6b7a",
] as const;
const SERIES_DARK = [
  "#3987e5",
  "#d95926",
  "#199e70",
  "#c98500",
  "#d55181",
  "#008300",
  "#9085e9",
  "#14a2b8",
  "#a9703a",
  "#cc57b4",
  "#8b9aa9",
] as const;

// Eight lines on one axis is past what any categorical palette can keep
// separable — the all-pairs check fails for every 8-hue set worth having,
// including Okabe-Ito. So compare shows the FOUR most anomalous indices and
// says so; the rest stay one click away on the strip. Four is also the
// ceiling for direct-labelling every series.
const COMPARE_LIMIT = 4;

type Mode = "units" | "compare";

interface Props {
  farmId: string;
  /** Catalog in display order; the section owns the query. */
  indices: readonly WeatherIndexCatalogItem[];
  /** Inclusive `from` (YYYY-MM-DD), or undefined for "everything stored". */
  from?: string;
  to: string;
  /** Index code drilled into from the strip, or null for the all-index views. */
  selected: string | null;
  onClearSelection: () => void;
}

interface SeriesPoint {
  date: string;
  value: number | null;
  zscore: number | null;
  isForecast: boolean;
}

// The forward half is drawn thinner and dashed in the SAME hue as its index:
// it is the same quantity, still unmeasured. A separate colour would read as
// a separate series, and a legend entry per index would double the legend.
const FORECAST_DASH = "3 3";

export function WeatherTrendsPanel({
  farmId,
  indices,
  from,
  to,
  selected,
  onClearSelection,
}: Props): ReactNode {
  const { t } = useTranslation("weatherIndices");
  const isAr = i18n.language === "ar";
  const [mode, setMode] = useState<Mode>("units");

  const dateTickFmt = useMemo(() => makeDateTickFmt(i18n.language), []);
  const dateLabelFmt = useMemo(() => makeDateLabelFmt(i18n.language), []);

  const seriesQs = useQueries({
    queries: indices.map((idx) => ({
      queryKey: ["weatherIndices", "trend", farmId, idx.code, from ?? "all", to],
      queryFn: () => getWeatherIndexTimeseries(farmId, idx.code, { from, to }),
      enabled: Boolean(farmId && idx.code) && selected === null,
      staleTime: 60_000,
    })),
  });

  const series = useMemo(() => {
    return indices.map((idx, i) => {
      const points: SeriesPoint[] = (seriesQs[i]?.data?.points ?? []).map((p) => ({
        date: p.date,
        value: toNum(p.value),
        zscore: toNum(p.zscore),
        isForecast: p.is_forecast,
      }));
      // "Latest" and the compare ranking both mean the current reading, so
      // they skip the forecast tail — otherwise the headline number beside
      // each sparkline would be a value five days from now, and compare
      // would rank indices by how anomalous they are predicted to become.
      const observed = points.filter((p) => !p.isForecast);
      const latest = [...observed].reverse().find((p) => p.value !== null)?.value ?? null;
      const latestZ = [...observed].reverse().find((p) => p.zscore !== null)?.zscore ?? null;
      const split = splitForecastSeries(points, (p) => p.value);
      return { idx, points, rows: split.rows, boundary: split.lastObservedDate, latest, latestZ };
    });
  }, [indices, seriesQs]);

  const palette = prefersDark() ? SERIES_DARK : SERIES_LIGHT;
  const colorFor = (code: string): string => {
    const at = indices.findIndex((i) => i.code === code);
    return palette[(at < 0 ? 0 : at) % palette.length];
  };
  const nameOf = (idx: WeatherIndexCatalogItem): string =>
    (isAr ? idx.name_ar : idx.name_en) || idx.name_en;

  // The compare subset: most anomalous first, ties and missing z-scores
  // falling back to catalog order so the choice is deterministic.
  const compared = useMemo(() => {
    return [...series]
      .sort((a, b) => Math.abs(b.latestZ ?? 0) - Math.abs(a.latestZ ?? 0))
      .slice(0, COMPARE_LIMIT)
      .sort((a, b) => a.idx.sort_order - b.idx.sort_order);
  }, [series]);

  // One row per date so recharts can draw every z-score series from a single
  // data prop. Each index contributes TWO keys — `code` up to today and
  // `code__fc` beyond it — so the forward half of every compared line is
  // dashed here for the same reason it is in the units view.
  const compareData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | null>>();
    for (const { idx, points } of compared) {
      const split = splitForecastSeries(points, (p) => p.zscore);
      for (const r of split.rows) {
        const row = byDate.get(r.date) ?? { date: r.date };
        row[idx.code] = r.value;
        row[forecastKey(idx.code)] = r.forecast;
        byDate.set(r.date, row);
      }
    }
    return [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  }, [compared]);

  // Where "now" sits on the shared axis: the latest day any compared index
  // still has an observed z-score for. They are all fed by the same fetch,
  // so in practice this is one date rather than a ragged edge.
  const compareBoundary = useMemo(() => {
    const dates = compared.map((s) => s.boundary).filter((d): d is string => d !== null);
    return dates.length === 0 ? null : dates.reduce((a, b) => (a > b ? a : b));
  }, [compared]);

  const selectedIdx = selected ? indices.find((i) => i.code === selected) : undefined;

  // A drilled-in index owns the whole panel: its own chart carries the
  // climatology band, which neither all-index view can show.
  if (selectedIdx) {
    return (
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-bold uppercase tracking-wide text-ap-primary">
            {t("trends.title")}
          </h3>
          <button
            type="button"
            onClick={onClearSelection}
            className="text-xs font-medium text-ap-accent hover:underline"
          >
            {t("trends.showAll")}
          </button>
        </div>
        <WeatherIndexChart
          farmId={farmId}
          indexCode={selectedIdx.code}
          name={nameOf(selectedIdx)}
          unit={selectedIdx.unit}
        />
      </div>
    );
  }

  const loading = seriesQs.some((q) => q.isLoading);
  const hasAnyData = series.some((s) => s.points.some((p) => p.value !== null));
  const hasAnyForecast = series.some((s) => s.points.some((p) => p.isForecast && p.value !== null));

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wide text-ap-primary">
          {t("trends.title")}
        </h3>
        <div
          role="radiogroup"
          aria-label={t("trends.modeAria")}
          className="flex overflow-hidden rounded-lg border border-ap-line"
        >
          {(["units", "compare"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              className={
                "px-2.5 py-1 text-xs font-semibold " +
                (mode === m
                  ? "bg-ap-primary text-white"
                  : "bg-ap-panel text-ap-ink hover:bg-ap-primary-soft")
              }
            >
              {t(`trends.mode.${m}`)}
            </button>
          ))}
        </div>
      </div>

      <p className="mt-1.5 text-xs text-ap-muted">
        {mode === "units"
          ? t("trends.hintUnits")
          : t("trends.hintCompare", { count: compared.length })}
      </p>
      {/* Stated once for the whole panel: the dashed convention is the same in
          both views, and repeating it per facet would be eight copies. */}
      {hasAnyForecast ? (
        <p className="mt-1 flex items-center gap-1.5 text-[11px] text-ap-muted">
          <svg aria-hidden="true" width="20" height="6" viewBox="0 0 20 6" className="shrink-0">
            <line
              x1="0"
              y1="3"
              x2="20"
              y2="3"
              stroke="currentColor"
              strokeWidth="2"
              strokeDasharray={FORECAST_DASH}
            />
          </svg>
          {t("forecast.legend")}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-3 space-y-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : !hasAnyData ? (
        <p className="py-10 text-center text-sm text-ap-muted">{t("trends.noData")}</p>
      ) : mode === "units" ? (
        <ul className="mt-3 divide-y divide-ap-line/60">
          {series.map(({ idx, points, rows, boundary, latest }) => (
            <li key={idx.code} className="grid grid-cols-[9rem_1fr_5rem] items-center gap-2 py-2">
              <div className="min-w-0">
                <p className="truncate text-xs font-semibold text-ap-ink">{nameOf(idx)}</p>
                <p className="text-[11px] text-ap-muted">{idx.unit}</p>
              </div>
              <div className="h-16">
                {points.length === 0 ? (
                  <p className="text-[11px] text-ap-muted">{t("trends.noData")}</p>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tickFormatter={(v: string) => dateTickFmt.format(new Date(v))}
                        tick={{ fontSize: 10 }}
                        minTickGap={40}
                        stroke="#94a3b8"
                      />
                      {/* Own scale per facet — that is the whole point. */}
                      <YAxis
                        width={40}
                        tick={{ fontSize: 10 }}
                        stroke="#94a3b8"
                        domain={["auto", "auto"]}
                      />
                      <Tooltip<number, string>
                        labelFormatter={(label: string) => dateLabelFmt.format(new Date(label))}
                        formatter={(value: number, key: string): [string, string] => [
                          value === null || Number.isNaN(value)
                            ? "—"
                            : `${value.toFixed(1)} ${idx.unit}`,
                          // The row is named for the index either way; only
                          // the forecast half says so, so a reader hovering
                          // the tail is told what it is.
                          key === "forecast"
                            ? `${nameOf(idx)} · ${t("forecast.short")}`
                            : nameOf(idx),
                        ]}
                      />
                      {boundary === null ? null : (
                        <ReferenceLine x={boundary} stroke="#94a3b8" strokeDasharray="2 2" />
                      )}
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={colorFor(idx.code)}
                        strokeWidth={2}
                        dot={false}
                        connectNulls
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="forecast"
                        stroke={colorFor(idx.code)}
                        strokeWidth={2}
                        strokeDasharray={FORECAST_DASH}
                        dot={false}
                        connectNulls
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
              <p className="text-end text-xs font-semibold tabular-nums text-ap-ink">
                {latest === null ? "—" : latest.toFixed(1)}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-3">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={compareData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v: string) => dateTickFmt.format(new Date(v))}
                  tick={{ fontSize: 11 }}
                  minTickGap={40}
                  stroke="#94a3b8"
                />
                <YAxis
                  width={44}
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                  label={{ value: "σ", position: "insideLeft", fontSize: 11 }}
                />
                {/* Zero = the seasonal normal; the only meaningful datum here. */}
                <ReferenceLine y={0} stroke="#64748b" strokeWidth={1.5} />
                {compareBoundary === null ? null : (
                  <ReferenceLine
                    x={compareBoundary}
                    stroke="#94a3b8"
                    strokeDasharray="2 2"
                    label={{ value: t("forecast.boundary"), fontSize: 10, fill: "#64748b" }}
                  />
                )}
                <Tooltip<number, string>
                  labelFormatter={(label: string) => dateLabelFmt.format(new Date(label))}
                  formatter={(value: number, key: string): [string, string] => {
                    const forecast = isForecastKey(key);
                    const code = forecast ? baseKey(key) : key;
                    const idx = indices.find((i) => i.code === code);
                    const base = idx ? nameOf(idx) : code;
                    const label = forecast ? `${base} · ${t("forecast.short")}` : base;
                    if (value === null || Number.isNaN(value)) return ["—", label];
                    // Signed, because the direction of the departure is the
                    // whole message here.
                    return [`${value > 0 ? "+" : ""}${value.toFixed(2)} σ`, label];
                  }}
                />
                {compared.map(({ idx }) => (
                  <Line
                    key={idx.code}
                    type="monotone"
                    dataKey={idx.code}
                    name={nameOf(idx)}
                    stroke={colorFor(idx.code)}
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                ))}
                {compared.map(({ idx }) => (
                  <Line
                    key={forecastKey(idx.code)}
                    type="monotone"
                    dataKey={forecastKey(idx.code)}
                    name={`${nameOf(idx)} · ${t("forecast.short")}`}
                    stroke={colorFor(idx.code)}
                    strokeWidth={2}
                    strokeDasharray={FORECAST_DASH}
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                    legendType="none"
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          {/* Legend is always present, so identity is never carried by colour
              alone — and it is the only place that names which indices the
              cap left out. */}
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {compared.map(({ idx, latestZ }) => (
              <li key={idx.code} className="flex items-center gap-1.5 text-[11px] text-ap-ink">
                <span
                  aria-hidden="true"
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: colorFor(idx.code) }}
                />
                {nameOf(idx)}
                {latestZ === null ? null : (
                  <span className="tabular-nums text-ap-muted">
                    {latestZ > 0 ? "+" : ""}
                    {latestZ.toFixed(1)}σ
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// The compare view puts every index on one `data` array, so the two halves of
// one index need two distinct keys. Suffixed rather than prefixed so a key
// still sorts and reads next to the code it belongs to.
const FORECAST_SUFFIX = "__fc";
function forecastKey(code: string): string {
  return `${code}${FORECAST_SUFFIX}`;
}
function isForecastKey(key: string): boolean {
  return key.endsWith(FORECAST_SUFFIX);
}
function baseKey(key: string): string {
  return key.slice(0, -FORECAST_SUFFIX.length);
}

function toNum(v: string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function prefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches === true
  );
}
