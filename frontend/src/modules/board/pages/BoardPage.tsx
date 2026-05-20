import { addDays, addWeeks, format, parseISO, startOfWeek } from "date-fns";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import type {
  ActivityType,
  BoardActivity,
  BoardBlock,
  BoardResourceChip,
} from "@/api/plans";
import { Skeleton } from "@/components/Skeleton";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useCapability } from "@/rbac/useCapability";
import { useBoard } from "@/queries/board";

import { useScheduleRecommendation } from "@/queries/recScheduling";

import { ActivityChip } from "../components/ActivityChip";
import { ActivityDetailDialog } from "../components/ActivityDetailDialog";
import { BoardCell, type RecDropPayload } from "../components/BoardCell";
import { BoardFilters } from "../components/BoardFilters";
import { BoardMobileList } from "../components/BoardMobileList";
import {
  BulkAddDialog,
  type SelectedCell,
} from "../components/BulkAddDialog";
import { QuickAddDialog } from "../components/QuickAddDialog";
import { RecommendationsRail } from "../components/RecommendationsRail";

const DEFAULT_WEEKS = 8;

/**
 * /board/:farmId — Weekly Operations Board.
 *
 * - Desktop: rows=active blocks × cols=N weeks grid. Click a cell to
 *   quick-add; shift-click 2+ cells to bulk-add.
 * - Mobile: vertical timeline per block.
 * - Filters (block, type, assignee) apply locally — the grid still
 *   fetches the full window and we drop chips client-side.
 */
