import { useQueries, useQuery } from "@tanstack/react-query";
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

import {
  getWeatherIndexCatalog,
  getWeatherIndexTimeseries,
  type WeatherIndexCatalogItem,
} from "@/api/weatherIndices";
import { Skeleton } from "@/components/Skeleton";
import i18n from "@/i18n";
import { makeDateLabelFmt, makeDateTickFmt } from "@/lib/chartFormat";

import { TimeSpanChips, timeSpanToSince, type TimeSpanKey } from "./TimeSpanChips";

/**
 * Weather-index trends over the same spans as the vegetation trend chart.
 *
 * The seven indices are on incompatible scales (°C, mm, W/m², m/s), so this
 * deliberately offers two honest views instead of one dual-axis plot — two
 * y-scales on one plot makes crossings an artifact of axis placement:
 *
 *   "units"   — small multiples. One compact chart per index, each with its
 *               OWN y-axis in its real unit. Nothing is comparable across
 *               facets, and nothing pretends to be.
 *   "anomaly" — every index on ONE axis as a z-score against its day-of-year
 *               climatology. Unitless and centred on zero, so co-movement
 *               (hot AND dry AND high ET together) is finally readable.
 *
 * `zscore` is served per point by the timeseries endpoint, so the anomaly
 * view needs no extra request.
 */

// Categorical slots 1-7 in fixed order — assigned per index code and never
// cycled, so a hidden series never repaints the others. Validated for CVD
// separation and contrast in both modes; the light surface trips a contrast
// WARN on three slots, which is why every series is also directly labelled.
const SERIES_LIGHT = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#4a3aa7",
] as const;
const SERIES_DARK = [
  "#3987e5",
  "#d95926",
  "#199e70",
  "#c98500",
  "#d55181",
  "#008300",
  "#9085e9",
] as const;

type Mode = "units" | "anomaly";

interface Props {
  farmId: string;
}

interface SeriesPoint {
  date: string;
  value: number | null;
  zscore: number | null;
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

export function WeatherTrendsCard({ farmId }: Props): ReactNode {
  const { t } = useTranslation("weatherIndices");
  const isAr = i18n.language === "ar";
  const [span, setSpan] = useState<TimeSpanKey>("90d");
  const [mode, setMode] = useState<Mode>("units");

  const dateTickFmt = useMemo(() => makeDateTickFmt(i18n.language), []);
  const dateLabelFmt = useMemo(() => makeDateLabelFmt(i18n.language), []);

  const range = useMemo(() => {
    const since = timeSpanToSince(span);
    return {
      // "all" has no lower bound; the endpoint treats a missing `from` as
      // "everything stored".
      from: since ? since.slice(0, 10) : undefined,
      to: new Date(Date.now() + 86_400_000).toISOString().slice(0, 10),
    };
  }, [span]);

  const catalogQ = useQuery({
    queryKey: ["weatherIndices", "catalog"] as const,
    queryFn: getWeatherIndexCatalog,
    staleTime: 5 * 60_000,
  });

  const indices = useMemo<WeatherIndexCatalogItem[]>(
    () => [...(catalogQ.data ?? [])].sort((a, b) => a.sort_order - b.sort_order),
    [catalogQ.data],
  );

  const seriesQs = useQueries({
    queries: indices.map((idx) => ({
      queryKey: ["weatherIndices", "trend", farmId, idx.code, range.from ?? "all", range.to],
      queryFn: () => getWeatherIndexTimeseries(farmId, idx.code, range),
      enabled: Boolean(farmId && idx.code),
      staleTime: 60_000,
    })),
  });

  const series = useMemo(() => {
    return indices.map((idx, i) => {
      const points: SeriesPoint[] = (seriesQs[i]?.data?.points ?? []).map((p) => ({
        date: p.date,
        value: toNum(p.value),
        zscore: toNum(p.zscore),
      }));
      const latest = [...points].reverse().find((p) => p.value !== null)?.value ?? null;
      return { idx, points, latest };
    });
  }, [indices, seriesQs]);

  const palette = prefersDark() ? SERIES_DARK : SERIES_LIGHT;
  const colorFor = (code: string): string => {
    const at = indices.findIndex((i) => i.code === code);
    return palette[(at < 0 ? 0 : at) % palette.length];
  };
  const nameOf = (idx: WeatherIndexCatalogItem): string =>
    (isAr ? idx.name_ar : idx.name_en) || idx.name_en;

  // One row per date so recharts can draw every z-score series from a
  // single data prop.
  const anomalyData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | null>>();
    for (const { idx, points } of series) {
      for (const p of points) {
        const row = byDate.get(p.date) ?? { date: p.date };
        row[idx.code] = p.zscore;
        byDate.set(p.date, row);
      }
    }
    return [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  }, [series]);

  const loading = catalogQ.isLoading || seriesQs.some((q) => q.isLoading);
  const hasAnyData = series.some((s) => s.points.some((p) => p.value !== null));

  return (
    <section
      aria-labelledby="weather-trends-heading"
      className="rounded-xl border border-ap-line bg-ap-panel p-4"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2
          id="weather-trends-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          {t("trends.title")}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <TimeSpanChips
            value={span}
            onChange={setSpan}
            i18nPrefix="trend.timespan"
            ariaLabel={t("trends.spanAria")}
          />
          <div
            role="radiogroup"
            aria-label={t("trends.modeAria")}
            className="flex overflow-hidden rounded-lg border border-ap-line"
          >
            {(["units", "anomaly"] as const).map((m) => (
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
      </header>

      <p className="mt-2 text-xs text-ap-muted">
        {mode === "units" ? t("trends.hintUnits") : t("trends.hintAnomaly")}
      </p>

      {loading ? (
        <div className="mt-3 space-y-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : !hasAnyData ? (
        <p className="py-12 text-center text-sm text-ap-muted">{t("trends.noData")}</p>
      ) : mode === "units" ? (
        <ul className="mt-3 divide-y divide-ap-line/60">
          {series.map(({ idx, points, latest }) => (
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
                    <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
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
                        formatter={(value: number): [string, string] => [
                          value === null || Number.isNaN(value)
                            ? "—"
                            : `${value.toFixed(1)} ${idx.unit}`,
                          nameOf(idx),
                        ]}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={colorFor(idx.code)}
                        strokeWidth={2}
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
              <LineChart data={anomalyData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
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
                <Tooltip<number, string>
                  labelFormatter={(label: string) => dateLabelFmt.format(new Date(label))}
                  formatter={(value: number, key: string): [string, string] => {
                    const idx = indices.find((i) => i.code === key);
                    const label = idx ? nameOf(idx) : key;
                    if (value === null || Number.isNaN(value)) return ["—", label];
                    // Signed, because the direction of the departure is the
                    // whole message here.
                    return [`${value > 0 ? "+" : ""}${value.toFixed(2)} σ`, label];
                  }}
                />
                {indices.map((idx) => (
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
              </LineChart>
            </ResponsiveContainer>
          </div>
          {/* Legend is always present for >= 2 series, so identity is never
              carried by colour alone. */}
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {indices.map((idx) => (
              <li key={idx.code} className="flex items-center gap-1.5 text-[11px] text-ap-ink">
                <span
                  aria-hidden="true"
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: colorFor(idx.code) }}
                />
                {nameOf(idx)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
