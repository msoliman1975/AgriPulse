import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getDerivedDaily, getForecast } from "@/api/weather";
import { Skeleton } from "@/components/Skeleton";
import { makeDateLabelFmt, makeDateTickFmt } from "@/lib/chartFormat";

interface Props {
  blockId: string;
  /** Days of observed history to stitch in front of the forecast. */
  pastDays: number;
  /** Forecast horizon in days; capped at 10 by the API. */
  forecastDays?: number;
}

interface CombinedPoint {
  date: string;
  temp_high: number | null;
  temp_low: number | null;
  precip: number | null;
}

/**
 * Observed weather stitched to the forecast, with a rule at today.
 *
 * - Past slice: `/blocks/{id}/weather/derived` (temp_min/max, precip).
 * - Future slice: `/blocks/{id}/weather/forecast` (high_c/low_c, precip_mm_total).
 *
 * Temperature and precipitation are the one pairing that earns two scales
 * here — they are the conventional weather pair, read together, and the bars
 * sit under the lines rather than crossing them. Every other cross-index
 * comparison in this section goes through z-scores instead.
 *
 * The block id resolves to the farm centroid server-side; "first block" is
 * the existing farm-level contract (see WeatherSection).
 */
export function WeatherOutlookPanel({ blockId, pastDays, forecastDays = 7 }: Props): ReactNode {
  const { t, i18n } = useTranslation("insights");
  const dateTickFmt = useMemo(() => makeDateTickFmt(i18n.language), [i18n.language]);
  const dateLabelFmt = useMemo(() => makeDateLabelFmt(i18n.language), [i18n.language]);

  const { since, until } = useMemo(() => {
    const now = new Date();
    const start = new Date(now);
    start.setDate(start.getDate() - pastDays);
    return {
      since: start.toISOString().slice(0, 10), // YYYY-MM-DD
      until: now.toISOString().slice(0, 10),
    };
  }, [pastDays]);

  const derivedQ = useQuery({
    queryKey: ["weather", "derived", blockId, since, until] as const,
    queryFn: () => getDerivedDaily(blockId, { since, until }),
    enabled: Boolean(blockId),
    staleTime: 60_000,
  });

  const forecastQ = useQuery({
    queryKey: ["weather", "forecast", blockId, forecastDays] as const,
    queryFn: () => getForecast(blockId, { horizon_days: forecastDays }),
    enabled: Boolean(blockId),
    staleTime: 60_000,
  });

  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const data = useMemo<CombinedPoint[]>(() => {
    const past: CombinedPoint[] = (derivedQ.data ?? []).map((row) => ({
      date: row.date,
      temp_high: toNum(row.temp_max_c),
      temp_low: toNum(row.temp_min_c),
      precip: toNum(row.precip_mm_daily),
    }));
    const future: CombinedPoint[] = (forecastQ.data?.days ?? []).map((d) => ({
      date: d.date,
      temp_high: toNum(d.high_c),
      temp_low: toNum(d.low_c),
      precip: toNum(d.precip_mm_total),
    }));
    // De-dupe: the forecast usually includes "today" as day 0; prefer the
    // observed value when both exist.
    const seen = new Set(past.map((p) => p.date));
    const stitched = [...past, ...future.filter((f) => !seen.has(f.date))];
    return stitched.sort((a, b) => (a.date < b.date ? -1 : 1));
  }, [derivedQ.data, forecastQ.data]);

  const loading = derivedQ.isLoading || forecastQ.isLoading;
  const hasError = derivedQ.isError && forecastQ.isError;
  const isEmpty = !loading && data.length === 0;

  return (
    <div>
      <h3 className="text-xs font-bold uppercase tracking-wide text-ap-primary">
        {t("weather.title")}
      </h3>
      <div className="mt-2 min-h-[280px]">
        {loading ? (
          <Skeleton className="h-72 w-full" />
        ) : hasError ? (
          <p className="py-12 text-center text-sm text-ap-crit">{t("weather.loadFailed")}</p>
        ) : isEmpty ? (
          <p className="py-12 text-center text-sm text-ap-muted">{t("weather.empty")}</p>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 16, left: 0 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" />
              <XAxis
                dataKey="date"
                tickFormatter={(v: string) => dateTickFmt.format(new Date(v))}
                fontSize={11}
              />
              {/* Left axis: precipitation mm. Right axis: temperature °C. */}
              <YAxis
                yAxisId="precip"
                orientation="left"
                fontSize={11}
                label={{
                  value: t("weather.axisPrecip"),
                  angle: -90,
                  position: "insideLeft",
                  fontSize: 10,
                  fill: "#64748b",
                }}
              />
              <YAxis
                yAxisId="temp"
                orientation="right"
                fontSize={11}
                label={{
                  value: t("weather.axisTemp"),
                  angle: 90,
                  position: "insideRight",
                  fontSize: 10,
                  fill: "#64748b",
                }}
              />
              <Tooltip
                labelFormatter={(label: string) => dateLabelFmt.format(new Date(label))}
                formatter={(value: number, name: string) => {
                  if (value === null || Number.isNaN(value)) return ["—", name];
                  if (name === t("weather.precip")) return [`${value.toFixed(1)} mm`, name];
                  return [`${value.toFixed(1)} °C`, name];
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar
                yAxisId="precip"
                dataKey="precip"
                name={t("weather.precip")}
                fill="#3b82f6"
                fillOpacity={0.6}
                maxBarSize={18}
              />
              <Line
                yAxisId="temp"
                type="monotone"
                dataKey="temp_high"
                name={t("weather.tempHigh")}
                stroke="#dc2626"
                strokeWidth={1.75}
                dot={false}
                connectNulls
              />
              <Line
                yAxisId="temp"
                type="monotone"
                dataKey="temp_low"
                name={t("weather.tempLow")}
                stroke="#0284c7"
                strokeWidth={1.75}
                dot={false}
                connectNulls
              />
              <ReferenceLine
                yAxisId="temp"
                x={todayIso}
                stroke="#0f172a"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                label={{
                  value: t("weather.todayLabel"),
                  position: "top",
                  fontSize: 10,
                  fill: "#0f172a",
                }}
                ifOverflow="extendDomain"
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

function toNum(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}
