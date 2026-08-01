import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { WeatherRiskPressureRow, WeatherRiskPressureSummary } from "@/api/reports";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { downloadCsv, toCsv, type CsvCell } from "@/lib/csv";
import { useWeatherRiskPressureReport } from "@/queries/reports";

import type { ReportProps } from "../registry";
import { ReportShell } from "./ReportShell";

const LEVEL_CLASS: Record<WeatherRiskPressureRow["latest_level"], string> = {
  high: "text-ap-crit",
  moderate: "text-ap-warn",
  low: "text-ap-good",
};

export function WeatherRiskPressureReport({ farmId, since, until }: ReportProps): ReactNode {
  const { t } = useTranslation("reports");
  const wr = useTranslation("weatherRisk").t;
  const { data, isLoading, isError } = useWeatherRiskPressureReport(farmId, { since, until });

  const pathogenName = (code: string): string => {
    const name = wr(`pathogen.${code}`);
    return name === `pathogen.${code}` ? code : name;
  };
  const levelName = (level: string): string => {
    const name = wr(`level.${level}`);
    return name === `level.${level}` ? level : name;
  };

  const handleExport = (): void => {
    if (!data) return;
    const headers = [
      t("weatherRiskPressure.headers.block"),
      t("weatherRiskPressure.headers.pathogen"),
      t("weatherRiskPressure.headers.peak"),
      t("weatherRiskPressure.headers.daysHigh"),
      t("weatherRiskPressure.headers.daysModerate"),
      t("weatherRiskPressure.headers.latest"),
      t("weatherRiskPressure.headers.latestDate"),
    ];
    const rows: CsvCell[][] = data.rows.map((r) => [
      r.block_name,
      pathogenName(r.risk_code),
      r.peak_score,
      r.days_high,
      r.days_moderate,
      levelName(r.latest_level),
      r.latest_date,
    ]);
    downloadCsv(
      `disease-pest-pressure_${since.slice(0, 10)}_${until.slice(0, 10)}`,
      toCsv(headers, rows),
    );
  };

  return (
    <ReportShell
      title={t("catalog.weather-risk-pressure.title")}
      farmName={data?.farm_name}
      period={{ since, until }}
      onExportCsv={data && data.rows.length > 0 ? handleExport : undefined}
    >
      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : isError ? (
        <p className="py-8 text-center text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : !data || data.rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-ap-muted">{t("weatherRiskPressure.empty")}</p>
      ) : (
        <>
          <SummaryCards summary={data.summary} />
          <PressureTable rows={data.rows} pathogenName={pathogenName} levelName={levelName} />
        </>
      )}
    </ReportShell>
  );
}

function SummaryCards({ summary }: { summary: WeatherRiskPressureSummary }): ReactNode {
  const { t } = useTranslation("reports");
  const cards: Array<[string, string | number]> = [
    [t("weatherRiskPressure.cards.blocksAtRisk"), summary.blocks_at_risk],
    [t("weatherRiskPressure.cards.pathogens"), summary.pathogen_count],
    [t("weatherRiskPressure.cards.highDays"), summary.total_high_days],
    [t("weatherRiskPressure.cards.blocks"), summary.block_count],
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

function PressureTable({
  rows,
  pathogenName,
  levelName,
}: {
  rows: WeatherRiskPressureRow[];
  pathogenName: (code: string) => string;
  levelName: (level: string) => string;
}): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="overflow-x-auto">
      <Table>
        <Thead className="text-[11px]">
          <Tr>
            <Th scope="col">{t("weatherRiskPressure.headers.block")}</Th>
            <Th scope="col">{t("weatherRiskPressure.headers.pathogen")}</Th>
            <Th scope="col" className="text-end">
              {t("weatherRiskPressure.headers.peak")}
            </Th>
            <Th scope="col" className="text-end">
              {t("weatherRiskPressure.headers.daysHigh")}
            </Th>
            <Th scope="col" className="text-end">
              {t("weatherRiskPressure.headers.latest")}
            </Th>
          </Tr>
        </Thead>
        <Tbody>
          {rows.map((r) => (
            <Tr key={`${r.block_id}:${r.risk_code}`} className="hover:bg-ap-bg/40">
              <Td className="font-medium text-ap-ink">{r.block_name}</Td>
              <Td className="text-ap-ink">{pathogenName(r.risk_code)}</Td>
              <Td className="text-end tabular-nums text-ap-ink">{r.peak_score}</Td>
              <Td className="text-end tabular-nums">{r.days_high || "—"}</Td>
              <Td className={`px-3 py-2 text-end font-medium ${LEVEL_CLASS[r.latest_level]}`}>
                {levelName(r.latest_level)} · {r.latest_score}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </div>
  );
}
