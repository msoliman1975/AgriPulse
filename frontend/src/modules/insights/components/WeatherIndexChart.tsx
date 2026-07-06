import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getWeatherIndexTimeseries } from "@/api/weatherIndices";
import { Skeleton } from "@/components/Skeleton";
import { makeDateLabelFmt, makeDateTickFmt } from "@/lib/chartFormat";

interface Props {
  farmId: string;
  indexCode: string;
  /** Localized index name (already resolved en/ar by the caller). */
  name: string;
  unit: string;
}

interface ChartPoint {
  date: string;
  value: number | null;
  mean: number | null;
  /** [mean - std, mean + std] band, or null when no baseline that day. */
  band: [number, number] | null;
}

/**
 * Farm-level weather-index series for the last 90 days with a climatology
 * band (seasonal normal ±1σ). Weather is farm-centroid data, so this is a
 * temporal chart — not a per-cell map overlay.
 */
export function WeatherIndexChart({ farmId, indexCode, name, unit }: Props): ReactNode {
  const { t, i18n } = useTranslation("weatherIndices");
  const dateTickFmt = useMemo(() => makeDateTickFmt(i18n.language), [i18n.language]);
  const dateLabelFmt = useMemo(() => makeDateLabelFmt(i18n.language), [i18n.language]);

  const { from, to } = useMemo(() => {
    const now = new Date();
    const start = new Date(now);
    start.setDate(start.getDate() - 90);
    return {
      from: start.toISOString().slice(0, 10),
      to: new Date(now.getTime() + 86_400_000).toISOString().slice(0, 10),
    };
  }, []);

  const q = useQuery({
    queryKey: ["weatherIndices", "timeseries", farmId, indexCode, from, to] as const,
    queryFn: () => getWeatherIndexTimeseries(farmId, indexCode, { from, to }),
    enabled: Boolean(farmId && indexCode),
    staleTime: 60_000,
  });

  const data = useMemo<ChartPoint[]>(() => {
    return (q.data?.points ?? []).map((p) => {
      const mean = _toNum(p.baseline_mean);
      const std = _toNum(p.baseline_std);
      const band: [number, number] | null =
        mean !== null && std !== null ? [mean - std, mean + std] : null;
      return { date: p.date, value: _toNum(p.value), mean, band };
    });
  }, [q.data]);

  if (q.isLoading) {
    return <Skeleton className="h-56 w-full" />;
  }
  if (q.isError) {
    return <p className="py-10 text-center text-sm text-ap-crit">{t("chart.loadFailed")}</p>;
  }
  if (data.length === 0) {
    return <p className="py-10 text-center text-sm text-ap-muted">{t("chart.empty")}</p>;
  }

  return (
    <div className="mt-3">
      <h4 className="mb-1 text-[11px] font-medium text-ap-muted">{t("chart.title", { name })}</h4>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" />
          <XAxis
            dataKey="date"
            tickFormatter={(v: string) => dateTickFmt.format(new Date(v))}
            fontSize={11}
            minTickGap={28}
          />
          <YAxis fontSize={11} width={44} />
          <Tooltip
            labelFormatter={(label: string) => dateLabelFmt.format(new Date(label))}
            formatter={(value: number | number[], rawName: string) => {
              if (Array.isArray(value)) {
                return [`${value[0].toFixed(1)} – ${value[1].toFixed(1)} ${unit}`, rawName];
              }
              if (value === null || Number.isNaN(value)) return ["—", rawName];
              return [`${value.toFixed(1)} ${unit}`, rawName];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Area
            dataKey="band"
            name={t("chart.band")}
            stroke="none"
            fill="#93c5fd"
            fillOpacity={0.25}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="mean"
            name={t("chart.normalLine")}
            stroke="#64748b"
            strokeWidth={1.25}
            strokeDasharray="4 3"
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="value"
            name={t("chart.valueLine")}
            stroke="#0f766e"
            strokeWidth={1.75}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function _toNum(v: string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
