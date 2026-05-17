import { formatDistanceToNow, parseISO } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router-dom";

import type { Alert, AlertSeverity, AlertStatus } from "@/api/alerts";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { SegmentedControl } from "@/components/SegmentedControl";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import { useAlerts, useTransitionAlert } from "@/queries/alerts";

const STATUS_TAB_VALUES: ReadonlyArray<AlertStatus | "all"> = [
  "open",
  "acknowledged",
  "snoozed",
  "resolved",
  "all",
];

const SEV_KIND: Record<AlertSeverity, "info" | "warn" | "crit"> = {
  info: "info",
  warning: "warn",
  critical: "crit",
};

export function AlertsPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t } = useTranslation("alerts");
  const [tab, setTab] = useState<AlertStatus | "all">("open");
  const canAck = useCapability("alert.acknowledge", { farmId });
  const canResolve = useCapability("alert.resolve", { farmId });

  const { data, isLoading, isError } = useAlerts(tab === "all" ? {} : { status: tab });
  const transition = useTransitionAlert();

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("page.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("page.subtitle")}</p>
        </div>
        <SegmentedControl
          ariaLabel={t("tabsLabel")}
          items={STATUS_TAB_VALUES.map((v) => ({ value: v, label: t(`tabs.${v}`) }))}
          value={tab}
          onChange={(v) => setTab(v)}
        />
      </header>

      <div className="rounded-xl border border-ap-line bg-ap-panel">
        {isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : isError ? (
          <p className="p-4 text-sm text-ap-crit">{t("page.loadFailed")}</p>
        ) : !data || data.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">
            {tab === "open" ? t("page.emptyOpen") : t("page.empty")}
          </p>
        ) : (
          <ul className="divide-y divide-ap-line">
            {data.map((a) => (
              <Row
                key={a.id}
                alert={a}
                farmId={farmId}
                canAck={canAck}
                canResolve={canResolve}
                onAck={() => transition.mutate({ alertId: a.id, payload: { acknowledge: true } })}
                onResolve={() => transition.mutate({ alertId: a.id, payload: { resolve: true } })}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

interface RowProps {
  alert: Alert;
  farmId: string;
  canAck: boolean;
  canResolve: boolean;
  onAck: () => void;
  onResolve: () => void;
}

function Row({ alert: a, farmId, canAck, canResolve, onAck, onResolve }: RowProps): ReactNode {
  const navigate = useNavigate();
  const { t } = useTranslation("alerts");
  const dateLocale = useDateLocale();
  const isTerminal = a.status === "resolved";
  return (
    <li className="flex items-start gap-3 p-4">
      <div
        aria-hidden="true"
        className={`h-12 w-1 flex-none rounded-full ${
          a.severity === "critical"
            ? "bg-ap-crit"
            : a.severity === "warning"
              ? "bg-ap-warn"
              : "bg-ap-accent"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ap-ink">{a.diagnosis_en ?? a.rule_code}</span>
          <Pill kind={SEV_KIND[a.severity]}>{t(`severity.${a.severity}`)}</Pill>
          <Pill kind={a.status === "resolved" ? "ok" : a.status === "open" ? "crit" : "neutral"}>
            {t(`status.${a.status}`)}
          </Pill>
        </div>
        {a.prescription_en ? (
          <p className="mt-1 text-sm text-ap-muted">{a.prescription_en}</p>
        ) : null}
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-ap-muted">
          <span className="font-mono">{a.rule_code}</span>
          <span>·</span>
          <span>
            {formatDistanceToNow(parseISO(a.created_at), {
              addSuffix: true,
              locale: dateLocale,
            })}
          </span>
          {a.acknowledged_at ? (
            <>
              <span>·</span>
              <span>
                {t("row.ackedAgo", {
                  when: formatDistanceToNow(parseISO(a.acknowledged_at), {
                    addSuffix: true,
                    locale: dateLocale,
                  }),
                })}
              </span>
            </>
          ) : null}
          {a.resolved_at ? (
            <>
              <span>·</span>
              <span>
                {t("row.resolvedAgo", {
                  when: formatDistanceToNow(parseISO(a.resolved_at), {
                    addSuffix: true,
                    locale: dateLocale,
                  }),
                })}
              </span>
            </>
          ) : null}
        </div>
      </div>
      <div className="flex flex-none flex-col items-end gap-1.5">
        <button
          type="button"
          onClick={() => {
            if (a.prescription_activity_id) {
              navigate(`/plan/${farmId}?activity=${a.prescription_activity_id}&lane=${a.block_id}`);
            } else {
              navigate(`/plan/${farmId}?lane=${a.block_id}`);
            }
          }}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("actions.openInPlan")}
        </button>
        {!isTerminal ? (
          <div className="flex gap-1">
            {a.status === "open" && canAck ? (
              <button
                type="button"
                onClick={onAck}
                className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
              >
                {t("actions.ack")}
              </button>
            ) : null}
            {canResolve ? (
              <button
                type="button"
                onClick={onResolve}
                className="rounded-md bg-ap-primary px-2 py-1 text-xs font-medium text-white hover:bg-ap-primary/90"
              >
                {t("actions.resolve")}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}
