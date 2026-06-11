import { useCallback, useId, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import {
  importSignalObservationsCsv,
  type CsvImportRowError,
  type CsvImportSuccess,
} from "@/api/signals";
import { Modal } from "@/components/Modal";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  farmId: string;
}

// Columns the importer understands. signal_code + observed_at are
// required; the rest are optional (CS-12 added the location / attachment /
// template ones). Descriptions are i18n keys under csvImport.schema.col.*.
const CSV_COLUMNS: { name: string; required: boolean }[] = [
  { name: "signal_code", required: true },
  { name: "observed_at", required: true },
  { name: "block_id", required: false },
  { name: "value_numeric", required: false },
  { name: "value_categorical", required: false },
  { name: "value_event", required: false },
  { name: "value_boolean", required: false },
  { name: "notes", required: false },
  { name: "location_mode", required: false },
  { name: "location_point_lat", required: false },
  { name: "location_point_lon", required: false },
  { name: "attachment_s3_key", required: false },
  { name: "template_code", required: false },
  { name: "template_member_position", required: false },
];

/**
 * CSV-import widget for the Signals Configuration page. Wraps the
 * existing /signals/csv-import endpoint (CS-7) with a drag-drop file
 * picker, an inline result summary, and a per-row error table when
 * the batch is rejected.
 *
 * Strict mode: any row error → whole batch rejected → operator
 * fixes locally and re-uploads. The form does not retry partial
 * batches; that's the API's contract.
 *
 * Schema hint + a tiny "download sample CSV" link live above the
 * dropzone so the operator doesn't have to dig into the API docs to
 * find the column names.
 */
