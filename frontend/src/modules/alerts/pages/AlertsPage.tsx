import { formatDistanceToNow, parseISO } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import type { Alert, AlertSeverity, AlertStatus } from "@/api/alerts";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { RowList } from "@/components/RowList";
import { SegmentedControl } from "@/components/SegmentedControl";
import { queryState } from "@/components/asyncState";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { localizedField } from "@/lib/localizedField";
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

const SEV_RAIL: Record<AlertSeverity, string> = {
  info: "bg-ap-accent",
  warning: "bg-ap-warn",
  critical: "bg-ap-crit",
};

export function AlertsPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t, i18n } = useTranslation("alerts");
  const dateLocale = useDateLocale();
  const [tab, setTab] = useState<AlertStatus | "all">("open");
  const canAck = useCapability("alert.acknowledge", { farmId });
  const canResolve = useCapability("alert.resolve", { farmId });

  const alerts = useAlerts(
    tab === "all"
      ? { farm_id: farmId ?? undefined }
      : { farm_id: farmId ?? undefined, status: tab },
  );
  const transition = useTransitionAlert();

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  const ago = (iso: string): string =>
    formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: dateLocale });

  return (
    <Page>
      <PageHeader
        title={t("page.title")}
        subtitle={t("page.subtitle")}
        actions={
          <SegmentedControl
            ariaLabel={t("tabsLabel")}
            items={STATUS_TAB_VALUES.map((v) => ({ value: v, label: t(`tabs.${v}`) }))}
            value={tab}
            onChange={(v) => setTab(v)}
          />
        }
      />

      <RowList<Alert>
        state={queryState(alerts)}
        filtered={tab !== "all"}
        rowKey={(a) => a.id}
        rail={(a) => SEV_RAIL[a.severity]}
        errorMessage={t("page.loadFailed")}
        title={(a) => (
          <>
            {localizedField(i18n.language, a.diagnosis_en, a.diagnosis_ar) ?? a.rule_code}
            <Pill kind={SEV_KIND[a.severity]}>{t(`severity.${a.severity}`)}</Pill>
            <Pill kind={a.status === "resolved" ? "ok" : a.status === "open" ? "crit" : "neutral"}>
              {t(`status.${a.status}`)}
            </Pill>
          </>
        )}
        subtitle={(a) => localizedField(i18n.language, a.prescription_en, a.prescription_ar)}
        meta={(a) => (
          <>
            <span className="font-mono">{a.rule_code}</span>
            <span>·</span>
            <span>{ago(a.created_at)}</span>
            {a.acknowledged_at ? (
              <>
                <span>·</span>
                <span>{t("row.ackedAgo", { when: ago(a.acknowledged_at) })}</span>
              </>
            ) : null}
            {a.resolved_at ? (
              <>
                <span>·</span>
                <span>{t("row.resolvedAgo", { when: ago(a.resolved_at) })}</span>
              </>
            ) : null}
          </>
        )}
        actions={(a) => (
          <div className="flex flex-col items-end gap-1.5">
            <LinkButton
              size="sm"
              variant="secondary"
              to={
                a.prescription_activity_id
                  ? `/board/${farmId}?activity=${a.prescription_activity_id}&lane=${a.block_id}`
                  : `/board/${farmId}?lane=${a.block_id}`
              }
            >
              {t("actions.openInPlan")}
            </LinkButton>
            {a.status !== "resolved" ? (
              <div className="flex gap-1">
                {a.status === "open" && canAck ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      transition.mutate({ alertId: a.id, payload: { acknowledge: true } })
                    }
                  >
                    {t("actions.ack")}
                  </Button>
                ) : null}
                {canResolve ? (
                  <Button
                    size="sm"
                    onClick={() => transition.mutate({ alertId: a.id, payload: { resolve: true } })}
                  >
                    {t("actions.resolve")}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
        empty={<EmptyState message={t("page.empty")} action={null} />}
        noResults={
          <EmptyState
            message={tab === "open" ? t("page.emptyOpen") : t("page.empty")}
            action={
              tab === "all" ? null : (
                <Button variant="secondary" onClick={() => setTab("all")}>
                  {t("tabs.all")}
                </Button>
              )
            }
          />
        }
      />
    </Page>
  );
}
