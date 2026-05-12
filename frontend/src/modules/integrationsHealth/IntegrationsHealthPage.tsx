import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { SegmentedControl } from "@/components/SegmentedControl";
import { useCapability } from "@/rbac/useCapability";

import { OverviewTab } from "./OverviewTab";
import { RunsTab } from "./RunsTab";
import { QueueTab } from "./QueueTab";
import { ProvidersTab } from "./ProvidersTab";

type TabKey = "overview" | "runs" | "queue" | "providers";

/**
 * Shared four-tab integration-health page. Mounted under:
 *   - /settings/integrations/health (tenant portal)
 *   - /platform/integrations/health/tenants/:id (platform drill-in, PR-IH7)
 *
 * `basePath` toggles whether API calls go to `/v1` (tenant) or
 * `/v1/admin/integrations/health/tenants/:id` (platform).
 */
export interface IntegrationsHealthPageProps {
  /** Base path passed through to the API hooks. Defaults to "/v1". */
  basePath?: string;
  /** Whether the Providers tab should show the full platform-wide list
   *  (true for PlatformAdmin) or the tenant-scoped subset (false). */
  platformProviderScope?: boolean;
}

export function IntegrationsHealthPage({
  basePath = "/v1",
  platformProviderScope = false,
}: IntegrationsHealthPageProps): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const canRead = useCapability("tenant.read_integration_health");
  const canReadPlatform = useCapability("platform.manage_tenants");
  const [tab, setTab] = useState<TabKey>("overview");

  if (!canRead && !canReadPlatform) {
    return (
      <div className="mx-auto max-w-3xl py-12 text-center">
        <p className="text-sm text-ap-muted">
          {t("missingCapability", {
            capability: "tenant.read_integration_health",
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold text-ap-ink">{t("title")}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t("subtitle")}</p>
      </header>

      <SegmentedControl
        ariaLabel={t("tabsLabel")}
        items={[
          { value: "overview", label: t("topTabs.overview") },
          { value: "runs", label: t("topTabs.runs") },
          { value: "queue", label: t("topTabs.queue") },
          { value: "providers", label: t("topTabs.providers") },
        ]}
        value={tab}
        onChange={(v) => setTab(v as TabKey)}
      />

      {tab === "overview" && <OverviewTab basePath={basePath} />}
      {tab === "runs" && <RunsTab basePath={basePath} />}
      {tab === "queue" && <QueueTab basePath={basePath} />}
      {tab === "providers" && (
        <ProvidersTab
          basePath={basePath}
          platformScope={platformProviderScope}
        />
      )}
    </div>
  );
}
