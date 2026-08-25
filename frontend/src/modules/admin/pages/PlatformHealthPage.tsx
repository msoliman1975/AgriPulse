import { formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PlatformTenantHealthRow } from "@/api/platformHealthRollup";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { queryState } from "@/components/asyncState";
import { useDateLocale } from "@/hooks/useDateLocale";
import type { Status } from "@/modules/admin/lib/healthStatus";
import { statusFor } from "@/modules/admin/lib/healthStatus";
import { useCrossTenantHealth } from "@/queries/platformHealthRollup";

/**
 * /platform/integrations/health — cross-tenant integration rollup.
 *
 * One row per active tenant with summary counts. Click into a tenant
 * to dive into per-tenant detail (uses the existing tenant detail page
 * with the Integrations tab from PR-Reorg3).
 */
export function PlatformHealthPage(): ReactNode {
  const { t } = useTranslation("admin");
  const dateLocale = useDateLocale();
  const q = useCrossTenantHealth();

  return (
    <Page>
      <PageHeader title={t("platformHealth.title")} subtitle={t("platformHealth.subtitle")} />

      <DataTable<PlatformTenantHealthRow>
        columns={[
          {
            key: "tenant",
            header: t("platformHealth.col.tenant"),
            cell: (row) => (
              <>
                {row.tenant_name}{" "}
                <span className="font-mono text-xs text-ap-muted">({row.tenant_slug})</span>
              </>
            ),
          },
          {
            key: "farms",
            header: t("platformHealth.col.farms"),
            align: "end",
            cell: (row) => row.farms_count,
          },
          {
            key: "weather",
            header: t("platformHealth.col.weather"),
            cell: (row) => (
              <Cell
                status={statusFor(
                  "weather",
                  row.weather_last_sync_at,
                  row.weather_failed_24h,
                  row.weather_active_subs,
                )}
                lastSync={row.weather_last_sync_at}
                failed24h={row.weather_failed_24h}
                activeSubs={row.weather_active_subs}
                dateLocale={dateLocale}
              />
            ),
          },
          {
            key: "imagery",
            header: t("platformHealth.col.imagery"),
            cell: (row) => (
              <Cell
                status={statusFor(
                  "imagery",
                  row.imagery_last_sync_at,
                  row.imagery_failed_24h,
                  row.imagery_active_subs,
                )}
                lastSync={row.imagery_last_sync_at}
                failed24h={row.imagery_failed_24h}
                activeSubs={row.imagery_active_subs}
                dateLocale={dateLocale}
              />
            ),
          },
        ]}
        rowKey={(row) => row.tenant_id}
        state={queryState(q)}
        rowHref={(row) => `/platform/integrations/health/tenants/${row.tenant_id}`}
        caption={t("platformHealth.title")}
        errorMessage={t("platformHealth.loadFailed")}
        empty={<EmptyState message={t("platformHealth.empty")} />}
      />
    </Page>
  );
}

function Cell({
  status,
  lastSync,
  activeSubs,
  failed24h,
  dateLocale,
}: {
  status: Status;
  lastSync: string | null;
  activeSubs: number;
  failed24h: number;
  dateLocale: ReturnType<typeof useDateLocale>;
}): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-2">
        <Pill kind={status === "neutral" ? "neutral" : status}>
          {t(`platformHealth.status.${status}`)}
        </Pill>
        <span className="text-xs text-ap-muted">{t("platformHealth.subs", { n: activeSubs })}</span>
      </div>
      <span className="text-[11px] text-ap-muted">
        {activeSubs === 0
          ? t("platformHealth.noActive")
          : lastSync
            ? t("platformHealth.lastSync", {
                when: formatDistanceToNow(parseISO(lastSync), {
                  addSuffix: true,
                  locale: dateLocale,
                }),
              })
            : t("platformHealth.neverSynced")}
        {failed24h > 0 ? ` · ${t("platformHealth.failed24h", { n: failed24h })}` : ""}
      </span>
    </div>
  );
}
