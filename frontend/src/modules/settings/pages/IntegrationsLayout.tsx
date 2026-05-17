import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useCapability } from "@/rbac/useCapability";

interface SubNavEntry {
  to: string;
  labelKey: string;
  show: boolean;
}

/**
 * /settings/integrations/* — wraps the integration health page (PR-Set2)
 * + the per-integration config pages (PR-Set4, placeholders for now).
 *
 * Only renders the sub-nav if the user has at least one of the gating
 * capabilities. The pages themselves enforce their own capability check.
 */
export function IntegrationsLayout(): ReactNode {
  const { t } = useTranslation("settings");
  const canManage = useCapability("tenant.manage_integrations");
  const canReadHealth = useCapability("tenant.read_integration_health");
  const location = useLocation();

  const entries: SubNavEntry[] = [
    {
      to: "/settings/integrations/health",
      labelKey: "integrationsTabs.health",
      show: canReadHealth,
    },
    {
      to: "/settings/integrations/weather",
      labelKey: "integrationsTabs.weather",
      show: canManage,
    },
    {
      to: "/settings/integrations/imagery",
      labelKey: "integrationsTabs.imagery",
      show: canManage,
    },
    {
      to: "/settings/integrations/email",
      labelKey: "integrationsTabs.email",
      show: canManage,
    },
    {
      to: "/settings/integrations/webhook",
      labelKey: "integrationsTabs.webhook",
      show: canManage,
    },
  ].filter((e) => e.show);

  if (entries.length === 0) {
    return (
      <div className="mx-auto max-w-3xl py-12 text-center">
        <p className="text-sm text-ap-muted">
          {t("noAccess.missingCapability", {
            capability: "tenant.manage_integrations",
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <nav aria-label={t("integrationsTabs.label")} className="flex gap-1 border-b border-ap-line">
        {entries.map((entry) => {
          const isActive = location.pathname.startsWith(entry.to);
          return (
            <NavLink
              key={entry.to}
              to={entry.to}
              className={clsx(
                "px-3 py-2 text-sm transition-colors border-b-2",
                isActive
                  ? "border-ap-primary text-ap-primary font-medium"
                  : "border-transparent text-ap-muted hover:text-ap-ink",
              )}
            >
              {t(entry.labelKey)}
            </NavLink>
          );
        })}
      </nav>
      <Outlet />
    </div>
  );
}