export function SignalsCsvImport({ farmId }: Props): ReactNode {
  const { t } = useTranslation("signals");
  const inputId = useId();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [rowErrors, setRowErrors] = useState<CsvImportRowError[]>([]);
  const [topLevelError, setTopLevelError] = useState<string | null>(null);
  const [success, setSuccess] = useState<CsvImportSuccess | null>(null);
  const [bulkMode, setBulkMode] = useState(false);
  const [showSchema, setShowSchema] = useState(false);
  // Bulk mode is a backfill action — gated on signal.define (the route
  // additionally requires it server-side).
  const canBulk = useCapability("signal.define", { farmId });

  const mutation = useMutation({
    mutationFn: (file: File) => importSignalObservationsCsv(farmId, file, bulkMode && canBulk),
    onMutate: () => {
      setRowErrors([]);
      setTopLevelError(null);
      setSuccess(null);
    },
    onSuccess: (data) => {
      setSuccess(data);
      // Refresh the views that show observations so a freshly-imported
      // batch appears without a hard reload. Keys must match the actual
      // queries: the log table + hooks use ["signal_observations", …]
      // (ObservationList.tsx, queries/signals.ts) and the map overlay
      // uses ["labs/map/signalObservations", …] (MapExperiencePage.tsx).
      // The previous keys (["signals","observations"], ["labs","map"])
      // matched nothing, so the table only updated on a full refresh.
      void queryClient.invalidateQueries({ queryKey: ["signal_observations"] });
      void queryClient.invalidateQueries({ queryKey: ["labs/map/signalObservations"] });
    },
    onError: (err) => {
      const parsed = _parseError(err);
      if (parsed.rowErrors.length > 0) {
        setRowErrors(parsed.rowErrors);
      }
      setTopLevelError(parsed.message);
    },
  });

  const handleFile = useCallback(
    (file: File | null) => {
      if (!file) return;
      mutation.mutate(file);
    },
    [mutation],
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files?.[0] ?? null;
      handleFile(file);
    },
    [handleFile],
  );

  return (
    <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ap-muted">
          {t("csvImport.title")}
        </h2>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowSchema(true)}
            className="text-[11px] text-ap-primary hover:underline"
          >
            {t("csvImport.schema.link")}
          </button>
          <a
            href={SAMPLE_CSV_URL}
            download="signal-observations-sample.csv"
            className="text-[11px] text-ap-primary hover:underline"
          >
            {t("csvImport.sampleLink")}
          </a>
        </div>
      </header>
      <p className="mt-1 text-xs text-ap-muted">{t("csvImport.subtitle")}</p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={
          "mt-3 flex flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed px-4 py-8 text-center text-sm " +
          (dragOver
            ? "border-ap-primary bg-ap-primary/10"
            : "border-ap-line bg-ap-bg/40 text-ap-muted")
        }
      >
        <p>{t("csvImport.dropPrompt")}</p>
        <label htmlFor={inputId} className="cursor-pointer text-xs text-ap-primary underline">
          {t("csvImport.browseLink")}
          <input
            ref={inputRef}
            id={inputId}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            disabled={mutation.isPending}
            onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <p className="text-[10px] text-ap-muted">
          {bulkMode && canBulk ? t("csvImport.limitsBulk") : t("csvImport.limits")}
        </p>
      </div>

      <label
        className={
          "mt-2 flex items-center gap-2 text-xs " +
          (canBulk ? "text-ap-ink" : "text-ap-muted")
        }
        title={canBulk ? t("csvImport.bulkMode.tooltip") : t("csvImport.bulkMode.needsCap")}
      >
        <input
          type="checkbox"
          checked={bulkMode && canBulk}
          disabled={!canBulk || mutation.isPending}
          onChange={(e) => setBulkMode(e.target.checked)}
        />
        {t("csvImport.bulkMode.label")}
      </label>

      {mutation.isPending ? (
        <p className="mt-3 text-xs text-ap-muted">{t("csvImport.uploading")}</p>
      ) : null}

      {success ? (
        <p
          role="status"
          className="mt-3 rounded-md border border-ap-primary/30 bg-ap-primary-soft p-2 text-xs text-ap-primary"
        >
          {t("csvImport.success", { count: success.rows_imported })}
        </p>
      ) : null}

      {topLevelError && rowErrors.length === 0 ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-ap-crit/30 bg-ap-crit-soft p-2 text-xs text-ap-crit"
        >
          {topLevelError}
        </p>
      ) : null}

      {rowErrors.length > 0 ? (
        <div className="mt-3">
          <p role="alert" className="text-xs font-semibold text-ap-crit">
            {t("csvImport.failureBanner", { count: rowErrors.length })}
          </p>
          <table className="mt-2 min-w-full border border-ap-crit/30 text-xs">
            <thead className="bg-ap-crit-soft text-ap-crit">
              <tr>
                <th scope="col" className="px-2 py-1 text-start font-semibold">
                  {t("csvImport.errorTable.row")}
                </th>
                <th scope="col" className="px-2 py-1 text-start font-semibold">
                  {t("csvImport.errorTable.field")}
                </th>
                <th scope="col" className="px-2 py-1 text-start font-semibold">
                  {t("csvImport.errorTable.message")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rowErrors.map((e, i) => (
                <tr key={`${e.row_number}-${i}`} className="border-t border-ap-crit/20">
                  <td className="px-2 py-1 tabular-nums text-ap-crit">{e.row_number}</td>
                  <td className="px-2 py-1 text-ap-crit">{e.field ?? "—"}</td>
                  <td className="px-2 py-1 text-ap-crit">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-ap-muted">{t("csvImport.failureHint")}</p>
        </div>
      ) : null}

      {showSchema ? (
        <Modal
          open
          onClose={() => setShowSchema(false)}
          labelledBy="csv-schema-title"
          className="max-w-lg p-4"
        >
          <div className="flex items-baseline justify-between">
            <h3 id="csv-schema-title" className="text-sm font-semibold text-ap-ink">
              {t("csvImport.schema.title")}
            </h3>
            <button
              type="button"
              onClick={() => setShowSchema(false)}
              className="text-xs text-ap-muted hover:text-ap-ink"
            >
              {t("csvImport.schema.close")}
            </button>
          </div>
          <p className="mt-1 text-xs text-ap-muted">{t("csvImport.schema.intro")}</p>
          <table className="mt-3 min-w-full text-xs">
            <tbody>
              {CSV_COLUMNS.map((c) => (
                <tr key={c.name} className="border-t border-ap-line align-top">
                  <td className="px-2 py-1 font-mono text-ap-ink">
                    {c.name}
                    {c.required ? <span className="text-ap-crit"> *</span> : null}
                  </td>
                  <td className="px-2 py-1 text-ap-muted">{t(`csvImport.schema.col.${c.name}`)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-ap-muted">{t("csvImport.schema.requiredNote")}</p>
        </Modal>
      ) : null}
    </section>
  );
}

// In-page sample CSV. Data URL avoids a static-asset round trip and
// keeps the column set in lockstep with backend csv_import.py.
const SAMPLE_CSV = `signal_code,observed_at,block_id,value_numeric,value_categorical,value_event,value_boolean,notes
soil_ph,2026-05-18T08:00:00+00:00,,6.7,,,,morning sample
scout_severity,2026-05-18T09:00:00+00:00,,,high,,,
`;
const SAMPLE_CSV_URL = `data:text/csv;charset=utf-8,${encodeURIComponent(SAMPLE_CSV)}`;

export function _parseError(err: unknown): {
  message: string;
  rowErrors: CsvImportRowError[];
} {
  // The apiClient surfaces FastAPI's Problem-JSON shape unchanged.
  // CsvImportFailedError → 422 with extras.errors; CsvImportTooLargeError
  // → 413 with extras.size_bytes/limit_bytes.
  if (isAxiosError(err)) {
    const body = err.response?.data as
      | { detail?: string; title?: string; extras?: Record<string, unknown> }
      | undefined;
    const extras = body?.extras as
      | { errors?: CsvImportRowError[]; size_bytes?: number; limit_bytes?: number }
      | undefined;
    if (extras?.errors && Array.isArray(extras.errors)) {
      return {
        message: body?.detail ?? body?.title ?? "Import failed.",
        rowErrors: extras.errors,
      };
    }
    if (extras?.size_bytes && extras?.limit_bytes) {
      return {
        message: `File too large (${extras.size_bytes} bytes, max ${extras.limit_bytes}).`,
        rowErrors: [],
      };
    }
    return {
      message: body?.detail ?? body?.title ?? err.message,
      rowErrors: [],
    };
  }
  return {
    message: err instanceof Error ? err.message : "Unknown error.",
    rowErrors: [],
  };
}
