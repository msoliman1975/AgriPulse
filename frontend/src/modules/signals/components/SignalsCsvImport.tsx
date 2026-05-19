import { useCallback, useId, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import {
  importSignalObservationsCsv,
  type CsvImportRowError,
  type CsvImportSuccess,
} from "@/api/signals";

interface Props {
  farmId: string;
}

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

  const mutation = useMutation({
    mutationFn: (file: File) => importSignalObservationsCsv(farmId, file),
    onMutate: () => {
      setRowErrors([]);
      setTopLevelError(null);
      setSuccess(null);
    },
    onSuccess: (data) => {
      setSuccess(data);
      // The observations list + the map overlay both key on the
      // observations endpoint — invalidate so a freshly-imported batch
      // shows up without a hard reload.
      void queryClient.invalidateQueries({ queryKey: ["signals", "observations"] });
      void queryClient.invalidateQueries({ queryKey: ["labs", "map"] });
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
        <a
          href={SAMPLE_CSV_URL}
          download="signal-observations-sample.csv"
          className="text-[11px] text-ap-primary hover:underline"
        >
          {t("csvImport.sampleLink")}
        </a>
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
        <p className="text-[10px] text-ap-muted">{t("csvImport.limits")}</p>
      </div>

      {mutation.isPending ? (
        <p className="mt-3 text-xs text-ap-muted">{t("csvImport.uploading")}</p>
      ) : null}

      {success ? (
        <p
          role="status"
          className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-800"
        >
          {t("csvImport.success", { count: success.rows_imported })}
        </p>
      ) : null}

      {topLevelError && rowErrors.length === 0 ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-800"
        >
          {topLevelError}
        </p>
      ) : null}

      {rowErrors.length > 0 ? (
        <div className="mt-3">
          <p role="alert" className="text-xs font-semibold text-rose-800">
            {t("csvImport.failureBanner", { count: rowErrors.length })}
          </p>
          <table className="mt-2 min-w-full border border-rose-200 text-xs">
            <thead className="bg-rose-50 text-rose-800">
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
                <tr key={`${e.row_number}-${i}`} className="border-t border-rose-100">
                  <td className="px-2 py-1 tabular-nums text-rose-700">{e.row_number}</td>
                  <td className="px-2 py-1 text-rose-700">{e.field ?? "—"}</td>
                  <td className="px-2 py-1 text-rose-700">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-ap-muted">{t("csvImport.failureHint")}</p>
        </div>
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
