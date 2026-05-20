import { format, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { BoardActivity, BoardBlock } from "@/api/plans";

import { ActivityChip } from "./ActivityChip";

interface BoardMobileListProps {
  blocks: BoardBlock[];
  activities: BoardActivity[];
  onChipClick: (a: BoardActivity) => void;
  onBlockAddClick?: (blockId: string) => void;
  canManage: boolean;
}

/**
 * Mobile fallback. The grid is unusable on narrow viewports — collapse
 * to a vertical timeline per block. Sorted ascending by date. Bulk
 * gestures are dropped on mobile; users fall back to one-at-a-time.
 */
export function BoardMobileList({
  blocks,
  activities,
  onChipClick,
  onBlockAddClick,
  canManage,
}: BoardMobileListProps): ReactNode {
  const { t } = useTranslation("board");
  const byBlock = new Map<string, BoardActivity[]>();
  for (const a of activities) {
    const arr = byBlock.get(a.block_id) ?? [];
    arr.push(a);
    byBlock.set(a.block_id, arr);
  }
  for (const arr of byBlock.values()) {
    arr.sort((a, b) => a.scheduled_date.localeCompare(b.scheduled_date));
  }

  return (
    <div className="flex flex-col gap-4">
      {blocks.map((block) => {
        const rows = byBlock.get(block.id) ?? [];
        return (
          <section
            key={block.id}
            className="rounded-xl border border-ap-line bg-ap-panel"
          >
            <header className="flex items-center justify-between border-b border-ap-line p-3">
              <div>
                <div className="font-medium text-ap-ink">{block.code}</div>
                {block.name ? (
                  <div className="text-xs text-ap-muted">{block.name}</div>
                ) : null}
              </div>
              {canManage && onBlockAddClick ? (
                <button
                  type="button"
                  onClick={() => onBlockAddClick(block.id)}
                  className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white"
                >
                  {t("mobile.add")}
                </button>
              ) : null}
            </header>
            <ul className="flex flex-col gap-1 p-3">
              {rows.length === 0 ? (
                <li className="text-xs text-ap-muted">{t("mobile.noneScheduled")}</li>
              ) : (
                rows.map((a) => (
                  <li key={a.id} className="flex items-center gap-2">
                    <time
                      dateTime={a.scheduled_date}
                      className="w-20 flex-shrink-0 text-xs text-ap-muted"
                    >
                      {format(parseISO(a.scheduled_date), "MMM d, EEE")}
                    </time>
                    <ActivityChip
                      activity={a}
                      onClick={(e) => {
                        e.stopPropagation();
                        onChipClick(a);
                      }}
                    />
                  </li>
                ))
              )}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
