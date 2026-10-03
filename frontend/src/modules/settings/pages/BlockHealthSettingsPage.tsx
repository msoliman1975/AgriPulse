// /settings/block-health — the one block health setting a tenant owns: how a
// block's status is built from its grid cells (`health.cell_rollup`, and
// `health.cell_share_pct` for the share rule, public migration 0094).
//
// The keys are served under the `detection` integration category, which is
// where they were first shown. They moved here because nobody looking for
// block health would open Integrations → Detection.
//
// The other health values are set by the platform and per crop, and a farm
// overrides them on its Settings tab in Farm management. The page says so,
// so a tenant knows where the rest of the rule lives.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { StatusBanner } from "@/components/StatusBanner";
import {
  CELL_ROLLUP_KEY,
  CELL_SHARE_KEY,
  CellRollupCard,
} from "@/modules/settings/components/CellRollupCard";
import { usePutTenantIntegration, useTenantIntegration } from "@/queries/integrations";
import { useCapability } from "@/rbac/useCapability";

export function BlockHealthSettingsPage(): ReactNode {
  const { t } = useTranslation("settings");
  const canManage = useCapability("tenant.manage_integrations");
  const tenantQ = useTenantIntegration("detection");
  const putTenant = usePutTenantIntegration("detection");

  if (!canManage) {
    return (
      <p className="py-12 text-center text-sm text-ap-muted">
        {t("noAccess.missingCapability", { capability: "tenant.manage_integrations" })}
      </p>
    );
  }

  const all = tenantQ.data?.settings ?? [];
  const rollup = all.find((s) => s.key === CELL_ROLLUP_KEY);
  const share = all.find((s) => s.key === CELL_SHARE_KEY);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("blockHealth.title")} subtitle={t("blockHealth.subtitle")} />
      {tenantQ.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : tenantQ.isError || !rollup ? (
        <StatusBanner kind="crit">{t("blockHealth.loadFailed")}</StatusBanner>
      ) : (
        <CellRollupCard
          rollup={rollup}
          share={share}
          onSave={(key, value) => putTenant.mutateAsync({ key, value })}
        />
      )}
      <p className="text-xs text-ap-muted">{t("blockHealth.otherTiers")}</p>
    </div>
  );
}