export function BoardPage(): ReactNode {
  const { t } = useTranslation("board");
  const { farmId } = useParams<{ farmId: string }>();
  const canManage = useCapability("plan.manage");
  const isMobile = useIsMobile();

  const [anchor, setAnchor] = useState<Date>(() =>
    startOfWeek(new Date(), { weekStartsOn: 1 }),
  );
  const weekStartIso = format(anchor, "yyyy-MM-dd");
  const weeks = DEFAULT_WEEKS;

  const boardQ = useBoard(farmId ?? null, weekStartIso, weeks);

  // Filters — empty Set means "all".
  const [filterBlockIds, setFilterBlockIds] = useState<Set<string>>(new Set());
  const [filterTypes, setFilterTypes] = useState<Set<ActivityType>>(new Set());
  const [filterResourceIds, setFilterResourceIds] = useState<Set<string>>(
    new Set(),
  );

  // Bulk selection — set of "${blockId}|${weekStart}" keys.
  const [bulkSelection, setBulkSelection] = useState<Set<string>>(new Set());
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);

  const [quickAdd, setQuickAdd] = useState<{
    blockId: string;
    weekStart: string;
  } | null>(null);
  const [openActivity, setOpenActivity] = useState<BoardActivity | null>(null);

  const scheduleRec = useScheduleRecommendation(farmId ?? null);

  const weekStarts = useMemo(
    () =>
      Array.from({ length: weeks }, (_, i) =>
        format(addWeeks(anchor, i), "yyyy-MM-dd"),
      ),
    [anchor, weeks],
  );

  // Apply client-side filters to the activity list.
  const filteredActivities = useMemo(() => {
    const all = boardQ.data?.activities ?? [];
    return all.filter((a) => {
      if (filterBlockIds.size > 0 && !filterBlockIds.has(a.block_id)) {
        return false;
      }
      if (filterTypes.size > 0 && !filterTypes.has(a.activity_type)) {
        return false;
      }
      if (filterResourceIds.size > 0) {
        const hit = a.resources.some((r) => filterResourceIds.has(r.id));
        if (!hit) return false;
      }
      return true;
    });
  }, [boardQ.data, filterBlockIds, filterTypes, filterResourceIds]);

  // Visible blocks: if filterBlockIds is non-empty, show only those;
  // otherwise all from the response.
  const visibleBlocks = useMemo(() => {
    const all = boardQ.data?.blocks ?? [];
    if (filterBlockIds.size === 0) return all;
    return all.filter((b) => filterBlockIds.has(b.id));
  }, [boardQ.data, filterBlockIds]);

  // Map (block × week-monday) → activities for O(1) cell lookup.
  const grouped = useMemo(() => {
    const map = new Map<string, BoardActivity[]>();
    for (const a of filteredActivities) {
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
  }, [filteredActivities]);

  // Surface known resources to the filter UI by flattening once.
  const knownResources = useMemo<BoardResourceChip[]>(() => {
    const byId = new Map<string, BoardResourceChip>();
    for (const a of boardQ.data?.activities ?? []) {
      for (const r of a.resources) {
        if (!byId.has(r.id)) byId.set(r.id, r);
      }
    }
    return Array.from(byId.values()).sort((a, b) =>
      a.name.localeCompare(b.name),
    );
  }, [boardQ.data]);

  function toggleCellSelection(blockId: string, weekStart: string) {
    const key = `${blockId}|${weekStart}`;
    setBulkSelection((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function clearFilters() {
    setFilterBlockIds(new Set());
    setFilterTypes(new Set());
    setFilterResourceIds(new Set());
  }

  function clearBulk() {
    setBulkSelection(new Set());
  }

  // Selected-cell tuples for BulkAddDialog — only include cells whose
  // block is in visibleBlocks (filter narrowed the grid).
  const selectedCells: SelectedCell[] = useMemo(() => {
    const byBlock = new Map(
      (boardQ.data?.blocks ?? []).map((b) => [b.id, b.code]),
    );
    return Array.from(bulkSelection)
      .map((k): SelectedCell | null => {
        const [blockId, weekStart] = k.split("|");
        const code = byBlock.get(blockId);
        if (!code) return null;
        return { blockId, weekStart, blockCode: code };
      })
      .filter((x): x is SelectedCell => x !== null);
  }, [bulkSelection, boardQ.data]);

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

      <div className="flex flex-wrap items-center justify-between gap-2">
        <BoardFilters
          blocks={boardQ.data?.blocks ?? []}
          knownResources={knownResources}
          blockIds={filterBlockIds}
          setBlockIds={setFilterBlockIds}
          types={filterTypes}
          setTypes={setFilterTypes}
          resourceIds={filterResourceIds}
          setResourceIds={setFilterResourceIds}
          onClear={clearFilters}
        />
        {bulkSelection.size >= 2 && canManage ? (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-ap-muted">
              {t("bulk.selected", { count: bulkSelection.size })}
            </span>
            <button
              type="button"
              onClick={() => setBulkDialogOpen(true)}
              className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary-700"
            >
              {t("bulk.add")}
            </button>
            <button
              type="button"
              onClick={clearBulk}
              className="text-xs text-ap-muted underline-offset-2 hover:underline"
            >
              {t("bulk.clear")}
            </button>
          </div>
        ) : null}
      </div>

      {boardQ.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : boardQ.isError ? (
        <p className="text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : isMobile ? (
        <BoardMobileList
          blocks={visibleBlocks}
          activities={filteredActivities}
          onChipClick={setOpenActivity}
          onBlockAddClick={(blockId) =>
            setQuickAdd({ blockId, weekStart: weekStartIso })
          }
          canManage={canManage}
        />
      ) : (
        <div className="flex gap-4">
          <div className="min-w-0 flex-1">
            <BoardGrid
              blocks={visibleBlocks}
              weekStarts={weekStarts}
              grouped={grouped}
              canManage={canManage}
              selection={bulkSelection}
              onCellClick={(blockId, weekStart, modifiers) => {
                if (!canManage) return;
                if (modifiers.shift) {
                  toggleCellSelection(blockId, weekStart);
                } else if (bulkSelection.size > 0) {
                  // Plain click while a bulk selection is active: clear it
                  // first, then treat as a new quick-add.
                  clearBulk();
                  setQuickAdd({ blockId, weekStart });
                } else {
                  setQuickAdd({ blockId, weekStart });
                }
              }}
              onChipClick={(activity) => setOpenActivity(activity)}
              onRecDrop={(blockId, weekStart, payload) => {
                if (!canManage) return;
                // The cell carries the week's Monday; the schedule
                // endpoint accepts a per-day scheduled_date so we land
                // on Monday by default. Operators can drag the resulting
                // chip later if they need a different day.
                scheduleRec.mutate({
                  recommendationId: payload.recommendationId,
                  payload: { scheduled_date: weekStart, block_id: blockId },
                });
              }}
            />
          </div>
          {canManage ? (
            <RecommendationsRail farmId={farmId} draggable />
          ) : null}
        </div>
      )}

      {quickAdd ? (
        <QuickAddDialog
          farmId={farmId}
          blockId={quickAdd.blockId}
          weekStart={quickAdd.weekStart}
          onClose={() => setQuickAdd(null)}
        />
      ) : null}
      {bulkDialogOpen ? (
        <BulkAddDialog
          farmId={farmId}
          cells={selectedCells}
          onClose={() => setBulkDialogOpen(false)}
          onSaved={clearBulk}
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
  selection: Set<string>;
  onCellClick: (
    blockId: string,
    weekStart: string,
    modifiers: { shift: boolean },
  ) => void;
  onChipClick: (a: BoardActivity) => void;
  onRecDrop?: (
    blockId: string,
    weekStart: string,
    payload: RecDropPayload,
  ) => void;
}

function BoardGrid({
  blocks,
  weekStarts,
  grouped,
  canManage,
  selection,
  onCellClick,
  onChipClick,
  onRecDrop,
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
                const isSelected = selection.has(key);
                return (
                  <BoardCell
                    key={key}
                    canManage={canManage}
                    selected={isSelected}
                    onClick={(modifiers) =>
                      onCellClick(block.id, ws, modifiers)
                    }
                    onRecDrop={
                      onRecDrop
                        ? (payload) => onRecDrop(block.id, ws, payload)
                        : undefined
                    }
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
