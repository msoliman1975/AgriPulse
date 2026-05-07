import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { AlertsDrawer } from "./AlertsDrawer";
import { FarmSwitcher } from "./FarmSwitcher";
import { SettingsDrawer } from "./SettingsDrawer";
import { TenantTreeDrawer } from "./TenantTreeDrawer";
import { UserMenu } from "./UserMenu";
import { BellIcon, GearIcon, TenantIcon } from "./icons";

interface HeaderProps {
  /** Optional view-specific toolbar slot (Insights date-range, Plan zoom). */
  toolbar?: ReactNode;
}

export function Header({ toolbar }: HeaderProps = {}): ReactNode {
  const { t } = useTranslation("common");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [tenantTreeOpen, setTenantTreeOpen] = useState(false);

  // Wired up to the alerts API in a later prompt.
  const alertsCount = 0;

  return (
    <header className="border-b border-ap-line bg-ap-panel">
      <div className="flex w-full items-center gap-3 px-4 py-3">
        <Link
          to="/"
          className="flex items-center gap-2 text-base font-semibold text-ap-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
        >
          <span aria-hidden="true" className="inline-block h-3 w-3 rounded-full bg-ap-primary" />
          {t("app.name")}
        </Link>
        <span aria-hidden="true" className="text-ap-line">/</span>
        <FarmSwitcher />
        {toolbar ? <div className="ms-auto flex items-center gap-2">{toolbar}</div> : null}
        <div className={toolbar ? "flex items-center gap-2" : "ms-auto flex items-center gap-2"}>
          <UserMenu />
          <button
            type="button"
            aria-label={t("shell.alertsTitle")}
            onClick={() => setAlertsOpen(true)}
            className="relative rounded-md p-2 text-ap-muted hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
          >
            <BellIcon className="h-5 w-5" />
            {alertsCount > 0 ? (
              <span
                aria-label={t("shell.alertsCount", { count: alertsCount })}
                className="absolute -end-0.5 -top-0.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-ap-crit px-1 text-[10px] font-semibold leading-tight text-white"
              >
                {alertsCount}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            aria-label="Tenant tree"
            title="Tenant overview"
            onClick={() => setTenantTreeOpen(true)}
            className="rounded-md p-2 text-ap-muted hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
          >
            <TenantIcon className="h-5 w-5" />
          </button>
          <button
            type="button"
            aria-label={t("shell.settingsTitle")}
            onClick={() => setSettingsOpen(true)}
            className="rounded-md p-2 text-ap-muted hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
          >
            <GearIcon className="h-5 w-5" />
          </button>
        </div>
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <AlertsDrawer open={alertsOpen} onClose={() => setAlertsOpen(false)} />
      <TenantTreeDrawer open={tenantTreeOpen} onClose={() => setTenantTreeOpen(false)} />
    </header>
  );
}
