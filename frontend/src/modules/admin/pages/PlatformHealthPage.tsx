import { differenceInHours, formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCrossTenantHealth } from "@/queries/platformHealthRollup";

type Status = "ok" | "warn" | "crit" | "neutral";

function statusFor(
  lastSyncIso: string | null,
  failed24h: number,
  activeSubs: number,
): Status {
  if (activeSubs === 0) return "neutral";
  if (failed24h > 0) return "crit";
  if (!lastSyncIso) return "crit";
  const hours = differenceInHours(new Date(), parseISO(lastSyncIso));
  if (hours > 24) return "crit";
  if (hours > 6) return "warn";
  return "ok";
}

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
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <header>
        <h1 className="text-2xl font-semibold text-ap-ink">
          {t("platformHealth.title")}
        </h1>
        <p className="mt-1 text-sm text-ap-muted">
          {t("platformHealth.subtitle")}
        </p>
      </header>

      {q.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : q.isError ? (
        <p className="text-sm text-ap-crit">{t("platformHealth.loadFailed")}</p>
      ) : (q.data ?? []).length === 0 ? (
        <p className="text-sm text-ap-muted">{t("platformHealth.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-ap-line bg-ap-panel">
          <table className="min-w-full text-sm">
            <thead className="bg-ap-bg/40 text-xs uppercase text-ap-muted">
              <tr>
                <th className="px-3 py-2 text-start">
                  {t("platformHealth.col.tenant")}
                </th>
                <th className="px-3 py-2 text-end">
                  {t("platformHealth.col.farms")}
                </th>
                <th className="px-3 py-2 text-start">
                  {t("platformHealth.col.weather")}
                </th>
                <th className="px-3 py-2 text-start">
                  {t("platformHealth.col.imagery")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {(q.data ?? []).map((row) => {
                const wStatus = statusFor(
                  row.weather_last_sync_at,
                  row.weather_failed_24h,
                  row.weather_active_subs,
                );
                const iStatus = statusFor(
                  row.imagery_last_sync_at,
                  row.imagery_failed_24h,
                  row.imagery_active_subs,
                );
                return (
                  <tr key={row.tenant_id}>
                    <td className="px-3 py-2 text-ap-ink">
                      <Link
                        to={`/platform/integrations/health/tenants/${row.tenant_id}`}
                        className="hover:text-ap-primary"
                      >
                        {row.tenant_name}{" "}
                        <span className="font-mono text-xs text-ap-muted">
                          ({row.tenant_slug})
                        </span>
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-end">{row.farms_count}</td>
                    <td className="px-3 py-2">
                      <Cell
                        status={wStatus}
                        lastSync={row.weather_last_sync_at}
                        activeSubs={row.weather_active_subs}
                        failed24h={row.weather_failed_24h}
                        dateLocale={dateLocale}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <Cell
                        status={iStatus}
                        lastSync={row.imagery_last_sync_at}
                        activeSubs={row.imagery_active_subs}
                        failed24h={row.imagery_failed_24h}
                        dateLocale={dateLocale}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
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
        <span className="text-xs text-ap-muted">
          {t("platformHealth.subs", { n: activeSubs })}
        </span>
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
        {failed24h > 0
          ? ` · ${t("platformHealth.failed24h", { n: failed24h })}`
          : ""}
      </span>
    </div>
  );
}
