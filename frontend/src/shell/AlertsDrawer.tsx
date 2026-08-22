import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { type InboxAction, type InboxItem, listInbox, transitionInboxItem } from "@/api/inbox";
import type { PlatformAlert } from "@/api/platformAlerts";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import { usePlatformAlerts } from "@/queries/platformAlerts";

import { Drawer } from "./Drawer";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Render the cross-tenant platform alert list instead of the inbox. */
  platform?: boolean;
}

export function AlertsDrawer({ open, onClose, platform = false }: Props): ReactNode {
  if (platform) {
    return <PlatformAlertsDrawer open={open} onClose={onClose} />;
  }
  return <InboxDrawer open={open} onClose={onClose} />;
}

/**
 * The bell for a platform admin.
 *
 * A platform admin belongs to no tenant, so `/v1/inbox` answers 403 and the
 * drawer was permanently empty for them - the one person the platform
 * alerts exist for could not reach them from the bell. This lists the live
 * platform alerts and links to the full page.
 *
 * Read-only on purpose. Acknowledging and resolving change what the red bar
 * says, so they belong on the page where the operator can see the whole
 * list, not in a drawer showing the first few.
 */
function PlatformAlertsDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("common");
  const dateLocale = useDateLocale();
  const navigate = useNavigate();

  // Ten is what fits in the drawer without turning it into a second copy
  // of the page. The "See all" button below is the way to the rest.
  const { data, isLoading } = usePlatformAlerts({ status: "live", limit: 10 }, open);
  const rows: PlatformAlert[] = data?.items ?? [];
  const total = data?.total ?? rows.length;

  return (
    <Drawer open={open} onClose={onClose} title={t("shell.platformAlertsTitle")}>
      {isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : rows.length > 0 ? (
        <ul className="flex flex-col divide-y divide-ap-line">
          {rows.map((row) => (
            <li key={row.id} className="py-2">
              <div className="flex items-start gap-2">
                <SeverityDot severity={row.severity} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ap-ink">{row.title}</p>
                  <p className="text-xs text-ap-muted">
                    {[row.tenant_name, row.farm_name].filter(Boolean).join(" / ")}
                  </p>
                  <p className="mt-0.5 text-[11px] text-ap-muted">
                    {formatDistanceToNow(new Date(row.last_seen_at), {
                      addSuffix: true,
                      locale: dateLocale,
                    })}
                  </p>
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ap-muted">{t("shell.platformAlertsEmpty")}</p>
      )}
      <button
        type="button"
        onClick={() => {
          navigate("/platform/alerts");
          onClose();
        }}
        className="mt-4 w-full rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-primary hover:bg-ap-line/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
      >
        {t("shell.platformAlertsSeeAll", { count: total })}
      </button>
    </Drawer>
  );
}

function InboxDrawer({ open, onClose }: { open: boolean; onClose: () => void }): ReactNode {
  const { t } = useTranslation("common");
  const dateLocale = useDateLocale();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["inbox", "list"] as const,
    queryFn: () => listInbox(),
    enabled: open,
    refetchInterval: open ? 30_000 : false,
  });

  // When the drawer opens, refresh the unread-count badge so a stale
  // cache from elsewhere in the app catches up.
  useEffect(() => {
    if (open) {
      void qc.invalidateQueries({ queryKey: ["inbox", "unread-count"] });
    }
  }, [open, qc]);

  const mutate = useMutation({
    mutationFn: ({ id, action }: { id: string; action: InboxAction }) =>
      transitionInboxItem(id, action),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["inbox", "list"] });
      void qc.invalidateQueries({ queryKey: ["inbox", "unread-count"] });
    },
  });

  function openItem(item: InboxItem): void {
    if (item.read_at == null) {
      mutate.mutate({ id: item.id, action: "read" });
    }
    if (item.link_url) {
      navigate(item.link_url);
      onClose();
    }
  }

  return (
    <Drawer open={open} onClose={onClose} title={t("shell.alertsTitle")}>
      {isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : data && data.length > 0 ? (
        <ul className="flex flex-col divide-y divide-ap-line">
          {data.map((item) => (
            <li key={item.id} className="py-2">
              <div className="flex items-start gap-2">
                <SeverityDot severity={item.severity} />
                <button
                  type="button"
                  onClick={() => openItem(item)}
                  className="flex-1 text-start focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
                >
                  <p
                    className={
                      item.read_at == null
                        ? "text-sm font-medium text-ap-ink"
                        : "text-sm text-ap-muted"
                    }
                  >
                    {item.title}
                  </p>
                  <p className="text-xs text-ap-muted line-clamp-2">{item.body}</p>
                  <p className="mt-0.5 text-[11px] text-ap-muted">
                    {formatDistanceToNow(new Date(item.created_at), {
                      addSuffix: true,
                      locale: dateLocale,
                    })}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => mutate.mutate({ id: item.id, action: "archive" })}
                  aria-label="Archive"
                  className="rounded p-1 text-ap-muted hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
                  title="Archive"
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ap-muted">{t("shell.alertsEmpty")}</p>
      )}
    </Drawer>
  );
}

function SeverityDot({
  severity,
}: {
  severity: "info" | "warning" | "critical" | null;
}): ReactNode {
  const cls =
    severity === "critical"
      ? "bg-ap-crit"
      : severity === "warning"
        ? "bg-ap-warn"
        : severity === "info"
          ? "bg-ap-accent"
          : "bg-ap-line";
  return (
    <span aria-hidden="true" className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${cls}`} />
  );
}
