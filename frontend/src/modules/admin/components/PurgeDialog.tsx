import type { ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PurgeJob, PurgeKind, PurgePreview } from "@/api/purge";
import { Modal } from "@/components/Modal";
import { usePurgePreview, useSubmitPurge } from "@/queries/admin/purge";

export interface PurgeTarget {
  kind: PurgeKind;
  id: string;
  tenantId: string;
  label: string;
}

interface Props {
  target: PurgeTarget | null;
  onClose: () => void;
}

/**
 * The single confirm surface for every purge kind.
 *
 * Three sections, in the order an admin needs them: what will be deleted (from
 * the server's preview, so the numbers can't drift from what the delete does),
 * then the typed confirmation, then the buttons. Dry run is a first-class
 * button rather than a checkbox — during a testing phase it is the control that
 * makes the feature trustworthy, so it should not be hidden behind a toggle.
 */
export function PurgeDialog({ target, onClose }: Props): ReactNode {
  const { t } = useTranslation("admin");
  const preview = usePurgePreview(target);
  const submit = useSubmitPurge(target?.tenantId);

  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<PurgeJob | null>(null);

  const close = (): void => {
    setConfirmation("");
    setReason("");
    setResult(null);
    submit.reset();
    onClose();
  };

  const data = preview.data;
  const blocked = (data?.blocking.length ?? 0) > 0;
  const phraseMatches = Boolean(data && confirmation === data.confirmation_phrase);

  const run = (dryRun: boolean): void => {
    if (!target || !data) return;
    submit.mutate(
      {
        kind: target.kind,
        id: target.id,
        tenant_id: target.tenantId,
        confirmation: data.confirmation_phrase,
        reason: reason.trim() || null,
        dry_run: dryRun,
      },
      { onSuccess: (job) => setResult(job) },
    );
  };

  return (
    <Modal
      open={Boolean(target)}
      onClose={close}
      labelledBy="purge-dialog-title"
      className="max-w-2xl"
    >
      <h2 id="purge-dialog-title" className="text-lg font-semibold text-ap-crit">
        {t(`purge.dialog.title.${target?.kind ?? "block"}`, { label: target?.label ?? "" })}
      </h2>

      {result ? (
        <PurgeResult job={result} onDone={close} />
      ) : (
        <>
          <p className="mt-2 text-sm text-ap-ink">{t("purge.dialog.irreversible")}</p>

          {preview.isLoading ? (
            <p className="mt-4 text-sm text-ap-muted">{t("purge.dialog.loading")}</p>
          ) : preview.isError || !data ? (
            <p role="alert" className="mt-4 text-sm text-ap-crit">
              {t("purge.dialog.previewError")}
            </p>
          ) : (
            <>
              {blocked ? (
                <div
                  role="alert"
                  className="mt-4 rounded-md border border-ap-warn/30 bg-ap-warn-soft p-3 text-sm text-ap-warn"
                >
                  {data.blocking.map((b) => (
                    <p key={b.reason}>{b.detail}</p>
                  ))}
                  <p className="mt-1 text-xs text-ap-warn/80">{t("purge.dialog.dryRunStillOk")}</p>
                </div>
              ) : null}

              <ImpactTable preview={data} />

              <label className="mt-4 block text-sm">
                <span className="block text-xs font-semibold uppercase tracking-wide text-ap-muted">
                  {t("purge.dialog.confirmLabel")}{" "}
                  <code className="font-mono text-ap-ink">{data.confirmation_phrase}</code>
                </span>
                <input
                  type="text"
                  value={confirmation}
                  onChange={(e) => setConfirmation(e.target.value)}
                  autoComplete="off"
                  className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 font-mono text-sm shadow-sm"
                />
              </label>

              <label className="mt-3 block text-sm">
                <span className="block text-xs font-semibold uppercase tracking-wide text-ap-muted">
                  {t("purge.dialog.reasonLabel")}
                </span>
                <input
                  type="text"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
                />
              </label>
            </>
          )}

          {submit.isError ? (
            <p role="alert" className="mt-3 text-sm text-ap-crit">
              {t("purge.dialog.submitError")}
            </p>
          ) : null}

          {/* The banner at the top of the dialog scrolls out of view by the time
              you have typed the confirmation, so a disabled button down here
              reads as broken. Repeat the reason where the control actually is. */}
          {data && blocked ? (
            <p
              id="purge-blocked-hint"
              className="mt-4 flex items-start gap-1.5 text-sm text-ap-warn"
            >
              <span aria-hidden="true">⚠</span>
              <span>
                {data.blocking
                  .map((b) =>
                    t(`purge.dialog.blockedShort.${b.reason}`, {
                      defaultValue: b.detail,
                      kind: t(`purge.dialog.kindNoun.${data.kind}`),
                    }),
                  )
                  .join(" ")}
              </span>
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => run(true)}
              disabled={!data || submit.isPending}
              className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
            >
              {t("purge.dialog.dryRun")}
            </button>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={close}
                className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-muted hover:bg-ap-line/40"
              >
                {t("purge.dialog.cancel")}
              </button>
              <button
                type="button"
                onClick={() => run(false)}
                disabled={!phraseMatches || blocked || submit.isPending}
                aria-describedby={blocked ? "purge-blocked-hint" : undefined}
                className="rounded-md bg-ap-crit px-3 py-2 text-sm font-medium text-white hover:bg-ap-crit/90 disabled:opacity-60"
              >
                {submit.isPending ? t("purge.dialog.working") : t("purge.dialog.confirm")}
              </button>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}

function ImpactTable({ preview }: { preview: PurgePreview }): ReactNode {
  const { t } = useTranslation("admin");
  const [expanded, setExpanded] = useState(false);
  const rows = expanded ? preview.db_rows : preview.db_rows.slice(0, 5);
  const kept = preview.storage.imagery_objects_kept_shared;

  return (
    <div className="mt-4 rounded-md border border-ap-line bg-ap-bg p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ap-muted">
        {t("purge.dialog.impactTitle")}
      </h3>
      <ul className="mt-2 space-y-1 text-sm text-ap-ink">
        <li>
          {t("purge.dialog.impact.rows", {
            rows: preview.total_rows.toLocaleString(),
            tables: preview.db_rows.length,
          })}
        </li>
        <li>
          {t("purge.dialog.impact.objects", {
            count: preview.storage.attachment_objects + preview.storage.imagery_objects,
          })}
          {kept > 0 ? (
            <span className="ml-1 text-xs text-ap-muted">
              {t("purge.dialog.impact.keptShared", { count: kept })}
            </span>
          ) : null}
        </li>
        {preview.pgstac.items > 0 || preview.pgstac.collections > 0 ? (
          <li>
            {t("purge.dialog.impact.stac", {
              items: preview.pgstac.items,
              collections: preview.pgstac.collections,
            })}
          </li>
        ) : null}
      </ul>

      {preview.db_rows.length > 0 ? (
        <>
          <table className="mt-3 w-full text-xs">
            <tbody>
              {rows.map((r) => (
                <tr key={r.table} className="border-t border-ap-line/60">
                  <td className="py-1 font-mono text-ap-muted">{r.table}</td>
                  <td className="py-1 text-right tabular-nums text-ap-ink">
                    {r.rows.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.db_rows.length > 5 ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-2 text-xs font-medium text-ap-accent hover:underline"
            >
              {expanded
                ? t("purge.dialog.impact.collapse")
                : t("purge.dialog.impact.expand", { count: preview.db_rows.length - 5 })}
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

/** Receipt card. Red when the verification scan found residue. */
function PurgeResult({ job, onDone }: { job: PurgeJob; onDone: () => void }): ReactNode {
  const { t } = useTranslation("admin");
  const receipt = job.receipt;
  const orphans = Number(receipt?.verification?.orphans_found ?? 0);
  const clean = job.status === "succeeded" && orphans === 0;
  const deleted = (receipt?.deleted ?? {}) as Record<string, number | string | boolean>;

  return (
    <div
      className={`mt-4 rounded-md border p-3 text-sm ${
        clean
          ? "border-ap-ok/30 bg-ap-ok-soft text-ap-ink"
          : "border-ap-crit/30 bg-ap-crit-soft text-ap-ink"
      }`}
    >
      <p className="font-semibold">
        {job.dry_run
          ? t("purge.result.dryRunTitle")
          : clean
            ? t("purge.result.doneTitle", { label: job.target_label ?? "" })
            : t("purge.result.problemTitle")}
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        <li>
          {t("purge.result.rows", { rows: Number(deleted.total_rows ?? 0).toLocaleString() })}
        </li>
        {job.dry_run ? null : (
          <li>{t("purge.result.objects", { count: Number(deleted.storage_objects ?? 0) })}</li>
        )}
        <li className={orphans === 0 ? "" : "font-semibold text-ap-crit"}>
          {job.dry_run
            ? t("purge.result.verificationSkipped")
            : t("purge.result.verification", {
                orphans,
                tables: Number(receipt?.verification?.scanned_tables ?? 0),
              })}
        </li>
      </ul>
      {receipt?.errors?.length ? (
        <ul className="mt-2 list-disc space-y-0.5 ps-5 text-xs text-ap-crit">
          {receipt.errors.slice(0, 5).map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      ) : null}
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={onDone}
          className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("purge.result.close")}
        </button>
      </div>
    </div>
  );
}
