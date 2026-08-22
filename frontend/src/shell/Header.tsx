import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getUnreadCount } from "@/api/inbox";
import { usePlatformAlertSummary } from "@/queries/platformAlerts";
import { useCapability } from "@/rbac/useCapability";
import { openInboxStream } from "@/realtime/inboxStream";
import { ActiveFarmContext } from "./ActiveFarmContext";
import { AlertsDrawer } from "./AlertsDrawer";
import { ConfigsMenu } from "./ConfigsMenu";
import { FarmSwitcher } from "./FarmSwitcher";
import { SettingsDrawer } from "./SettingsDrawer";
import { TenantBadge } from "./TenantBadge";
import { UserMenu } from "./UserMenu";
import { BellIcon, UserIcon } from "./icons";

interface HeaderProps {
  /** Optional view-specific toolbar slot (Insights date-range, Plan zoom). */
  toolbar?: ReactNode;
}

export function Header({ toolbar }: HeaderProps = {}): ReactNode {
  const { t } = useTranslation("common");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);

  // Bell badge: unread inbox count.
  //   * Push: SSE on /v1/inbox/stream invalidates the count + list on
  //     each event so the UI reflects new alerts within a second.
  //   * Pull fallback: 60s poll covers the gap if the stream errors
  //     (no token, network blip, dev server reload).
  //
  // A platform admin has no tenant, so every inbox call answers 403 and the
  // bell was permanently empty for the one person the platform alerts are
  // written for. For them the bell counts live platform alerts instead and
  // the drawer lists those, which is also the second way into
  // /platform/alerts alongside the red bar.
  const isPlatformAdmin = useCapability("platform.manage_tenants");
  const qc = useQueryClient();
  const { data: inboxCount = 0 } = useQuery({
    queryKey: ["inbox", "unread-count"] as const,
    queryFn: getUnreadCount,
    refetchInterval: 60_000,
    enabled: !isPlatformAdmin,
  });
  const { data: platformSummary } = usePlatformAlertSummary(isPlatformAdmin);
  const alertsCount = isPlatformAdmin
    ? (platformSummary?.critical ?? 0) + (platformSummary?.warning ?? 0)
    : inboxCount;

  useEffect(() => {
    // The inbox stream is tenant-scoped too. Opening it as a platform admin
    // only produces a 403 in the console on every page load.
    if (isPlatformAdmin) return;
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
  }, [qc, isPlatformAdmin]);

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
        <TenantBadge />
        <FarmSwitcher />
        <ActiveFarmContext />
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
          <ConfigsMenu />
          <button
            type="button"
            aria-label={t("shell.userProfileTitle")}
            title={t("shell.userProfileTitle")}
            onClick={() => setSettingsOpen(true)}
            className="rounded-md p-2 text-ap-muted hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
          >
            <UserIcon className="h-5 w-5" />
          </button>
        </div>
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <AlertsDrawer
        open={alertsOpen}
        onClose={() => setAlertsOpen(false)}
        platform={isPlatformAdmin}
      />
    </header>
  );
}
