// Bulk AOI upload — Farm Console "+ Add ▾ → Upload AOI files…".
//
// A wide left-docked panel over the console map: drop many AOI files, review
// an editable table (code/name/status/errors), and commit. Each parsed polygon
// is a candidate block; the panel classifies it against the farm's existing
// blocks (new / reuse / replace / error) and paints a color-coded preview on
// the map behind it via onPreviewChange. Commit calls the /blocks:bulk
// reconcile — identity is the code, and a destructive replace is gated on an
// explicit confirmation here + the delete capability server-side.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { FeatureCollection, Polygon } from "geojson";

import { bulkCreateBlocks, type BulkBlockResultRow } from "@/api/blocks";
import {
  classifyRows,
  deriveRowsFromFiles,
  type BulkRow,
  type ClassifiedRow,
  type ExistingBlock,
} from "@/lib/aoi/bulk";
import type { BulkPreviewProps, BulkPreviewStatus } from "../map/MapCanvas";

interface Props {
  farmId: string;
  existing: ExistingBlock[];
  canReplace: boolean;
  onPreviewChange: (fc: FeatureCollection<Polygon, BulkPreviewProps> | null) => void;
  onCommitted: (summary: {
    created: number;
    replaced: number;
    reused: number;
    errors: number;
  }) => void;
  onClose: () => void;
}

const inputCls =
  "w-full rounded-lg border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";
const primaryBtn =
  "h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white disabled:opacity-50 hover:bg-ap-primary/90";
const ghostBtn =
  "h-9 rounded-lg border border-ap-line bg-ap-panel px-3 text-sm font-semibold text-ap-ink hover:bg-ap-primary-soft disabled:opacity-50";

// status → dot color (matches MapCanvas BULK_STATUS_COLOR + legend).
// new=good(green), reuse=muted(gray, a no-op), replace=warn(amber), error=crit(red).
const STATUS_DOT: Record<BulkPreviewStatus, string> = {
  new: "bg-ap-good",
  reuse: "bg-ap-muted",
  replace: "bg-ap-warn",
  error: "bg-ap-crit",
};

const ACCEPT = ".geojson,.json,.zip,.kml";

