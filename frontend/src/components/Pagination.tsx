import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "./Button";

interface PaginationProps {
  /** Zero-based. */
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  className?: string;
}

/** Renders nothing when everything fits on one page. */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  className,
}: PaginationProps): ReactNode {
  const { t } = useTranslation("common");
  if (total <= pageSize) return null;

  const first = total === 0 ? 0 : page * pageSize + 1;
  const last = Math.min(total, (page + 1) * pageSize);
  const hasPrev = page > 0;
  const hasNext = (page + 1) * pageSize < total;

  return (
    <nav
      aria-label={t("pagination.label")}
      className={clsx("flex items-center justify-between gap-3 text-xs text-ap-muted", className)}
    >
      <span>{t("pagination.showing", { first, last, total })}</span>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={!hasPrev}
          onClick={() => onPageChange(Math.max(0, page - 1))}
        >
          {t("pagination.prev")}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={!hasNext}
          onClick={() => onPageChange(page + 1)}
        >
          {t("pagination.next")}
        </Button>
      </div>
    </nav>
  );
}
