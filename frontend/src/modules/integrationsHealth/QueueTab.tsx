import { formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill, type PillKind } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useIntegrationQueue } from "@/queries/integrationsHealth";
import type { QueueEntry, QueueState } from "@/api/integrationsHealth";

export interface QueueTabProps {
  basePath: string;
}

/**
 * Pipeline queue (PR-IH4). Three sections side by side, each from the
 * same `/integrations/health/queue?state=…` call. Sections refresh
 * independently so a slow Running section doesn't stall Overdue.
 */
export function QueueTab({ basePath }: QueueTabProps): ReactNode {
  const { t } = useTranslation("integrationsHealth");

  const runningQ = useIntegrationQueue(undefined, "running", basePath);
  const overdueQ = useIntegrationQueue(undefined, "overdue", basePath);
  const stuckQ = useIntegrationQueue(undefined, "stuck", basePath);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <QueueSection
        title={t("queue.sections.running")}
        kind="running"
        rows={runningQ.data ?? []}
        isLoading={runningQ.isLoading}
        isError={runningQ.isError}
      />
      <QueueSection
        title={t("queue.sections.overdue")}
        kind="overdue"
        rows={overdueQ.data ?? []}
        isLoading={overdueQ.isLoading}
        isError={overdueQ.isError}
      />
      <QueueSection
        title={t("queue.sections.stuck")}
        kind="stuck"
        rows={stuckQ.data ?? []}
        isLoading={stuckQ.isLoading}
        isError={stuckQ.isError}
        footer={t("queue.stuckThreshold", { minutes: 30 })}
      />
    </div>
  );
}

function QueueSection({
  title,
  kind,
  rows,
  isLoading,
  isError,
  footer,
}: {
  title: string;
  kind: QueueState;
  rows: QueueEntry[];
  isLoading: boolean;
  isError: boolean;
  footer?: string;
}): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const dateLocale = useDateLocale();
  const pill: PillKind = kind === "stuck" ? "crit" : kind === "overdue" ? "warn" : "info";

  return (
    <section className="flex flex-col gap-2 rounded-xl border border-ap-line bg-ap-panel p-3">
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-ap-ink">{title}</h2>
        <Pill kind={pill}>{rows.length}</Pill>
      </header>

      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : isError ? (
        <p className="text-xs text-ap-crit">{t("loadFailed")}</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-ap-muted">{t(`queue.empty.${kind}`)}</p>
      ) : (
        <ul className="divide-y divide-ap-line text-xs">
          {rows.map((r) => (
            <li key={`${r.kind}-${r.subscription_id}-${r.attempt_id ?? "none"}`} className="py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-ap-ink">{t(`kind.${r.kind}`)}</span>
                <span className="font-mono text-ap-muted">{r.provider_code ?? "—"}</span>
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-2 text-ap-muted">
                <span className="truncate font-mono">{r.block_id}</span>
                <span>
                  {r.since
                    ? formatDistanceToNow(parseISO(r.since), {
                        addSuffix: true,
                        locale: dateLocale,
                      })
                    : "—"}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {footer ? <p className="text-[10px] text-ap-muted">{footer}</p> : null}
    </section>
  );
}
