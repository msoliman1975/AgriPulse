import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  WaterBalanceBlockRow,
  WaterBalanceSummary,
  WaterBalanceWeather,
} from "@/api/reports";
import { Skeleton } from "@/components/Skeleton";
import { downloadCsv, toCsv, type CsvCell } from "@/lib/csv";
import { useWaterBalanceReport } from "@/queries/reports";

import type { ReportProps } from "../registry";
import { ReportShell } from "./ReportShell";

function fmt(value: string | null, digits = 1, suffix = ""): string {
  if (value === null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(digits)}${suffix}` : "—";
}

export function WaterBalanceReport({ farmId, since, until }: ReportProps): ReactNode {
  const { t } = useTranslation("reports");
  const { data, isLoading, isError } = useWaterBalanceReport(farmId, { since, until });

  const handleExport = (): void => {
    if (!data) return;
    const headers = [
      t("waterBalance.headers.block"),
      t("waterBalance.headers.scheduled"),
      t("waterBalance.headers.applied"),
      t("waterBalance.headers.skipped"),
      t("waterBalance.headers.pending"),
      t("waterBalance.headers.recommended"),
      t("waterBalance.headers.appliedMm"),
      t("waterBalance.headers.adherence"),
      t("waterBalance.headers.last"),
    ];
    const rows: CsvCell[][] = data.blocks.map((b) => [
      b.block_name,
      b.scheduled_count,
      b.applied_count,
      b.skipped_count,
      b.pending_count,
      b.recommended_mm_total ?? "",
      b.applied_mm_total ?? "",
      b.adherence_pct ?? "",
      b.last_scheduled_for ?? "",
    ]);
    downloadCsv(
      `water-balance_${since.slice(0, 10)}_${until.slice(0, 10)}`,
      toCsv(headers, rows),
    );
  };

  return (
    <ReportShell
      title={t("catalog.water-balance.title")}
      farmName={data?.farm_name}
      period={{ since, until }}
      onExportCsv={data ? handleExport : undefined}
    >
      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : isError ? (
        <p className="py-8 text-center text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : !data ? (
        <p className="py-8 text-center text-sm text-ap-muted">{t("waterBalance.empty")}</p>
      ) : (
        <>
          <WeatherCards weather={data.weather} summary={data.summary} />
          {data.blocks.length === 0 ? (
            <p className="py-8 text-center text-sm text-ap-muted">{t("waterBalance.empty")}</p>
          ) : (
            <WaterBalanceTable rows={data.blocks} />
          )}
        </>
      )}
    </ReportShell>
  );
}

function WeatherCards({
  weather,
  summary,
}: {
  weather: WaterBalanceWeather;
  summary: WaterBalanceSummary;
}): ReactNode {
  const { t } = useTranslation("reports");
  const cards: Array<[string, string]> = [
    [t("waterBalance.cards.et0"), fmt(weather.et0_mm_total, 1, " mm")],
    [t("waterBalance.cards.rain"), fmt(weather.precip_mm_total, 1, " mm")],
    [t("waterBalance.cards.applied"), fmt(summary.applied_mm_total, 1, " mm")],
    [t("waterBalance.cards.recommended"), fmt(summary.recommended_mm_total, 1, " mm")],
  ];
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-ap-line bg-ap-bg/40 p-3">
          <div className="text-[11px] uppercase tracking-wider text-ap-muted">{label}</div>
          <div className="mt-1 text-lg font-semibold tabular-nums text-ap-ink">{value}</div>
        </div>
      ))}
    </div>
  );
}

function WaterBalanceTable({ rows }: { rows: WaterBalanceBlockRow[] }): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-ap-line text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-ap-muted">
          <tr>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("waterBalance.headers.block")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("waterBalance.headers.scheduled")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("waterBalance.headers.applied")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("waterBalance.headers.recommended")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("waterBalance.headers.appliedMm")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("waterBalance.headers.adherence")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("waterBalance.headers.last")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ap-line">
          {rows.map((b) => (
            <tr key={b.block_id} className="hover:bg-ap-bg/40">
              <td className="px-3 py-2 font-medium text-ap-ink">{b.block_name}</td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-muted">
                {b.scheduled_count || "—"}
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-ink">
                {b.scheduled_count ? b.applied_count : "—"}
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-ink">
                {fmt(b.recommended_mm_total, 1, " mm")}
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-ink">
                {fmt(b.applied_mm_total, 1, " mm")}
              </td>
              <td className="px-3 py-2 text-end tabular-nums">
                <Adherence value={b.adherence_pct} />
              </td>
              <td className="px-3 py-2 text-end text-[11px] text-ap-muted">
                {b.last_scheduled_for ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Adherence({ value }: { value: string | null }): ReactNode {
  if (value === null) return <span className="text-ap-muted">—</span>;
  const n = Number(value);
  // Under-watering (well below recommended) flags amber; on-target green.
  const cls = n >= 90 ? "text-ap-primary" : n >= 60 ? "text-ap-warn" : "text-ap-crit";
  return <span className={cls}>{n.toFixed(0)}%</span>;
}
