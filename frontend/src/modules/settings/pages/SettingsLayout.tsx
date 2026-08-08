import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { Page } from "@/components/Page";
import { useCapability } from "@/rbac/useCapability";

/**
 * Tenant Settings Hub layout — single home for tenant-wide configuration:
 *
 *   /settings/org              — tenant profile + branding (placeholder)
 *   /settings/notifications    — outbound channels (placeholder)
 *   /settings/integrations/*   — weather/imagery/email/webhook (placeholder)
 *   /settings/users            — tenant user mgmt (PR-Auth6)
 *   /settings/rules            — alert rules (PR-Auth4)
 *
 * (Decision-tree authoring was promoted out of this hub to the top-level
 *  /decision-trees surface — reached from the gear/Configs menu.)
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
  const canUser = useCapability("user.read");
  const canResources = useCapability("resource.read");
  // Farm-scoped grants can't be checked without a farm id, so this gates on
  // the tenant-level grant — which is who the surface is for. A farm-scoped
  // manager still assigns crops from the Farm Console.
  const canBulk = useCapability("crop_assignment.create");
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
    { to: "/settings/bulk", labelKey: "nav.bulk", show: canBulk },
    { to: "/settings/workers", labelKey: "nav.workers", show: canResources },
    { to: "/settings/equipment", labelKey: "nav.equipment", show: canResources },
    // Decision Trees promoted to the top-level /decision-trees surface
    // (reached from the gear/Configs menu), no longer a Settings tab.
  ];

  // The hub owns the <Page> frame; its child routes render bare fragments so
  // the inset isn't applied twice. (This layout used to add its own
  // `px-4 py-6` on top of the shell's, which is what made /settings/* the only
  // triple-padded surface in the app.)
  return (
    <Page width="wide">
      <div className="flex gap-6">
        <SettingsSideNav entries={entries.filter((e) => e.show)} title={t("title")} />
        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </Page>
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
