import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import { useCapability } from "@/rbac/useCapability";

/**
 * /settings landing — bounces to the first reachable tab so deep-linking
 * /settings shows something useful instead of a blank pane.
 */
export function SettingsIndexPage(): ReactNode {
  const { t } = useTranslation("settings");
  const canManageIntegrations = useCapability("tenant.manage_integrations");
  const canReadHealth = useCapability("tenant.read_integration_health");
  const canRule = useCapability("alert_rule.read");
  const canUser = useCapability("user.read");

  if (canManageIntegrations) return <Navigate to="/settings/org" replace />;
  if (canReadHealth) return <Navigate to="/settings/integrations/health" replace />;
  if (canUser) return <Navigate to="/settings/users" replace />;
  if (canRule) return <Navigate to="/settings/rules" replace />;
  return (
    <div className="mx-auto max-w-3xl py-12 text-center">
      <h1 className="text-xl font-semibold text-ap-ink">{t("noAccess.title")}</h1>
      <p className="mt-2 text-sm text-ap-muted">{t("noAccess.body")}</p>
    </div>
  );
}
