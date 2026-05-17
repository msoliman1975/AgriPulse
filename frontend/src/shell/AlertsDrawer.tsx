import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { type InboxAction, type InboxItem, listInbox, transitionInboxItem } from "@/api/inbox";
import { Skeleton } from "@/components/Skeleton";

import { Drawer } from "./Drawer";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function AlertsDrawer({ open, onClose }: Props): ReactNode {
  const { t } = useTranslation("common");
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
                    {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
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
        <p className="text-sm text-slate-600">{t("shell.alertsEmpty")}</p>
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
