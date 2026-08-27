import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { listBlocks } from "@/api/blocks";
import type { CustomFieldDef, SignalDetailRow, SignalDetailStat } from "@/api/reports";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { localizedField, localizedName } from "@/lib/localizedField";
import { categoricalLabel } from "@/modules/signals/lib/signalLabels";
import { downloadCsv, toCsv, type CsvCell } from "@/lib/csv";
import { useReportCustomFields, useSignalDetailsReport } from "@/queries/reports";

import { fieldLabel } from "../customFields";
import type { ReportProps } from "../registry";
import { ReportShell } from "./ReportShell";

/** How a signal's stored value reads on the page.
 *
 * Branches on `value_kind` rather than on which column happens to be non-null:
 * `false` and `0` are real readings, and a "first non-null wins" render turns
 * both into an em dash. */
// `lang` is threaded in rather than read from the i18n singleton so the cell
// re-renders when the language changes, and so the CSV export can ask for the
// same string the table shows.
function renderValue(row: SignalDetailRow, noValue: string, lang?: string): string {
  const unit = localizedField(lang, row.unit, row.unit_ar);
  const categorical =
    row.value_categorical === null ? null : categoricalLabel(lang, row, row.value_categorical);
  switch (row.value_kind) {
    case "numeric":
      return row.value_numeric === null
        ? noValue
        : unit
          ? `${row.value_numeric} ${unit}`
          : row.value_numeric;
    case "boolean":
      return row.value_boolean === null ? noValue : row.value_boolean ? "✓" : "✗";
    case "categorical":
      return categorical ?? noValue;
    case "event":
      return row.value_event ?? noValue;
    default:
      // geopoint and anything added later: the coordinates live in a column
      // this table does not carry, so say the reading exists rather than
      // printing an em dash that reads as "nothing was recorded".
      return categorical ?? row.value_event ?? noValue;
  }
}

/**
 * Signal Details — every custom-signal observation on a farm, filtered.
 *
 * The other six reports collapse signals to one number per block. This one
 * does not collapse at all: it is the report for "show me the readings", with
 * the filters that make a season of scouting answerable — which signals, which
 * blocks, which values, who recorded them, and whether they carry a note or a
 * photo.
 */
