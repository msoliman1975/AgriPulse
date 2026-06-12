import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { WeatherCropContext, WeatherSummaryStats } from "@/api/reports";
import { Skeleton } from "@/components/Skeleton";
import { downloadCsv, toCsv, type CsvCell } from "@/lib/csv";
import { useWeatherSummaryReport } from "@/queries/reports";

import type { ReportProps } from "../registry";
import { ReportShell } from "./ReportShell";

function num(v: string | null): number | null {
  if (v === null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmt(v: string | null, digits = 1, suffix = ""): string {
  if (v === null) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toFixed(digits)}${suffix}` : "—";
}

interface ChartPoint {
  date: string;
  tmax: number | null;
  tmin: number | null;
  precip: number | null;
  gddCum: number | null;
}

export function WeatherSummaryReport({ farmId, since, until }: ReportProps): ReactNode {
  const { t } = useTranslation("reports");
  const { data, isLoading, isError } = useWeatherSummaryReport(farmId, { since, until });

  const chart = useMemo<ChartPoint[]>(
    () =>
      (data?.daily ?? []).map((d) => ({
        date: d.date,
        tmax: num(d.temp_max_c),
        tmin: num(d.temp_min_c),
        precip: num(d.precip_mm),
        gddCum: num(d.gdd_cumulative_season),
      })),
    [data],
  );

  const handleExport = (): void => {
    if (!data) return;
    const headers = [
      t("weatherSummary.headers.date"),
      t("weatherSummary.headers.tmin"),
      t("weatherSummary.headers.tmax"),
      t("weatherSummary.headers.tmean"),
      t("weatherSummary.headers.precip"),
      t("weatherSummary.headers.et0"),
      t("weatherSummary.headers.gdd"),
      t("weatherSummary.headers.gddCum"),
    ];
    const rows: CsvCell[][] = data.daily.map((d) => [
      d.date,
      d.temp_min_c ?? "",
      d.temp_max_c ?? "",
      d.temp_mean_c ?? "",
      d.precip_mm ?? "",
      d.et0_mm ?? "",
      d.gdd_base10 ?? "",
      d.gdd_cumulative_season ?? "",
    ]);
    downloadCsv(
      `weather-summary_${since.slice(0, 10)}_${until.slice(0, 10)}`,
      toCsv(headers, rows),
    );
  };

  return (
    <ReportShell
      title={t("catalog.weather-summary.title")}
      farmName={data?.farm_name}
      period={{ since, until }}
      onExportCsv={data ? handleExport : undefined}
    >
      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : isError ? (
        <p className="py-8 text-center text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : !data || data.daily.length === 0 ? (
        <p className="py-8 text-center text-sm text-ap-muted">{t("weatherSummary.empty")}</p>
      ) : (
        <>
          <StatCards stats={data.stats} />
          {data.crops.length > 0 ? <CropContext crops={data.crops} /> : null}
          <TempPrecipChart data={chart} />
          <GddChart data={chart} />
        </>
      )}
    </ReportShell>
  );
}

function StatCards({ stats }: { stats: WeatherSummaryStats }): ReactNode {
  const { t } = useTranslation("reports");
  const cards: Array<[string, string]> = [
    [t("weatherSummary.cards.tempRange"), `${fmt(stats.temp_min_c)} – ${fmt(stats.temp_max_c, 1, "°C")}`],
    [t("weatherSummary.cards.rain"), `${fmt(stats.precip_mm_total, 1, " mm")} (${stats.rain_days}d)`],
    [t("weatherSummary.cards.et0"), fmt(stats.et0_mm_total, 1, " mm")],
    [t("weatherSummary.cards.gddCum"), fmt(stats.gdd_cumulative_season, 0, " °C·d")],
  ];
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-ap-line bg-ap-bg/40 p-3">
          <div className="text-[11px] uppercase tracking-wider text-ap-muted">{label}</div>
          <div className="mt-1 text-base font-semibold tabular-nums text-ap-ink">{value}</div>
        </div>
      ))}
    </div>
  );
}

function CropContext({ crops }: { crops: WeatherCropContext[] }): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="mb-4 flex flex-wrap gap-2 text-xs">
      {crops.map((c) => (
        <span
          key={c.crop_id}
          className="rounded-full border border-ap-line bg-ap-panel px-2.5 py-1 text-ap-muted"
        >
          <span className="font-medium text-ap-ink">{c.name_en}</span>
          {c.gdd_base_temp_c ? ` · ${t("weatherSummary.base")} ${Number(c.gdd_base_temp_c).toFixed(1)}°C` : ""}
          {c.default_growing_season_days
            ? ` · ${c.default_growing_season_days} ${t("weatherSummary.days")}`
            : ""}
        </span>
      ))}
    </div>
  );
}

function tick(value: string): string {
  const d = new Date(value);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function TempPrecipChart({ data }: { data: ChartPoint[] }): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="mb-2">
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
        {t("weatherSummary.charts.tempPrecip")}
      </h3>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" />
          <XAxis dataKey="date" tickFormatter={tick} fontSize={11} />
          <YAxis yAxisId="precip" orientation="left" fontSize={11} />
          <YAxis yAxisId="temp" orientation="right" fontSize={11} />
          <Tooltip labelFormatter={(l: string) => new Date(l).toLocaleDateString()} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar
            yAxisId="precip"
            dataKey="precip"
            name={t("weatherSummary.series.precip")}
            fill="#3b82f6"
            fillOpacity={0.6}
            maxBarSize={16}
          />
          <Line
            yAxisId="temp"
            type="monotone"
            dataKey="tmax"
            name={t("weatherSummary.series.tmax")}
            stroke="#dc2626"
            strokeWidth={1.75}
            dot={false}
            connectNulls
          />
          <Line
            yAxisId="temp"
            type="monotone"
            dataKey="tmin"
            name={t("weatherSummary.series.tmin")}
            stroke="#0284c7"
            strokeWidth={1.75}
            dot={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function GddChart({ data }: { data: ChartPoint[] }): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div>
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
        {t("weatherSummary.charts.gdd")}
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 2" />
          <XAxis dataKey="date" tickFormatter={tick} fontSize={11} />
          <YAxis fontSize={11} />
          <Tooltip labelFormatter={(l: string) => new Date(l).toLocaleDateString()} />
          <Line
            type="monotone"
            dataKey="gddCum"
            name={t("weatherSummary.series.gddCum")}
            stroke="#356b30"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
