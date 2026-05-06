import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { AlertsDrawer } from "./AlertsDrawer";
import { SettingsDrawer } from "./SettingsDrawer";
import { UserMenu } from "./UserMenu";
import { BellIcon, GearIcon } from "./icons";

export function Header(): ReactNode {
  const { t } = useTranslation("common");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);

  // Wired up to the alerts API in a later prompt.
  const alertsCount = 0;

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="flex w-full items-center justify-between gap-4 px-4 py-3">
        <Link
          to="/"
          className="flex items-center gap-2 text-lg font-semibold text-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <span aria-hidden="true" className="inline-block h-3 w-3 rounded-full bg-brand-600" />
          {t("app.name")}
        </Link>
        <div className="flex items-center gap-2">
          <UserMenu />
          <button
            type="button"
            aria-label={t("shell.alertsTitle")}
            onClick={() => setAlertsOpen(true)}
            className="relative rounded-md p-2 text-slate-600 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-brand-500"
          >
            <BellIcon className="h-5 w-5" />
            {alertsCount > 0 ? (
              <span
                aria-label={t("shell.alertsCount", { count: alertsCount })}
                className="absolute -end-0.5 -top-0.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold leading-tight text-white"
              >
                {alertsCount}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            aria-label={t("shell.settingsTitle")}
            onClick={() => setSettingsOpen(true)}
            className="rounded-md p-2 text-slate-600 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-brand-500"
          >
            <GearIcon className="h-5 w-5" />
          </button>
        </div>
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <AlertsDrawer open={alertsOpen} onClose={() => setAlertsOpen(false)} />
    </header>
  );
}