export function BulkAoiUploadPanel({
  farmId,
  existing,
  canReplace,
  onPreviewChange,
  onCommitted,
  onClose,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [rows, setRows] = useState<BulkRow[]>([]);
  const [parsing, setParsing] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<BulkBlockResultRow[] | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const classified = useMemo(() => classifyRows(rows, existing), [rows, existing]);

  const counts = useMemo(() => {
    const c = { new: 0, reuse: 0, replace: 0, error: 0 };
    for (const r of classified) c[r.status] += 1;
    return c;
  }, [classified]);
  const allowReplace = canReplace && confirmReplace;

  // Rows we will actually submit: new + reuse always; replace only once the
  // destructive action is confirmed (and permitted). Others stay in the table.
  const toSend = useMemo(
    () =>
      classified.filter(
        (r) =>
          r.geometry != null &&
          (r.status === "new" || r.status === "reuse" || (r.status === "replace" && allowReplace)),
      ),
    [classified, allowReplace],
  );

  // Live map preview: color-coded polygons for every row with geometry.
  const previewFc = useMemo<FeatureCollection<Polygon, BulkPreviewProps> | null>(() => {
    const features = classified
      .filter((r) => r.geometry != null)
      .map((r) => ({
        type: "Feature" as const,
        geometry: r.geometry as Polygon,
        properties: { code: r.code, status: r.status },
      }));
    return features.length > 0 ? { type: "FeatureCollection", features } : null;
  }, [classified]);

  useEffect(() => {
    onPreviewChange(previewFc);
  }, [previewFc, onPreviewChange]);
  // Clear the map overlay when the panel unmounts.
  useEffect(() => () => onPreviewChange(null), [onPreviewChange]);

  const addFiles = async (files: FileList | File[]): Promise<void> => {
    const list = Array.from(files);
    if (list.length === 0) return;
    setParsing(true);
    setError(null);
    try {
      const parsed = await deriveRowsFromFiles(list);
      setRows((prev) => [...prev, ...parsed]);
    } finally {
      setParsing(false);
    }
  };

  // Editing the code carries the name along while the name is still the
  // default (name === code); once the user types their own name it sticks.
  const updateRow = (id: string, patch: Partial<BulkRow>): void =>
    setRows((prev) =>
      prev.map((r) => {
        if (r.id !== id) return r;
        const next = { ...r, ...patch };
        if (patch.code !== undefined && patch.name === undefined && r.name === r.code) {
          next.name = patch.code;
        }
        return next;
      }),
    );
  const removeRow = (id: string): void => setRows((prev) => prev.filter((r) => r.id !== id));

  const submit = async (): Promise<void> => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await bulkCreateBlocks(
        farmId,
        toSend.map((r) => ({
          code: r.code,
          name: r.name.trim() || null,
          boundary: r.geometry as Polygon,
        })),
        allowReplace,
      );
      setResults(res.results);
      onCommitted({
        created: res.created,
        replaced: res.replaced,
        reused: res.reused,
        errors: res.errors,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="absolute start-3 top-3 z-30 flex max-h-[calc(100%-1.5rem)] w-[440px] max-w-[94vw] flex-col rounded-2xl border border-ap-line bg-ap-panel shadow-card">
      <div className="flex items-center gap-2 border-b border-ap-line px-4 py-3">
        <span className="text-base">⬆</span>
        <h3 className="text-sm font-bold text-ap-ink">{t("bulk.title")}</h3>
        <button
          type="button"
          onClick={onClose}
          className="ms-auto grid h-7 w-7 place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50"
          aria-label={t("manage.cancel")}
        >
          ✕
        </button>
      </div>

      {results ? (
        <ResultsView results={results} onClose={onClose} t={t} />
      ) : (
        <>
          {/* Dropzone (always available to add more files). Drag-and-drop is
              not discoverable on its own, so the picker also has a button. */}
          <div className="border-b border-ap-line p-3">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                void addFiles(e.dataTransfer.files);
              }}
              className={
                "flex flex-col items-center gap-2 rounded-lg border border-dashed p-3 text-center text-sm " +
                (dragOver ? "border-ap-primary bg-ap-primary-soft" : "border-ap-line text-ap-muted")
              }
            >
              <span>{parsing ? t("bulk.parsing") : t("bulk.drop")}</span>
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={parsing}
                className={ghostBtn}
              >
                {t("bulk.selectFiles")}
              </button>
            </div>
            <input
              id="bulk-aoi-file"
              ref={fileRef}
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              onChange={(e) => {
                if (e.target.files) void addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {rows.length === 0 ? (
            <div className="p-4 text-xs text-ap-muted">{t("bulk.hint")}</div>
          ) : (
            <>
              <Legend counts={counts} t={t} />
              <ul className="min-h-0 flex-1 divide-y divide-ap-line/60 overflow-auto">
                {classified.map((r) => (
                  <RowItem key={r.id} row={r} onChange={updateRow} onRemove={removeRow} t={t} />
                ))}
              </ul>
              <Footer
                counts={counts}
                canReplace={canReplace}
                confirmReplace={confirmReplace}
                onConfirmReplace={setConfirmReplace}
                sendCount={toSend.length}
                submitting={submitting}
                error={error}
                onSubmit={() => void submit()}
                t={t}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}

type TFn = (key: string, opts?: Record<string, unknown>) => string;

function Legend({ counts, t }: { counts: Record<BulkPreviewStatus, number>; t: TFn }): ReactNode {
  const items: BulkPreviewStatus[] = ["new", "reuse", "replace", "error"];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[11px] text-ap-muted">
      {items.map((s) => (
        <span key={s} className="inline-flex items-center gap-1">
          <span className={"h-2.5 w-2.5 rounded-full " + STATUS_DOT[s]} />
          {t(`bulk.status.${s}`)} · {counts[s]}
        </span>
      ))}
    </div>
  );
}

function RowItem({
  row,
  onChange,
  onRemove,
  t,
}: {
  row: ClassifiedRow;
  onChange: (id: string, patch: Partial<BulkRow>) => void;
  onRemove: (id: string) => void;
  t: TFn;
}): ReactNode {
  const isError = row.status === "error";
  return (
    <li className="flex items-start gap-2 px-3 py-2">
      <span
        className={"mt-2 h-2.5 w-2.5 flex-none rounded-full " + STATUS_DOT[row.status]}
        title={t(`bulk.status.${row.status}`)}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <input
            className={inputCls + " font-mono"}
            value={row.code}
            onChange={(e) => onChange(row.id, { code: e.target.value })}
            aria-label={t("bulk.code")}
            disabled={isError && row.clientError !== "duplicate"}
          />
          <input
            className={inputCls}
            value={row.name}
            placeholder={t("bulk.namePlaceholder")}
            onChange={(e) => onChange(row.id, { name: e.target.value })}
            aria-label={t("bulk.name")}
            disabled={isError && row.clientError !== "duplicate"}
          />
          <button
            type="button"
            onClick={() => onRemove(row.id)}
            className="grid h-7 w-7 flex-none place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50"
            aria-label={t("bulk.remove")}
          >
            ✕
          </button>
        </div>
        <div className="mt-0.5 truncate text-[11px] text-ap-muted" title={row.fileName}>
          {row.fileName}
          {row.clientError ? (
            <span className="text-ap-crit"> · {t(`bulk.err.${row.clientError}`)}</span>
          ) : row.status === "replace" ? (
            <span className="text-ap-warn"> · {t("bulk.replaceNote")}</span>
          ) : row.status === "reuse" ? (
            <span className="text-ap-muted"> · {t("bulk.reuseNote")}</span>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function Footer({
  counts,
  canReplace,
  confirmReplace,
  onConfirmReplace,
  sendCount,
  submitting,
  error,
  onSubmit,
  t,
}: {
  counts: Record<BulkPreviewStatus, number>;
  canReplace: boolean;
  confirmReplace: boolean;
  onConfirmReplace: (v: boolean) => void;
  sendCount: number;
  submitting: boolean;
  error: string | null;
  onSubmit: () => void;
  t: TFn;
}): ReactNode {
  return (
    <div className="border-t border-ap-line p-3">
      {counts.replace > 0 ? (
        canReplace ? (
          <label className="mb-2 flex items-start gap-2 rounded-lg bg-ap-warn-soft p-2 text-[11px] text-ap-ink">
            <input
              type="checkbox"
              checked={confirmReplace}
              onChange={(e) => onConfirmReplace(e.target.checked)}
              className="mt-0.5 accent-ap-warn"
            />
            <span>{t("bulk.confirmReplace", { n: counts.replace })}</span>
          </label>
        ) : (
          <div className="mb-2 rounded-lg bg-ap-warn-soft p-2 text-[11px] text-ap-ink">
            {t("bulk.replaceForbidden", { n: counts.replace })}
          </div>
        )
      ) : null}
      {error ? (
        <div className="mb-2 rounded-lg bg-ap-crit/10 px-2 py-1 text-[11px] text-ap-crit">
          {error}
        </div>
      ) : null}
      <button
        type="button"
        onClick={onSubmit}
        disabled={submitting || sendCount === 0}
        className={primaryBtn + " w-full"}
      >
        {submitting ? t("bulk.creating") : t("bulk.create", { n: sendCount })}
      </button>
    </div>
  );
}

function ResultsView({
  results,
  onClose,
  t,
}: {
  results: BulkBlockResultRow[];
  onClose: () => void;
  t: TFn;
}): ReactNode {
  const label = (r: BulkBlockResultRow): string =>
    r.status === "error" && r.error_code
      ? t(`bulk.err.${r.error_code}`)
      : t(`bulk.result.${r.status}`);
  const dot = (r: BulkBlockResultRow): string => {
    if (r.status === "created") return STATUS_DOT.new;
    if (r.status === "reused") return STATUS_DOT.reuse;
    if (r.status === "error") return STATUS_DOT.error;
    return STATUS_DOT.replace; // replaced_deleted / replaced_inactivated
  };
  return (
    <>
      <ul className="min-h-0 flex-1 divide-y divide-ap-line/60 overflow-auto">
        {results.map((r) => (
          <li key={r.index} className="flex items-center gap-2 px-3 py-2 text-sm">
            <span className={"h-2.5 w-2.5 flex-none rounded-full " + dot(r)} />
            <span className="font-mono text-xs text-ap-ink">{r.code}</span>
            <span className="ms-auto text-[11px] text-ap-muted">{label(r)}</span>
          </li>
        ))}
      </ul>
      <div className="border-t border-ap-line p-3">
        <button type="button" onClick={onClose} className={ghostBtn + " w-full"}>
          {t("bulk.done")}
        </button>
      </div>
    </>
  );
}
