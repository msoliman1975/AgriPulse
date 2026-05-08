import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TenantStatus } from "@/api/adminTenants";

const STATUS_CLASS: Record<TenantStatus, string> = {
  active: "bg-emerald-100 text-emerald-800",
  suspended: "bg-amber-100 text-amber-800",
  pending_delete: "bg-rose-100 text-rose-800",
  pending_provision: "bg-sky-100 text-sky-800",
  archived: "bg-slate-200 text-slate-700",
};

interface Props {
  status: TenantStatus;
  className?: string;
}

export function TenantStatusBadge({ status, className }: Props): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
        STATUS_CLASS[status],
        className,
      )}
    >
      {t(`status.${status}`)}
    </span>
  );
}
