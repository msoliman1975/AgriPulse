import { addDays, addWeeks, format, parseISO, startOfWeek } from "date-fns";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import type { BoardActivity, BoardBlock } from "@/api/plans";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import { useBoard } from "@/queries/board";

import { BoardCell } from "../components/BoardCell";
import { ActivityChip } from "../components/ActivityChip";
import { QuickAddDialog } from "../components/QuickAddDialog";
import { ActivityDetailDialog } from "../components/ActivityDetailDialog";

const DEFAULT_WEEKS = 8;

/**
 * /board/:farmId — Weekly Operations Board.
 * Rows = active blocks. Columns = N weeks starting Monday-of-current-week
 * (or a user-picked start). Each cell shows activity chips for that
 * (block × week).
 */
export function BoardPage(): ReactNode {
  const { t } = useTranslation("board");
  const { farmId } = useParams<{ farmId: string }>();
  const canManage = useCapability("plan.manage");

  // Anchor the window to Monday of the current week (locale-agnostic; we
  // pin to Monday regardless of i18next's weekStartsOn).
  const [anchor, setAnchor] = useState<Date>(() =>
    startOfWeek(new Date(), { weekStartsOn: 1 }),
  );
  const weekStartIso = format(anchor, "yyyy-MM-dd");
  const weeks = DEFAULT_WEEKS;

  const boardQ = useBoard(farmId ?? null, weekStartIso, weeks);

  const weekStarts = useMemo(
    () =>
      Array.from({ length: weeks }, (_, i) =>
        format(addWeeks(anchor, i), "yyyy-MM-dd"),
      ),
    [anchor, weeks],
  );

  // Group activities by (block_id × week_start_iso) so the grid lookup
  // is O(1) at render time.
  const grouped = useMemo(() => {
    const map = new Map<string, BoardActivity[]>();
    for (const a of boardQ.data?.activities ?? []) {
      const wkStart = format(
        startOfWeek(parseISO(a.scheduled_date), { weekStartsOn: 1 }),
        "yyyy-MM-dd",
      );
      const key = `${a.block_id}|${wkStart}`;
      const arr = map.get(key) ?? [];
      arr.push(a);
      map.set(key, arr);
    }
    return map;
  }, [boardQ.data]);

  const [quickAdd, setQuickAdd] = useState<{
    blockId: string;
    weekStart: string;
  } | null>(null);
  const [openActivity, setOpenActivity] = useState<BoardActivity | null>(null);

  if (!farmId) return null;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ap-ink">{t("title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("subtitle")}</p>
        </div>
        <WeekNavigator
          anchor={anchor}
          weeks={weeks}
          onShift={(deltaWeeks) =>
            setAnchor((prev) => addWeeks(prev, deltaWeeks))
          }
          onToday={() =>
            setAnchor(startOfWeek(new Date(), { weekStartsOn: 1 }))
          }
        />
      </header>

      {boardQ.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : boardQ.isError ? (
        <p className="text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : (
        <BoardGrid
          blocks={boardQ.data?.blocks ?? []}
          weekStarts={weekStarts}
          grouped={grouped}
          canManage={canManage}
          onCellClick={(blockId, weekStart) => {
            if (canManage) setQuickAdd({ blockId, weekStart });
          }}
          onChipClick={(activity) => setOpenActivity(activity)}
        />
      )}

      {quickAdd ? (
        <QuickAddDialog
          farmId={farmId}
          blockId={quickAdd.blockId}
          weekStart={quickAdd.weekStart}
          onClose={() => setQuickAdd(null)}
        />
      ) : null}
      {openActivity ? (
        <ActivityDetailDialog
          farmId={farmId}
          activity={openActivity}
          onClose={() => setOpenActivity(null)}
        />
      ) : null}
    </div>
  );
}

interface WeekNavigatorProps {
  anchor: Date;
  weeks: number;
  onShift: (deltaWeeks: number) => void;
  onToday: () => void;
}

function WeekNavigator({
  anchor,
  weeks,
  onShift,
  onToday,
}: WeekNavigatorProps): ReactNode {
  const { t } = useTranslation("board");
  const last = addDays(addWeeks(anchor, weeks), -1);
  return (
    <div className="flex items-center gap-2 text-sm">
      <button
        type="button"
        className="rounded-md border border-ap-line bg-white px-2 py-1"
        onClick={() => onShift(-weeks)}
      >
        ‹ {t("nav.prev")}
      </button>
      <span className="px-2 text-ap-muted">
        {format(anchor, "MMM d")} – {format(last, "MMM d, yyyy")}
      </span>
      <button
        type="button"
        className="rounded-md border border-ap-line bg-white px-2 py-1"
        onClick={() => onShift(weeks)}
      >
        {t("nav.next")} ›
      </button>
      <button
        type="button"
        className="ml-2 rounded-md border border-ap-line bg-white px-2 py-1"
        onClick={onToday}
      >
        {t("nav.today")}
      </button>
    </div>
  );
}

interface BoardGridProps {
  blocks: BoardBlock[];
  weekStarts: string[];
  grouped: Map<string, BoardActivity[]>;
  canManage: boolean;
  onCellClick: (blockId: string, weekStart: string) => void;
  onChipClick: (a: BoardActivity) => void;
}

function BoardGrid({
  blocks,
  weekStarts,
  grouped,
  canManage,
  onCellClick,
  onChipClick,
}: BoardGridProps): ReactNode {
  const { t } = useTranslation("board");
  if (blocks.length === 0) {
    return (
      <p className="rounded-xl border border-ap-line bg-ap-panel p-8 text-center text-sm text-ap-muted">
        {t("empty")}
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-ap-line bg-ap-panel">
      <table className="min-w-full table-fixed border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-ap-bg/80">
          <tr>
            <th className="w-32 border-b border-r border-ap-line p-2 text-left text-xs font-semibold uppercase tracking-wider text-ap-muted">
              {t("col.block")}
            </th>
            {weekStarts.map((ws) => (
              <th
                key={ws}
                className="min-w-[140px] border-b border-r border-ap-line p-2 text-left text-xs font-semibold uppercase tracking-wider text-ap-muted"
              >
                {format(parseISO(ws), "MMM d")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {blocks.map((block) => (
            <tr key={block.id}>
              <th
                scope="row"
                className="w-32 border-b border-r border-ap-line bg-ap-bg/30 p-2 text-left align-top font-medium text-ap-ink"
              >
                <div>{block.code}</div>
                {block.name ? (
                  <div className="text-xs text-ap-muted">{block.name}</div>
                ) : null}
              </th>
              {weekStarts.map((ws) => {
                const key = `${block.id}|${ws}`;
                const cellActivities = grouped.get(key) ?? [];
                return (
                  <BoardCell
                    key={key}
                    canManage={canManage}
                    onClick={() => onCellClick(block.id, ws)}
                  >
                    {cellActivities.map((a) => (
                      <ActivityChip
                        key={a.id}
                        activity={a}
                        onClick={(evt) => {
                          evt.stopPropagation();
                          onChipClick(a);
                        }}
                      />
                    ))}
                  </BoardCell>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
