import { formatDistanceToNow, parseISO } from "date-fns";
import { Fragment, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill, type PillKind } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import {
  useFarmIntegrationHealth,
  useRecentAttempts,
} from "@/queries/integrationsHealth";
import type {
  AttemptKind,
  AttemptStatus,
  IntegrationAttempt,
} from "@/api/integrationsHealth";

export interface RunsTabProps {
  basePath: string;
}

/**
 * Recent ingestion attempts table (PR-IH3). Reads from
 * `/integrations/health/recent` which unifies weather + imagery rows.
 * Filterable by kind, status, and farm. Row click opens an inline
 * detail row with the full error message.
 */
export function RunsTab({ basePath }: RunsTabProps): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const [kind, setKind] = useState<AttemptKind | "all">("all");
  const [status, setStatus] = useState<AttemptStatus | "all">("all");
  const [farmId, setFarmId] = useState<string>("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const farmsQ = useFarmIntegrationHealth(basePath);
  const recentQ = useRecentAttempts(
    {
      kind: kind === "all" ? undefined : kind,
      status: status === "all" ? undefined : status,
      farm_id: farmId || undefined,
    },
    basePath,
  );

  const rows = recentQ.data ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-ap-muted">{t("filters.kind")}</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as AttemptKind | "all")}
            className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
          >
            <option value="all">{t("filters.all")}</option>
            <option value="weather">{t("kind.weather")}</option>
            <option value="imagery">{t("kind.imagery")}</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-ap-muted">{t("filters.status")}</span>
          <select
            value={status}
            onChange={(e) =>
              setStatus(e.target.value as AttemptStatus | "all")
            }
            className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
          >
            <option value="all">{t("filters.all")}</option>
            <option value="running">{t("attemptStatus.running")}</option>
            <option value="succeeded">{t("attemptStatus.succeeded")}</option>
            <option value="failed">{t("attemptStatus.failed")}</option>
            <option value="skipped">{t("attemptStatus.skipped")}</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-ap-muted">{t("filters.farm")}</span>
          <select
            value={farmId}
            onChange={(e) => setFarmId(e.target.value)}
            className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
          >
            <option value="">{t("filters.all")}</option>
            {(farmsQ.data ?? []).map((f) => (
              <option key={f.farm_id} value={f.farm_id}>
                {f.farm_name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {recentQ.isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : recentQ.isError ? (
        <p className="text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("runs.empty")}</p>
      ) : (
        <RunsTable
          rows={rows}
          expanded={expanded}
          onToggle={(id) => setExpanded(expanded === id ? null : id)}
        />
      )}
    </div>
  );
}

function RunsTable({
  rows,
  expanded,
  onToggle,
}: {
  rows: IntegrationAttempt[];
  expanded: string | null;
  onToggle: (id: string) => void;
}): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const dateLocale = useDateLocale();

  return (
    <div className="overflow-x-auto rounded-xl border border-ap-line bg-ap-panel">
      <table className="min-w-full text-sm">
        <thead className="bg-ap-bg/40 text-xs uppercase text-ap-muted">
          <tr>
            <th className="px-3 py-2 text-start">{t("runs.col.kind")}</th>
            <th className="px-3 py-2 text-start">{t("runs.col.provider")}</th>
            <th className="px-3 py-2 text-start">{t("runs.col.status")}</th>
            <th className="px-3 py-2 text-start">{t("runs.col.startedAt")}</th>
            <th className="px-3 py-2 text-end">{t("runs.col.wait")}</th>
            <th className="px-3 py-2 text-end">{t("runs.col.run")}</th>
            <th className="px-3 py-2 text-start">{t("runs.col.detail")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ap-line">
          {rows.map((r) => {
            const isOpen = expanded === r.attempt_id;
            return (
              <Fragment key={r.attempt_id}>
                <tr
                  className="cursor-pointer hover:bg-ap-line/30"
                  onClick={() => onToggle(r.attempt_id)}
                >
                  <td className="px-3 py-2 text-ap-ink">
                    {t(`kind.${r.kind}`)}
                  </td>
                  <td className="px-3 py-2 text-ap-muted">
                    {r.provider_code ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap items-center gap-1">
                      <Pill kind={pillForStatus(r.status)}>
                        {t(`attemptStatus.${r.status}`)}
                      </Pill>
                      {r.failed_streak_position > 1 ? (
                        <Pill kind="crit">
                          {t("runs.attemptN", { n: r.failed_streak_position })}
                        </Pill>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-ap-muted">
                    {formatDistanceToNow(parseISO(r.started_at), {
                      addSuffix: true,
                      locale: dateLocale,
                    })}
                  </td>
                  <td className="px-3 py-2 text-end text-ap-muted">
                    {r.wait_ms !== null && r.wait_ms !== undefined
                      ? formatDuration(r.wait_ms)
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-end text-ap-muted">
                    {r.run_ms !== null && r.run_ms !== undefined
                      ? formatDuration(r.run_ms)
                      : r.duration_ms !== null
                        ? formatDuration(r.duration_ms)
                        : "—"}
                  </td>
                  <td className="px-3 py-2 text-ap-muted">
                    {summaryFor(r, t)}
                  </td>
                </tr>
                {isOpen ? (
                  <tr className="bg-ap-bg/30">
                    <td colSpan={7} className="px-3 py-3">
                      <DetailBlock row={r} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DetailBlock({ row }: { row: IntegrationAttempt }): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
      <Field label={t("detail.attemptId")} value={row.attempt_id} />
      <Field label={t("detail.subscriptionId")} value={row.subscription_id} />
      <Field label={t("detail.blockId")} value={row.block_id} />
      <Field label={t("detail.farmId")} value={row.farm_id ?? "—"} />
      {row.queued_at && row.queued_at !== row.started_at ? (
        <Field label={t("detail.queuedAt")} value={row.queued_at} />
      ) : null}
      <Field label={t("detail.startedAt")} value={row.started_at} />
      <Field label={t("detail.completedAt")} value={row.completed_at ?? "—"} />
      {row.rows_ingested !== null ? (
        <Field
          label={t("detail.rowsIngested")}
          value={String(row.rows_ingested)}
        />
      ) : null}
      {row.scene_id ? (
        <Field label={t("detail.sceneId")} value={row.scene_id} />
      ) : null}
      {row.error_code ? (
        <Field label={t("detail.errorCode")} value={row.error_code} />
      ) : null}
      {row.error_message ? (
        <div className="sm:col-span-2">
          <div className="text-ap-muted">{t("detail.errorMessage")}</div>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-md border border-ap-line bg-white p-2 text-[11px] text-ap-ink">
            {row.error_message}
          </pre>
        </div>
      ) : null}
    </dl>
  );
}

function Field({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <div>
      <span className="text-ap-muted">{label}: </span>
      <span className="font-mono text-ap-ink">{value}</span>
    </div>
  );
}

function pillForStatus(s: AttemptStatus): PillKind {
  switch (s) {
    case "succeeded":
      return "ok";
    case "failed":
      return "crit";
    case "running":
      return "info";
    case "skipped":
      return "neutral";
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

function summaryFor(
  r: IntegrationAttempt,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  if (r.error_code) return r.error_code;
  if (r.status === "succeeded" && r.rows_ingested !== null) {
    return t("runs.summary.rows", { n: r.rows_ingested });
  }
  if (r.scene_id) return r.scene_id;
  return "";
}
