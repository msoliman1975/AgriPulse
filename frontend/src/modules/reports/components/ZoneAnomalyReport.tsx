import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ZoneAnomalyBlockRow, ZoneAnomalyStatus } from "@/api/reports";
import { Skeleton } from "@/components/Skeleton";
import { downloadCsv, toCsv, type CsvCell } from "@/lib/csv";
import { useZoneAnomalyReport } from "@/queries/reports";

import type { ReportProps } from "../registry";
import { ReportShell } from "./ReportShell";

const INDEX_CODES = ["ndvi", "ndre", "ndwi", "evi", "savi", "gndvi"] as const;

const STATUS_CHIP: Record<ZoneAnomalyStatus, string> = {
  anomalies: "bg-ap-crit-soft text-ap-crit",
  clear: "bg-ap-primary-soft text-ap-primary",
  insufficient: "bg-ap-warn-soft text-ap-warn",
  no_data: "bg-ap-bg text-ap-muted",
  no_grid: "bg-ap-bg text-ap-muted",
};

function fmt(value: string | null, digits = 3): string {
  if (value === null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

export function ZoneAnomalyReport({ farmId, since, until }: ReportProps): ReactNode {
  const { t } = useTranslation("reports");
  const [indexCode, setIndexCode] = useState("ndvi");
  const { data, isLoading, isError } = useZoneAnomalyReport(farmId, {
    index_code: indexCode,
    since,
    until,
  });

  const handleExport = (): void => {
    if (!data) return;
    const headers = [
      t("zoneAnomaly.headers.block"),
      t("zoneAnomaly.headers.status"),
      t("zoneAnomaly.headers.scene"),
      t("zoneAnomaly.headers.cells"),
      t("zoneAnomaly.headers.flagged"),
      t("zoneAnomaly.headers.area"),
      t("zoneAnomaly.headers.worstZ"),
      t("zoneAnomaly.headers.mean"),
      t("zoneAnomaly.headers.std"),
      t("zoneAnomaly.headers.threshold"),
    ];
    const rows: CsvCell[][] = data.blocks.map((b) => [
      b.block_name,
      t(`zoneAnomaly.status.${b.status}`),
      b.scene_time?.slice(0, 10) ?? "",
      b.cell_count,
      b.flagged_count,
      b.flagged_area_ha ?? "",
      b.worst_z ?? "",
      b.block_mean ?? "",
      b.block_std ?? "",
      b.threshold_k ?? "",
    ]);
    downloadCsv(
      `zone-anomaly_${indexCode}_${since.slice(0, 10)}_${until.slice(0, 10)}`,
      toCsv(headers, rows),
    );
  };

  return (
    <ReportShell
      title={t("catalog.zone-anomaly.title")}
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
        <p className="py-8 text-center text-sm text-ap-muted">{t("zoneAnomaly.empty")}</p>
      ) : (
        <>
          <Summary data={data.summary} />
          <ZoneAnomalyTable rows={data.blocks} />
        </>
      )}
    </ReportShell>
  );
}

function Summary({ data }: { data: import("@/api/reports").ZoneAnomalySummary }): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="mb-4 flex flex-wrap items-center gap-4 text-sm">
      <span className="flex items-baseline gap-1.5">
        <span className="text-lg font-semibold tabular-nums text-ap-crit">
          {data.blocks_with_anomalies}
        </span>
        <span className="text-ap-muted">{t("zoneAnomaly.summary.blocksFlagged")}</span>
      </span>
      <span className="flex items-baseline gap-1.5">
        <span className="text-lg font-semibold tabular-nums text-ap-ink">
          {data.total_flagged_cells}
        </span>
        <span className="text-ap-muted">{t("zoneAnomaly.summary.cells")}</span>
      </span>
      <span className="flex items-baseline gap-1.5">
        <span className="text-lg font-semibold tabular-nums text-ap-ink">
          {data.total_flagged_area_ha ? Number(data.total_flagged_area_ha).toFixed(2) : "0.00"}
        </span>
        <span className="text-ap-muted">{t("zoneAnomaly.summary.hectares")}</span>
      </span>
      <span className="ms-auto text-xs text-ap-muted">
        {t("zoneAnomaly.summary.coverage", {
          withGrid: data.blocks_with_grid,
          total: data.block_count,
        })}
      </span>
    </div>
  );
}

function ZoneAnomalyTable({ rows }: { rows: ZoneAnomalyBlockRow[] }): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-ap-line text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-ap-muted">
          <tr>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("zoneAnomaly.headers.block")}
            </th>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("zoneAnomaly.headers.status")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("zoneAnomaly.headers.scene")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("zoneAnomaly.headers.cells")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("zoneAnomaly.headers.flagged")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("zoneAnomaly.headers.area")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("zoneAnomaly.headers.worstZ")}
            </th>
            <th scope="col" className="px-3 py-2 text-end font-semibold">
              {t("zoneAnomaly.headers.meanStd")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ap-line">
          {rows.map((b) => (
            <tr key={b.block_id} className="hover:bg-ap-bg/40">
              <td className="px-3 py-2 font-medium text-ap-ink">{b.block_name}</td>
              <td className="px-3 py-2">
                <span
                  className={`inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium ${STATUS_CHIP[b.status]}`}
                >
                  {t(`zoneAnomaly.status.${b.status}`)}
                </span>
              </td>
              <td className="px-3 py-2 text-end text-[11px] text-ap-muted">
                {b.scene_time?.slice(0, 10) ?? "—"}
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-muted">
                {b.cell_count || "—"}
              </td>
              <td className="px-3 py-2 text-end tabular-nums">
                {b.flagged_count > 0 ? (
                  <span className="font-medium text-ap-crit">{b.flagged_count}</span>
                ) : (
                  <span className="text-ap-muted">{b.cell_count ? 0 : "—"}</span>
                )}
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-ink">
                {b.flagged_area_ha ? `${Number(b.flagged_area_ha).toFixed(2)} ha` : "—"}
              </td>
              <td className="px-3 py-2 text-end tabular-nums">
                {b.worst_z !== null ? (
                  <span className={Number(b.worst_z) <= -2 ? "text-ap-crit" : "text-ap-ink"}>
                    {fmt(b.worst_z, 2)}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="px-3 py-2 text-end tabular-nums text-ap-muted">
                {b.block_mean !== null ? `${fmt(b.block_mean)} ± ${fmt(b.block_std)}` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
