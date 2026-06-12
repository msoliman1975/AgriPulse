import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { OperationsLogReportResponse, OpsLogEntry, OpsLogKind } from "@/api/reports";
import { Skeleton } from "@/components/Skeleton";
import { downloadCsv, toCsv, type CsvCell } from "@/lib/csv";
import { useOperationsLogReport } from "@/queries/reports";

import type { ReportProps } from "../registry";
import { ReportShell } from "./ReportShell";

const KIND_CHIP: Record<OpsLogKind, string> = {
  activity: "bg-ap-primary-soft text-ap-primary",
  alert: "bg-ap-crit-soft text-ap-crit",
  recommendation: "bg-ap-warn-soft text-ap-warn",
};

function day(iso: string): string {
  return iso.slice(0, 10);
}

export function OperationsLogReport({ farmId, since, until }: ReportProps): ReactNode {
  const { t } = useTranslation("reports");
  const { data, isLoading, isError } = useOperationsLogReport(farmId, { since, until });

  const handleExport = (): void => {
    if (!data) return;
    const headers = [
      t("opsLog.headers.date"),
      t("opsLog.headers.type"),
      t("opsLog.headers.block"),
      t("opsLog.headers.title"),
      t("opsLog.headers.status"),
      t("opsLog.headers.severity"),
      t("opsLog.headers.detail"),
    ];
    const rows: CsvCell[][] = data.entries.map((e) => [
      day(e.time),
      t(`opsLog.kind.${e.kind}`),
      e.block_name ?? "",
      e.title,
      e.status ?? "",
      e.severity ?? "",
      e.detail ?? "",
    ]);
    downloadCsv(
      `operations-log_${since.slice(0, 10)}_${until.slice(0, 10)}`,
      toCsv(headers, rows),
    );
  };

  return (
    <ReportShell
      title={t("catalog.operations-log.title")}
      farmName={data?.farm_name}
      period={{ since, until }}
      onExportCsv={data ? handleExport : undefined}
    >
      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : isError ? (
        <p className="py-8 text-center text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : !data ? (
        <p className="py-8 text-center text-sm text-ap-muted">{t("opsLog.empty")}</p>
      ) : (
        <>
          <Summary data={data} />
          {data.entries.length === 0 ? (
            <p className="py-8 text-center text-sm text-ap-muted">{t("opsLog.empty")}</p>
          ) : (
            <LogTable entries={data.entries} />
          )}
        </>
      )}
    </ReportShell>
  );
}

function Summary({ data }: { data: OperationsLogReportResponse }): ReactNode {
  const { t } = useTranslation("reports");
  const s = data.summary;
  const groups: Array<[string, string]> = [
    [
      t("opsLog.kind.activity"),
      t("opsLog.summary.activities", {
        total: s.activities_total,
        done: s.activities_completed,
        skipped: s.activities_skipped,
      }),
    ],
    [
      t("opsLog.kind.alert"),
      t("opsLog.summary.alerts", { opened: s.alerts_opened, resolved: s.alerts_resolved }),
    ],
    [
      t("opsLog.kind.recommendation"),
      t("opsLog.summary.recommendations", {
        total: s.recommendations_total,
        applied: s.recommendations_applied,
        dismissed: s.recommendations_dismissed,
      }),
    ],
  ];
  return (
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      {groups.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-ap-line bg-ap-bg/40 p-3">
          <div className="text-[11px] uppercase tracking-wider text-ap-muted">{label}</div>
          <div className="mt-1 text-sm font-medium text-ap-ink">{value}</div>
        </div>
      ))}
    </div>
  );
}

function LogTable({ entries }: { entries: OpsLogEntry[] }): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-ap-line text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-ap-muted">
          <tr>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("opsLog.headers.date")}
            </th>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("opsLog.headers.type")}
            </th>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("opsLog.headers.block")}
            </th>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("opsLog.headers.title")}
            </th>
            <th scope="col" className="px-3 py-2 text-start font-semibold">
              {t("opsLog.headers.status")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ap-line">
          {entries.map((e, i) => (
            <tr key={`${e.kind}-${i}`} className="hover:bg-ap-bg/40">
              <td className="whitespace-nowrap px-3 py-2 text-[11px] text-ap-muted">
                {day(e.time)}
              </td>
              <td className="px-3 py-2">
                <span
                  className={`inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium ${KIND_CHIP[e.kind]}`}
                >
                  {t(`opsLog.kind.${e.kind}`)}
                </span>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-ap-muted">{e.block_name ?? "—"}</td>
              <td className="px-3 py-2 text-ap-ink">
                <div>{e.title}</div>
                {e.detail ? <div className="text-[11px] text-ap-muted">{e.detail}</div> : null}
              </td>
              <td className="px-3 py-2 text-[11px] text-ap-muted">
                {e.status ?? "—"}
                {e.severity ? ` · ${e.severity}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
