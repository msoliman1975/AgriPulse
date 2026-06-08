import clsx from "clsx";
import { useState, type DragEvent, type MouseEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface RecDropPayload {
  recommendationId: string;
  actionType: string;
}

interface BoardCellProps {
  canManage: boolean;
  selected: boolean;
  onClick: (modifiers: { shift: boolean }) => void;
  /** Optional drop handler — fires when a rec chip is dropped on the cell. */
  onRecDrop?: (payload: RecDropPayload) => void;
  /** Compact cells (used for day-grid month view) get a smaller min-width
   *  so 30 columns fit reasonably. Defaults to false. */
  compact?: boolean;
  /** Cell sits in the column representing today — gets a persistent tint. */
  today?: boolean;
  children: ReactNode;
}

const REC_MIME = "application/x-agripulse-rec";

/** One (block × week) cell. Clickable when the caller has plan.manage.
 * Shift-click toggles the cell into the bulk-add selection. Accepts a
 * rec-chip drop to spawn a scheduled activity.
 */
export function BoardCell({
  canManage,
  selected,
  onClick,
  onRecDrop,
  compact = false,
  today = false,
  children,
}: BoardCellProps): ReactNode {
  const { t } = useTranslation("board");
  const [dragOver, setDragOver] = useState(false);

  function handleClick(e: MouseEvent<HTMLTableCellElement>) {
    if (!canManage) return;
    onClick({ shift: e.shiftKey });
  }

  function handleDragOver(e: DragEvent<HTMLTableCellElement>) {
    if (!canManage || !onRecDrop) return;
    if (Array.from(e.dataTransfer.types).includes(REC_MIME)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      if (!dragOver) setDragOver(true);
    }
  }

  function handleDragLeave() {
    if (dragOver) setDragOver(false);
  }

  function handleDrop(e: DragEvent<HTMLTableCellElement>) {
    setDragOver(false);
    if (!canManage || !onRecDrop) return;
    const raw = e.dataTransfer.getData(REC_MIME);
    if (!raw) return;
    e.preventDefault();
    try {
      const parsed = JSON.parse(raw) as { id: string; action_type: string };
      onRecDrop({ recommendationId: parsed.id, actionType: parsed.action_type });
    } catch {
      // Drop carried something unparseable — ignore.
    }
  }

  return (
    <td
      className={clsx(
        compact ? "min-w-[56px] p-1" : "min-w-[140px] p-1.5",
        "border-b border-r align-top",
        selected
          ? "border-ap-primary bg-ap-primary-soft/50"
          : dragOver
            ? "border-ap-primary bg-ap-primary-soft/40"
            : today
              ? "border-ap-line bg-ap-accent/[0.07]"
              : "border-ap-line",
        canManage && "cursor-pointer hover:bg-ap-primary-soft/30",
      )}
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
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