export function SignalDetailsReport({ farmId, since, until }: ReportProps): ReactNode {
  const { t, i18n } = useTranslation("reports");

  const [signalCodes, setSignalCodes] = useState<string[]>([]);
  const [blockIds, setBlockIds] = useState<string[]>([]);
  const [values, setValues] = useState<string[]>([]);
  const [minValue, setMinValue] = useState("");
  const [maxValue, setMaxValue] = useState("");
  const [withNotesOnly, setWithNotesOnly] = useState(false);
  const [withAttachmentOnly, setWithAttachmentOnly] = useState(false);

  // The signal half of the custom-field catalog doubles as this report's
  // signal filter: it is already farm-scoped, already two-tier resolved, and
  // already carries the categorical options.
  const catalogQ = useReportCustomFields(farmId);
  const signalDefs = useMemo(
    () => (catalogQ.data?.fields ?? []).filter((f) => f.source === "signal"),
    [catalogQ.data],
  );

  const blocksQ = useQuery({
    queryKey: ["blocks", "for-signal-report", farmId] as const,
    queryFn: () => listBlocks(farmId, { limit: 200 }),
    enabled: Boolean(farmId),
    staleTime: 5 * 60_000,
  });
  const blocks = blocksQ.data?.items ?? [];

  // Value options come from the picked signals only. Offering every option in
  // the catalog would list pest species next to phenology stages, and picking
  // one across signals that do not share it silently empties the table.
  const valueOptions = useMemo(() => {
    const picked = signalDefs.filter(
      (d) => signalCodes.length === 0 || signalCodes.includes(d.code),
    );
    const seen = new Map<string, string>();
    for (const def of picked) {
      for (const option of def.options ?? []) {
        if (!seen.has(option.code)) seen.set(option.code, option.name_en || option.code);
      }
    }
    return [...seen.entries()].map(([code, label]) => ({ code, label }));
  }, [signalDefs, signalCodes]);

  const { data, isLoading, isError } = useSignalDetailsReport(farmId, {
    since,
    until,
    ...(signalCodes.length > 0 ? { signal_code: signalCodes } : {}),
    ...(blockIds.length > 0 ? { block_id: blockIds } : {}),
    ...(values.length > 0 ? { value: values } : {}),
    ...(minValue.trim() ? { min_value: minValue.trim() } : {}),
    ...(maxValue.trim() ? { max_value: maxValue.trim() } : {}),
    ...(withNotesOnly ? { with_notes_only: true } : {}),
    ...(withAttachmentOnly ? { with_attachment_only: true } : {}),
  });

  const noValue = "—";

  const handleExport = (): void => {
    if (!data) return;
    const headers = [
      t("signalDetails.headers.observed"),
      t("signalDetails.headers.signal"),
      t("signalDetails.headers.value"),
      t("signalDetails.headers.unit"),
      t("signalDetails.headers.block"),
      t("signalDetails.headers.crop"),
      t("signalDetails.headers.recordedBy"),
      t("signalDetails.headers.notes"),
      t("signalDetails.headers.location"),
      t("signalDetails.headers.attachment"),
    ];
    const rows: CsvCell[][] = data.rows.map((r) => [
      r.observed_at,
      localizedName(i18n.language, r.signal_name, r.signal_name_ar),
      // The raw stored value, not the rendered one: a CSV column of
      // "12 count" does not sum in a spreadsheet.
      r.value_numeric ?? r.value_categorical ?? r.value_event ?? boolText(r.value_boolean),
      localizedField(i18n.language, r.unit, r.unit_ar) ?? "",
      localizedField(i18n.language, r.block_name, r.block_name_ar) ?? "",
      r.crop_path ?? "",
      localizedField(i18n.language, r.recorded_by_name, r.recorded_by_name_ar) ?? "",
      r.notes ?? "",
      r.location_mode,
      r.has_attachment ? "1" : "0",
    ]);
    downloadCsv(`signal-details_${since.slice(0, 10)}_${until.slice(0, 10)}`, toCsv(headers, rows));
  };

  const clearFilters = (): void => {
    setSignalCodes([]);
    setBlockIds([]);
    setValues([]);
    setMinValue("");
    setMaxValue("");
    setWithNotesOnly(false);
    setWithAttachmentOnly(false);
  };

  const hasFilters =
    signalCodes.length > 0 ||
    blockIds.length > 0 ||
    values.length > 0 ||
    minValue.trim() !== "" ||
    maxValue.trim() !== "" ||
    withNotesOnly ||
    withAttachmentOnly;

  return (
    <ReportShell
      title={t("catalog.signal-details.title")}
      farmName={data ? localizedName(i18n.language, data.farm_name, data.farm_name_ar) : undefined}
      period={{ since, until }}
      onExportCsv={data && data.rows.length > 0 ? handleExport : undefined}
    >
      <div className="print-hide mb-4 flex flex-wrap items-end gap-3">
        <MultiSelect
          label={t("signalDetails.filters.signal")}
          allLabel={t("signalDetails.filters.allSignals")}
          options={signalDefs.map((def: CustomFieldDef) => ({
            value: def.code,
            label: fieldLabel(def, i18n.language),
          }))}
          value={signalCodes}
          onChange={setSignalCodes}
        />
        <MultiSelect
          label={t("signalDetails.filters.block")}
          allLabel={t("signalDetails.filters.allBlocks")}
          options={blocks.map((b) => ({ value: b.id, label: b.name ?? b.code ?? b.id }))}
          value={blockIds}
          onChange={setBlockIds}
        />
        {valueOptions.length > 0 ? (
          <MultiSelect
            label={t("signalDetails.filters.value")}
            allLabel={t("signalDetails.filters.allValues")}
            options={valueOptions.map((o) => ({ value: o.code, label: o.label }))}
            value={values}
            onChange={setValues}
          />
        ) : null}
        <label className="flex flex-col gap-1">
          <span className="label mb-0">{t("signalDetails.filters.min")}</span>
          <input
            className="input w-24"
            type="number"
            inputMode="decimal"
            value={minValue}
            onChange={(e) => setMinValue(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="label mb-0">{t("signalDetails.filters.max")}</span>
          <input
            className="input w-24"
            type="number"
            inputMode="decimal"
            value={maxValue}
            onChange={(e) => setMaxValue(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-ap-ink">
          <input
            type="checkbox"
            checked={withNotesOnly}
            onChange={(e) => setWithNotesOnly(e.target.checked)}
          />
          {t("signalDetails.filters.withNotes")}
        </label>
        <label className="flex items-center gap-1.5 text-xs text-ap-ink">
          <input
            type="checkbox"
            checked={withAttachmentOnly}
            onChange={(e) => setWithAttachmentOnly(e.target.checked)}
          />
          {t("signalDetails.filters.withAttachment")}
        </label>
        {hasFilters ? (
          <button
            type="button"
            className="text-xs text-ap-accent hover:underline"
            onClick={clearFilters}
          >
            {t("signalDetails.filters.clear")}
          </button>
        ) : null}
      </div>

      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : isError ? (
        <p className="py-8 text-center text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : !data || data.rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-ap-muted">
          {hasFilters ? t("signalDetails.emptyFiltered") : t("signalDetails.empty")}
        </p>
      ) : (
        <>
          {data.summary.truncated ? (
            // The stats below are computed over the returned page. Saying so
            // is not a nicety: a mean presented as the period's mean, taken
            // over a cut-off page, is a number somebody acts on.
            <p className="mb-3 rounded-lg border border-ap-warn/40 bg-ap-warn-soft px-3 py-2 text-xs text-ap-warn">
              {t("signalDetails.truncated", { count: data.rows.length })}
            </p>
          ) : null}
          <SummaryRow
            observations={data.summary.observation_count}
            signals={data.summary.signal_count}
            blocks={data.summary.block_count}
            recorders={data.summary.recorder_count}
          />
          <StatsTable stats={data.stats} />
          <ObservationsTable rows={data.rows} noValue={noValue} />
        </>
      )}
    </ReportShell>
  );
}

function boolText(value: boolean | null): string {
  if (value === null) return "";
  return value ? "true" : "false";
}

function SummaryRow({
  observations,
  signals,
  blocks,
  recorders,
}: {
  observations: number;
  signals: number;
  blocks: number;
  recorders: number;
}): ReactNode {
  const { t } = useTranslation("reports");
  const cards: Array<[string, number]> = [
    [t("signalDetails.cards.observations"), observations],
    [t("signalDetails.cards.signals"), signals],
    [t("signalDetails.cards.blocks"), blocks],
    [t("signalDetails.cards.recorders"), recorders],
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

function StatsTable({ stats }: { stats: SignalDetailStat[] }): ReactNode {
  const { t, i18n } = useTranslation("reports");
  if (stats.length === 0) return null;
  return (
    <div className="mb-5">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ap-muted">
        {t("signalDetails.statsTitle")}
      </h3>
      <Table>
        <Thead className="text-[11px]">
          <Tr>
            <Th scope="col">{t("signalDetails.headers.signal")}</Th>
            <Th scope="col" className="text-end">
              {t("signalDetails.headers.count")}
            </Th>
            <Th scope="col" className="text-end">
              {t("signalDetails.headers.blocks")}
            </Th>
            <Th scope="col" className="text-end">
              {t("signalDetails.headers.range")}
            </Th>
            <Th scope="col" className="text-end">
              {t("signalDetails.headers.mean")}
            </Th>
            <Th scope="col">{t("signalDetails.headers.breakdown")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {stats.map((s) => (
            <Tr key={s.signal_code}>
              <Td className="text-ap-ink" dir="auto">
                <div className="font-medium">
                  {localizedName(i18n.language, s.signal_name, s.signal_name_ar)}
                </div>
                <div className="text-[11px] text-ap-muted">
                  {s.last_observed_at.slice(0, 10)}
                  {s.unit ? ` · ${s.unit}` : ""}
                </div>
              </Td>
              <Td className="text-end tabular-nums text-ap-ink">{s.observation_count}</Td>
              <Td className="text-end tabular-nums">{s.block_count || "—"}</Td>
              <Td className="text-end tabular-nums">
                {s.min_value !== null && s.max_value !== null
                  ? `${s.min_value} – ${s.max_value}`
                  : "—"}
              </Td>
              <Td className="text-end tabular-nums text-ap-ink">{s.mean_value ?? "—"}</Td>
              <Td>
                {s.categories.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {s.categories.map((c) => (
                      <span
                        key={c.value}
                        className="rounded bg-ap-bg px-1.5 py-0.5 text-[11px] text-ap-ink"
                        dir="auto"
                      >
                        {c.value} · {c.count}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-ap-muted">—</span>
                )}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </div>
  );
}

function ObservationsTable({
  rows,
  noValue,
}: {
  rows: SignalDetailRow[];
  noValue: string;
}): ReactNode {
  const { t, i18n } = useTranslation("reports");
  return (
    <div className="overflow-x-auto">
      <Table>
        <Thead className="text-[11px]">
          <Tr>
            <Th scope="col">{t("signalDetails.headers.observed")}</Th>
            <Th scope="col">{t("signalDetails.headers.signal")}</Th>
            <Th scope="col" className="text-end">
              {t("signalDetails.headers.value")}
            </Th>
            <Th scope="col">{t("signalDetails.headers.block")}</Th>
            <Th scope="col">{t("signalDetails.headers.recordedBy")}</Th>
            <Th scope="col">{t("signalDetails.headers.notes")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {rows.map((r) => (
            <Tr key={r.observation_id} className="hover:bg-ap-bg/40">
              <Td className="whitespace-nowrap text-[11px] text-ap-muted">
                {r.observed_at.slice(0, 16).replace("T", " ")}
              </Td>
              <Td className="text-ap-ink" dir="auto">
                {localizedName(i18n.language, r.signal_name, r.signal_name_ar)}
              </Td>
              <Td className="text-end tabular-nums font-medium text-ap-ink" dir="auto">
                {renderValue(r, noValue, i18n.language)}
              </Td>
              <Td className="text-ap-ink" dir="auto">
                {/* No block means a farm-level reading, which is a real shape
                    here — not missing data. */}
                {localizedField(i18n.language, r.block_name, r.block_name_ar) ?? (
                  <span className="text-ap-muted">{t("signalDetails.farmLevel")}</span>
                )}
              </Td>
              <Td className="text-[11px] text-ap-muted" dir="auto">
                {localizedField(i18n.language, r.recorded_by_name, r.recorded_by_name_ar) ??
                  noValue}
              </Td>
              <Td className="max-w-xs text-[11px] text-ap-muted" dir="auto">
                {r.notes ? <span className="line-clamp-2">{r.notes}</span> : noValue}
                {r.has_attachment ? (
                  <span className="ms-1" title={t("signalDetails.headers.attachment")}>
                    📎
                  </span>
                ) : null}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </div>
  );
}

/**
 * A plain multi-select. No dropdown-with-checkboxes here: these lists are
 * short (a farm's signals, a farm's blocks), and a native multiple select
 * keeps keyboard behaviour and screen-reader semantics for free.
 */
function MultiSelect({
  label,
  allLabel,
  options,
  value,
  onChange,
}: {
  label: string;
  allLabel: string;
  options: Array<{ value: string; label: string }>;
  value: string[];
  onChange: (next: string[]) => void;
}): ReactNode {
  if (options.length === 0) return null;
  return (
    <label className="flex flex-col gap-1">
      <span className="label mb-0">
        {label}
        {value.length === 0 ? <span className="ms-1 text-ap-muted">({allLabel})</span> : null}
      </span>
      <select
        multiple
        className="input h-20 w-44"
        value={value}
        onChange={(e) => onChange([...e.target.selectedOptions].map((option) => option.value))}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
