import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TenantStatus } from "@/api/adminTenants";

const STATUS_CLASS: Record<TenantStatus, string> = {
  active: "bg-ap-primary-soft text-ap-primary",
  suspended: "bg-ap-warn-soft text-ap-warn",
  pending_delete: "bg-ap-crit-soft text-ap-crit",
  pending_provision: "bg-sky-100 text-sky-800",
  archived: "bg-ap-line text-ap-ink",
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
