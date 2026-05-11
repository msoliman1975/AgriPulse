import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { IntegrationsHealthPage } from "@/modules/integrationsHealth";

/**
 * Platform-side tenant drill-in (PR-IH7).
 *
 * Mounts the shared IntegrationsHealthPage with the base path swapped
 * to the platform admin mirror routes
 * (`/v1/admin/tenants/{tenantId}/integrations/health/...`). The page
 * itself is identical — same four tabs, same components — only the
 * data source changes.
 */
export function PlatformHealthTenantDrillPage(): ReactNode {
  const { tenantId } = useParams<{ tenantId: string }>();
  const { t } = useTranslation("admin");

  if (!tenantId) {
    return (
      <div className="mx-auto max-w-3xl py-12 text-center">
        <p className="text-sm text-ap-muted">
          {t("platformHealth.drill.missingTenant")}
        </p>
      </div>
    );
  }

  const basePath = `/v1/admin/tenants/${tenantId}`;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <div className="text-sm">
        <Link
          to="/platform/integrations/health"
          className="text-ap-muted hover:text-ap-primary"
        >
          ← {t("platformHealth.drill.back")}
        </Link>
      </div>
      <IntegrationsHealthPage basePath={basePath} platformProviderScope={true} />
    </div>
  );
}
