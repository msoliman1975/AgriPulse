import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getUnreadCount } from "@/api/inbox";
import { openInboxStream } from "@/realtime/inboxStream";
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

  // Bell badge: unread inbox count.
  //   * Push: SSE on /v1/inbox/stream invalidates the count + list on
  //     each event so the UI reflects new alerts within a second.
  //   * Pull fallback: 60s poll covers the gap if the stream errors
  //     (no token, network blip, dev server reload).
  const qc = useQueryClient();
  const { data: alertsCount = 0 } = useQuery({
    queryKey: ["inbox", "unread-count"] as const,
    queryFn: getUnreadCount,
    refetchInterval: 60_000,
  });

  useEffect(() => {
    const handle = openInboxStream({
      onEvent: () => {
        void qc.invalidateQueries({ queryKey: ["inbox", "unread-count"] });
        void qc.invalidateQueries({ queryKey: ["inbox", "list"] });
      },
      onError: () => {
        // Polling above keeps the badge fresh; intentional no-op.
      },
    });
    return () => {
      handle.close();
    };
  }, [qc]);

  return (
    <header className="border-b border-ap-line bg-ap-panel">
      <div className="flex w-full items-center gap-3 px-4 py-3">
        <Link
          to="/"
          className="flex items-center gap-2 text-base font-semibold text-ap-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
        >
          <img
            src="/agripulse-mark.png"
            alt=""
            aria-hidden="true"
            className="h-6 w-6 object-contain"
          />
          {t("app.name")}
        </Link>
        <span aria-hidden="true" className="text-ap-line">
          /
        </span>
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
