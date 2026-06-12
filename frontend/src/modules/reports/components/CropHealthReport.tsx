import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CropHealthBlockRow, CropHealthStatus } from "@/api/reports";
import { Skeleton } from "@/components/Skeleton";
import { downloadCsv, toCsv, type CsvCell } from "@/lib/csv";
import { useCropHealthReport } from "@/queries/reports";

import type { ReportProps } from "../registry";
import { ReportShell } from "./ReportShell";

// Indices the report can run on. NDVI default; the rest cover the
// standard vegetation/moisture set the platform computes.
const INDEX_CODES = ["ndvi", "ndre", "ndwi", "evi", "savi", "gndvi"] as const;

const STATUS_CHIP: Record<CropHealthStatus, string> = {
  normal: "bg-ap-primary-soft text-ap-primary",
  watch: "bg-ap-warn-soft text-ap-warn",
  stressed: "bg-ap-crit-soft text-ap-crit",
  unknown: "bg-ap-bg text-ap-muted",
};

function fmt(value: string | null, digits = 3): string {
  if (value === null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

export function CropHealthReport({ farmId, since, until }: ReportProps): ReactNode {
  const { t } = useTranslation("reports");
  const [indexCode, setIndexCode] = useState("ndvi");
  const { data, isLoading, isError } = useCropHealthReport(farmId, {
    index_code: indexCode,
    since,
    until,
  });

  const handleExport = (): void => {
    if (!data) return;
    const headers = [
      t("cropHealth.headers.block"),
      t("cropHealth.headers.crop"),
      t("cropHealth.headers.status"),
      `${indexCode.toUpperCase()} ${t("cropHealth.headers.last")}`,
      t("cropHealth.headers.observed"),
      t("cropHealth.headers.z"),
      t("cropHealth.headers.trend"),
      t("cropHealth.headers.min"),
      t("cropHealth.headers.max"),
      "p10",
      "p50",
      "p90",
      t("cropHealth.headers.valid"),
      t("cropHealth.headers.cloud"),
      t("cropHealth.headers.scenes"),
    ];
    const rows: CsvCell[][] = data.blocks.map((b) => [
      b.block_name,
      b.crop_name_en ?? "",
      t(`cropHealth.status.${b.status}`),
      b.last_value ?? "",
      b.last_observed_at?.slice(0, 10) ?? "",
      b.baseline_z ?? "",
      b.trend_pct ?? "",
      b.min_value ?? "",
      b.max_value ?? "",
      b.p10 ?? "",
      b.p50 ?? "",
      b.p90 ?? "",
      b.avg_valid_pixel_pct ?? "",
      b.avg_cloud_pct ?? "",
      b.scene_count,
    ]);
    downloadCsv(
      `crop-health_${indexCode}_${since.slice(0, 10)}_${until.slice(0, 10)}`,
      toCsv(headers, rows),
    );
  };

  return (
    <ReportShell
      title={t("catalog.crop-health.title")}
      farmName={data?.farm_name}
      period={{ since, until }}
      onExportCsv={data ? handleExport : undefined}
    >
      <div className="print-hide mb-4 flex items-center gap-2">
        <span className="label mb-0">{t("cropHealth.index")}</span>
        <select
          className="input w-auto"
          value={indexCode}
          onChange={(e) => setIndexCode(e.target.value)}
        >
          {INDEX_CODES.map((code) => (
            <option key={code} value={code}>
              {code.toUpperCase()}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : isError ? (
        <p className="py-8 text-center text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : !data || data.blocks.length === 0 ? (
        <p className="py-8 text-center text-sm text-ap-muted">{t("cropHealth.empty")}</p>
      ) : (
        <>
          <Summary data={data.summary} />
          <CropHealthTable rows={data.blocks} indexCode={indexCode} />
        </>
      )}
    </ReportShell>
  );
}

function Summary({ data }: { data: import("@/api/reports").CropHealthSummary }): ReactNode {
  const { t } = useTranslation("reports");
  const chips: Array<[string, number, string]> = [
    [t("cropHealth.status.stressed"), data.stressed, "text-ap-crit"],
    [t("cropHealth.status.watch"), data.watch, "text-ap-warn"],
    [t("cropHealth.status.normal"), data.normal, "text-ap-primary"],
    [t("cropHealth.status.unknown"), data.unknown, "text-ap-muted"],
  ];
  return (
    <div className="mb-4 flex flex-wrap items-center gap-4 text-sm">
      {chips.map(([label, count, cls]) => (
        <span key={label} className="flex items-baseline gap-1.5">
          <span className={`text-lg font-semibold tabular-nums ${cls}`}>{count}</span>
          <span className="text-ap-muted">{label}</span>
        </span>
      ))}
      <span className="ms-auto text-xs text-ap-muted">
        {t("cropHealth.coverage", {
          withData: data.with_data_count,
          total: data.block_count,
        })}
      </span>
    </div>
  );
}

function CropHealthTable({
  rows,
  indexCode,
}: {
  rows: CropHealthBlockRow[];
  indexCode: string;
}): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-ap-line text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-ap-muted">
          <tr>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("cropHealth.headers.block")}
            </th>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("cropHealth.headers.status")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {indexCode.toUpperCase()}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("cropHealth.headers.z")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("cropHealth.headers.trend")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              p10/p50/p90
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("cropHealth.headers.valid")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("cropHealth.headers.scenes")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ap-line">
          {rows.map((b) => (
            <tr key={b.block_id} className="hover:bg-ap-bg/40">
              <td className="px-3 py-2 text-ap-ink">
                <div className="font-medium">{b.block_name}</div>
                {b.crop_name_en ? (
                  <div className="text-[11px] text-ap-muted">{b.crop_name_en}</div>
                ) : null}
              </td>
              <td className="px-3 py-2">
                <span
                  className={`inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium ${STATUS_CHIP[b.status]}`}
                >
                  {t(`cropHealth.status.${b.status}`)}
                </span>
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-ink">{fmt(b.last_value)}</td>
              <td className="px-3 py-2 text-end tabular-nums">
                <ZScore value={b.baseline_z} />
              </td>
              <td className="px-3 py-2 text-end tabular-nums">
                <Trend value={b.trend_pct} />
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-muted">
                {fmt(b.p10, 2)} / {fmt(b.p50, 2)} / {fmt(b.p90, 2)}
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-muted">
                {b.avg_valid_pixel_pct ? `${fmt(b.avg_valid_pixel_pct, 0)}%` : "—"}
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-muted">{b.scene_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ZScore({ value }: { value: string | null }): ReactNode {
  if (value === null) return <span className="text-ap-muted">—</span>;
  const n = Number(value);
  const cls = n <= -2 ? "text-ap-crit" : n <= -1 ? "text-ap-warn" : "text-ap-ink";
  return <span className={cls}>{n.toFixed(2)}</span>;
}

function Trend({ value }: { value: string | null }): ReactNode {
  if (value === null) return <span className="text-ap-muted">—</span>;
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  const cls = n > 0 ? "text-ap-primary" : n < 0 ? "text-ap-crit" : "text-ap-muted";
  return (
    <span className={cls}>
      {sign}
      {n.toFixed(1)}%
    </span>
  );
}
