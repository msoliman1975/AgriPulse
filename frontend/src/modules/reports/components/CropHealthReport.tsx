import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CropHealthBlockRow, CropHealthStatus, CustomFieldDef } from "@/api/reports";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { localizedField, localizedName } from "@/lib/localizedField";
import { downloadCsv, toCsv, type CsvCell } from "@/lib/csv";
import { formatIndexValue } from "@/lib/indexFormat";
import { useCropHealthReport } from "@/queries/reports";

import { customCsvCells, customCsvHeaders, fieldsParam } from "../customFields";
import { useIndexUnit } from "../useIndexUnit";
import type { ReportProps } from "../registry";
import { CropPathFilter } from "./CropPathFilter";
import { CustomBodyCells, CustomHeaderCells } from "./CustomColumns";
import { CustomFieldPicker } from "./CustomFieldPicker";
import { ReportIndexSelect } from "./ReportIndexSelect";
import { ReportShell } from "./ReportShell";

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
  const { t, i18n } = useTranslation("reports");
  const [indexCode, setIndexCode] = useState("ndvi");
  const [cropPath, setCropPath] = useState<string | null>(null);
  const [fieldKeys, setFieldKeys] = useState<string[]>([]);
  const unit = useIndexUnit(indexCode);
  const fields = fieldsParam(fieldKeys);
  const { data, isLoading, isError } = useCropHealthReport(farmId, {
    index_code: indexCode,
    since,
    until,
    ...(cropPath ? { crop_path: cropPath } : {}),
    ...(fields ? { fields } : {}),
  });
  // Render from the response, not from `fieldKeys`: the backend drops a column
  // whose definition the farm no longer offers, and a header with no matching
  // cell would push every value one column left.
  const customFields = data?.custom_fields ?? [];

  const handleExport = (): void => {
    if (!data) return;
    const headers = [
      t("cropHealth.headers.block"),
      t("cropHealth.headers.crop"),
      t("cropHealth.headers.cropPath"),
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
      ...customCsvHeaders(customFields, i18n.language),
    ];
    const rows: CsvCell[][] = data.blocks.map((b) => [
      localizedName(i18n.language, b.block_name, b.block_name_ar),
      localizedField(i18n.language, b.crop_name_en, b.crop_name_ar) ?? "",
      b.crop_path ?? "",
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
      ...customCsvCells(customFields, b.custom, i18n.language),
    ]);
    downloadCsv(
      `crop-health_${indexCode}_${since.slice(0, 10)}_${until.slice(0, 10)}`,
      toCsv(headers, rows),
    );
  };

  return (
    <ReportShell
      title={t("catalog.crop-health.title")}
      farmName={data ? localizedName(i18n.language, data.farm_name, data.farm_name_ar) : undefined}
      period={{ since, until }}
      onExportCsv={data ? handleExport : undefined}
    >
      <div className="print-hide mb-4 flex flex-wrap items-center gap-4">
        <ReportIndexSelect value={indexCode} onChange={setIndexCode} />
        <CropPathFilter value={cropPath} onChange={setCropPath} />
        <CustomFieldPicker farmId={farmId} value={fieldKeys} onChange={setFieldKeys} />
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
          <CropHealthTable
            rows={data.blocks}
            indexCode={indexCode}
            unit={unit}
            customFields={customFields}
          />
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
  unit,
  customFields,
}: {
  rows: CropHealthBlockRow[];
  indexCode: string;
  unit: string;
  customFields: CustomFieldDef[];
}): ReactNode {
  const { t, i18n } = useTranslation("reports");
  return (
    <div className="overflow-x-auto">
      <Table>
        <Thead className="text-[11px]">
          <Tr>
            <Th scope="col">{t("cropHealth.headers.block")}</Th>
            <Th scope="col">{t("cropHealth.headers.status")}</Th>
            <Th scope="col" className="text-end">
              {indexCode.toUpperCase()}
            </Th>
            <Th scope="col" className="text-end">
              {t("cropHealth.headers.z")}
            </Th>
            <Th scope="col" className="text-end">
              {t("cropHealth.headers.trend")}
            </Th>
            <Th scope="col" className="text-end">
              p10/p50/p90
            </Th>
            <Th scope="col" className="text-end">
              {t("cropHealth.headers.valid")}
            </Th>
            <Th scope="col" className="text-end">
              {t("cropHealth.headers.scenes")}
            </Th>
            <CustomHeaderCells defs={customFields} />
          </Tr>
        </Thead>
        <Tbody>
          {rows.map((b) => (
            <Tr key={b.block_id} className="hover:bg-ap-bg/40">
              <Td className="text-ap-ink">
                <div className="font-medium">
                  {localizedName(i18n.language, b.block_name, b.block_name_ar)}
                </div>
                {b.crop_name_en ? (
                  <div className="text-[11px] text-ap-muted">
                    {localizedField(i18n.language, b.crop_name_en, b.crop_name_ar)}
                    {b.crop_path ? (
                      <span className="ms-1 font-mono text-ap-primary">{b.crop_path}</span>
                    ) : null}
                  </div>
                ) : null}
              </Td>
              <Td>
                <span
                  className={`inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium ${STATUS_CHIP[b.status]}`}
                >
                  {t(`cropHealth.status.${b.status}`)}
                </span>
              </Td>
              <Td className="text-end tabular-nums text-ap-ink">
                {/* `lst` is degrees Celsius at one decimal; every other index
                    is a dimensionless ratio at three. One toFixed(3) for both
                    printed a temperature to a precision the sensor lacks. */}
                {formatIndexValue(b.last_value === null ? null : Number(b.last_value), unit)}
              </Td>
              <Td className="text-end tabular-nums">
                <ZScore value={b.baseline_z} />
              </Td>
              <Td className="text-end tabular-nums">
                <Trend value={b.trend_pct} />
              </Td>
              <Td className="text-end tabular-nums">
                {fmt(b.p10, 2)} / {fmt(b.p50, 2)} / {fmt(b.p90, 2)}
              </Td>
              <Td className="text-end tabular-nums">
                {b.avg_valid_pixel_pct ? `${fmt(b.avg_valid_pixel_pct, 0)}%` : "—"}
              </Td>
              <Td className="text-end tabular-nums">{b.scene_count}</Td>
              <CustomBodyCells defs={customFields} cells={b.custom} />
            </Tr>
          ))}
        </Tbody>
      </Table>
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
