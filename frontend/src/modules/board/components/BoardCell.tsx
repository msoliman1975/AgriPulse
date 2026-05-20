import clsx from "clsx";
import type { MouseEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface BoardCellProps {
  canManage: boolean;
  selected: boolean;
  onClick: (modifiers: { shift: boolean }) => void;
  children: ReactNode;
}

/** One (block × week) cell. Clickable when the caller has plan.manage.
 * Shift-click toggles the cell into the bulk-add selection.
 */
export function BoardCell({
  canManage,
  selected,
  onClick,
  children,
}: BoardCellProps): ReactNode {
  const { t } = useTranslation("board");
  function handleClick(e: MouseEvent<HTMLTableCellElement>) {
    if (!canManage) return;
    onClick({ shift: e.shiftKey });
  }
  return (
    <td
      className={clsx(
        "min-w-[140px] border-b border-r p-1.5 align-top",
        selected
          ? "border-ap-primary bg-ap-primary-soft/50"
          : "border-ap-line",
        canManage && "cursor-pointer hover:bg-ap-primary-soft/30",
      )}
      onClick={handleClick}
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
