import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useCapability } from "@/rbac/useCapability";

/**
 * Tenant Settings Hub layout — single home for tenant-wide configuration:
 *
 *   /settings/org              — tenant profile + branding (placeholder)
 *   /settings/notifications    — outbound channels (placeholder)
 *   /settings/integrations/*   — weather/imagery/email/webhook (placeholder)
 *   /settings/users            — tenant user mgmt (PR-Auth6)
 *   /settings/rules            — alert rules (PR-Auth4)
 *   /settings/decision-trees   — recommendation tree authoring (platform-only)
 *
 * Each tab is independently capability-gated; the side-nav hides entries
 * the caller can't reach. The page-level gates stay in place so a deep
 * link still 403s rather than rendering an empty shell.
 */
interface NavEntry {
  to: string;
  labelKey: string;
  show: boolean;
  prefix?: string;
}

export function SettingsLayout(): ReactNode {
  const { t } = useTranslation("settings");
  const canManageIntegrations = useCapability("tenant.manage_integrations");
  const canReadHealth = useCapability("tenant.read_integration_health");
  const canRule = useCapability("alert_rule.read");
  const canUser = useCapability("user.read");
  const canTree = useCapability("decision_tree.manage");
  // Org / notifications placeholder pages — gate on the same caps as the
  // V1 settings they will hold.
  const showOrg = canManageIntegrations;
  const showNotifications = canManageIntegrations;
  const showIntegrations = canManageIntegrations || canReadHealth;

  const entries: NavEntry[] = [
    { to: "/settings/org", labelKey: "nav.org", show: showOrg },
    {
      to: "/settings/notifications",
      labelKey: "nav.notifications",
      show: showNotifications,
    },
    {
      to: "/settings/integrations",
      labelKey: "nav.integrations",
      show: showIntegrations,
      prefix: "/settings/integrations",
    },
    { to: "/settings/users", labelKey: "nav.users", show: canUser },
    { to: "/settings/rules", labelKey: "nav.rules", show: canRule },
    {
      to: "/settings/decision-trees",
      labelKey: "nav.decisionTrees",
      show: canTree,
      prefix: "/settings/decision-trees",
    },
  ];

  return (
    <div className="mx-auto flex w-full max-w-6xl gap-6 px-4 py-6">
      <SettingsSideNav entries={entries.filter((e) => e.show)} title={t("title")} />
      <div className="flex-1 min-w-0">
        <Outlet />
      </div>
    </div>
  );
}

interface SettingsSideNavProps {
  entries: NavEntry[];
  title: string;
}

function SettingsSideNav({ entries, title }: SettingsSideNavProps): ReactNode {
  const { t } = useTranslation("settings");
  const location = useLocation();
  if (entries.length === 0) {
    return null;
  }
  return (
    <nav aria-label={t("title")} className="hidden w-56 flex-shrink-0 md:block">
      <h2 className="px-3 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
        {title}
      </h2>
      <ul className="flex flex-col gap-0.5">
        {entries.map((entry) => {
          const isActive = entry.prefix
            ? location.pathname.startsWith(entry.prefix)
            : location.pathname === entry.to;
          return (
            <li key={entry.to}>
              <NavLink
                to={entry.to}
                className={clsx(
                  "block rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-ap-primary-soft font-medium text-ap-primary"
                    : "text-ap-ink hover:bg-ap-line/50",
                )}
              >
                {t(entry.labelKey)}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
