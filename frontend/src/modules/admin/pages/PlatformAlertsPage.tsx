import { formatDistanceToNow, parseISO } from "date-fns";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  AlertCategory,
  AlertSeverity,
  AlertStatusFilter,
  PlatformAlert,
} from "@/api/platformAlerts";
import { Button } from "@/components/Button";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Toolbar, type FilterValues } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { useDateLocale } from "@/hooks/useDateLocale";
import {
  useAcknowledgePlatformAlert,
  usePlatformAlerts,
  useResolvePlatformAlert,
  useRunPlatformAlertSweep,
} from "@/queries/platformAlerts";

const PAGE_SIZE = 100;

/** Severity drives the row's colour, and only two values exist. */
function severityPill(severity: AlertSeverity): "crit" | "warn" {
  return severity === "critical" ? "crit" : "warn";
}

function first<T extends string>(values: FilterValues, key: string): T | undefined {
  const list = values[key];
  return list && list.length > 0 ? (list[0] as T) : undefined;
}

/**
 * /platform/alerts — the cross-tenant operator queue.
 *
 * Sibling of /platform/integrations/health, and the split is deliberate:
 * health answers "what is the state of everything", this answers "what needs
 * me". A rollup with one red cell in a hundred green ones is a page you have
 * to go looking at; this is a list that is empty when nothing is wrong.
 */
export function PlatformAlertsPage(): ReactNode {
  const { t } = useTranslation("admin");
  const dateLocale = useDateLocale();

  const [values, setValues] = useState<FilterValues>({ status: ["live"] });

  const filters = useMemo(
    () => ({
      status: first<AlertStatusFilter>(values, "status") ?? "live",
      severity: first<AlertSeverity>(values, "severity"),
      category: first<AlertCategory>(values, "category"),
      limit: PAGE_SIZE,
    }),
    [values],
  );

  const q = usePlatformAlerts(filters);
  const ack = useAcknowledgePlatformAlert();
  const resolve = useResolvePlatformAlert();
  const sweep = useRunPlatformAlertSweep();

  const rows = q.data?.items ?? [];
  const state = queryState(
    q as unknown as Parameters<typeof queryState<PlatformAlert[]>>[0],
  );

  const ago = (iso: string): string =>
    formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: dateLocale });

  return (
    <Page>
      <PageHeader
        title={t("platformAlerts.title")}
        subtitle={t("platformAlerts.subtitle")}
        actions={
          <Button
            variant="secondary"
            onClick={() => sweep.mutate()}
            disabled={sweep.isPending}
          >
            {sweep.isPending ? t("platformAlerts.sweeping") : t("platformAlerts.sweepNow")}
          </Button>
        }
      />

      <Toolbar
        axisLayout="inline"
        axes={[
          {
            key: "status",
            label: t("platformAlerts.filter.status"),
            single: true,
            options: [
              { value: "live", label: t("platformAlerts.status.live") },
              { value: "open", label: t("platformAlerts.status.open") },
              { value: "acknowledged", label: t("platformAlerts.status.acknowledged") },
              { value: "resolved", label: t("platformAlerts.status.resolved") },
            ],
          },
          {
            key: "severity",
            label: t("platformAlerts.filter.severity"),
            single: true,
            options: [
              { value: "critical", label: t("platformAlerts.severity.critical") },
              { value: "warning", label: t("platformAlerts.severity.warning") },
            ],
          },
          {
            key: "category",
            label: t("platformAlerts.filter.category"),
            single: true,
            options: [
              { value: "imagery", label: t("platformAlerts.category.imagery") },
              { value: "thermal", label: t("platformAlerts.category.thermal") },
              { value: "weather", label: t("platformAlerts.category.weather") },
              { value: "index_calc", label: t("platformAlerts.category.index_calc") },
              { value: "task", label: t("platformAlerts.category.task") },
            ],
          },
        ]}
        values={values}
        onValuesChange={setValues}
        resultCount={{ shown: rows.length, total: q.data?.total ?? rows.length }}
      />

      <DataTable<PlatformAlert>
        state={state}
        rowKey={(row) => row.id}
        // "Nothing matches this filter" and "nothing is wrong" are very
        // different messages to an operator staring at an empty alert list.
        filtered={filters.status !== "live" || Boolean(filters.severity || filters.category)}
        empty={<EmptyState message={t("platformAlerts.empty")} />}
        noResults={<EmptyState message={t("platformAlerts.noResults")} />}
        errorMessage={t("platformAlerts.loadError")}
        columns={[
          {
            key: "severity",
            header: t("platformAlerts.col.severity"),
            width: "w-24",
            cell: (row) => (
              <Pill kind={severityPill(row.severity)}>
                {t(`platformAlerts.severity.${row.severity}`)}
              </Pill>
            ),
          },
          {
            key: "what",
            header: t("platformAlerts.col.what"),
            cell: (row) => (
              <div className="min-w-0">
                <div className="font-medium text-ap-ink">{row.title}</div>
                {row.detail ? (
                  <div className="mt-0.5 text-xs text-ap-muted">{row.detail}</div>
                ) : null}
              </div>
            ),
          },
          {
            key: "where",
            header: t("platformAlerts.col.where"),
            width: "w-56",
            cell: (row) => (
              <div className="min-w-0 text-xs">
                <div className="text-ap-ink">{row.tenant_name ?? "—"}</div>
                {row.farm_name ? (
                  <div className="text-ap-muted">{row.farm_name}</div>
                ) : null}
              </div>
            ),
          },
          {
            key: "kind",
            header: t("platformAlerts.col.kind"),
            width: "w-40",
            cell: (row) => (
              <div className="text-xs">
                <div className="text-ap-ink">{t(`platformAlerts.category.${row.category}`)}</div>
                <div className="text-ap-muted">{t(`platformAlerts.kind.${row.kind}`)}</div>
              </div>
            ),
          },
          {
            key: "seen",
            header: t("platformAlerts.col.seen"),
            width: "w-44",
            cell: (row) => (
              <div className="text-xs">
                <div className="text-ap-ink">{ago(row.last_seen_at)}</div>
                <div className="text-ap-muted">
                  {t("platformAlerts.sinceCount", {
                    since: ago(row.first_seen_at),
                    count: row.occurrences,
                  })}
                </div>
              </div>
            ),
          },
          {
            key: "actions",
            header: "",
            align: "end",
            width: "w-56",
            cell: (row) =>
              row.status === "resolved" ? (
                <Pill kind="neutral">
                  {t(`platformAlerts.resolvedReason.${row.resolved_reason ?? "manual"}`)}
                </Pill>
              ) : (
                <div className="flex justify-end gap-2">
                  {row.status === "open" ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => ack.mutate(row.id)}
                      disabled={ack.isPending}
                    >
                      {t("platformAlerts.acknowledge")}
                    </Button>
                  ) : (
                    <Pill kind="info">{t("platformAlerts.acknowledged")}</Pill>
                  )}
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => resolve.mutate(row.id)}
                    disabled={resolve.isPending}
                  >
                    {t("platformAlerts.resolve")}
                  </Button>
                </div>
              ),
          },
        ]}
      />
    </Page>
  );
}
