import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface BoardCellProps {
  canManage: boolean;
  onClick: () => void;
  children: ReactNode;
}

/** One (block × week) cell. Clickable when the caller has plan.manage. */
export function BoardCell({
  canManage,
  onClick,
  children,
}: BoardCellProps): ReactNode {
  const { t } = useTranslation("board");
  return (
    <td
      className={clsx(
        "min-w-[140px] border-b border-r border-ap-line p-1.5 align-top",
        canManage && "cursor-pointer hover:bg-ap-primary-soft/30",
      )}
      onClick={canManage ? onClick : undefined}
    >
      <div className="flex min-h-[60px] flex-col gap-1">
        {children}
        {canManage ? (
          <span
            className="opacity-0 transition-opacity hover:opacity-100 sr-only-focusable text-xs text-ap-muted"
            aria-hidden="true"
          >
            + {t("cell.add")}
          </span>
        ) : null}
      </div>
    </td>
  );
}
