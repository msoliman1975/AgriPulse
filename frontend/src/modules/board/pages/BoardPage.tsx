import {
  addDays,
  addMonths,
  addWeeks,
  addYears,
  format,
  parseISO,
  startOfMonth,
  startOfWeek,
} from "date-fns";
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

type ViewMode = "week" | "month" | "season";

/** One column of the board grid. `start` is its ISO date (the day for
 * day-unit modes; first-of-month for month-unit modes). `unit` controls
 * how activities aggregate into the cell. */
interface ColumnDef {
  start: string;
  unit: "day" | "month";
}

/** Computes the columns + the backend fetch window for a view mode.
 *
 * Week / Month modes render one column **per day** (7 cols for a week,
 * 28-31 for a month). Season mode aggregates by month (8 cols Mar..Oct)
 * because 240+ day columns would be unusable.
 *
 * The backend endpoint only speaks (weekStart, weeks). We translate the
 * view-mode window into the smallest week-aligned superset that covers
 * it and aggregate client-side. */
function computeWindow(mode: ViewMode, anchor: Date): {
  columns: ColumnDef[];
  fetchStart: string;
  fetchWeeks: number;
} {
  if (mode === "week") {
    // `anchor` = Monday of the visible week.
    const columns = Array.from({ length: 7 }, (_, i) => ({
      start: format(addDays(anchor, i), "yyyy-MM-dd"),
      unit: "day" as const,
    }));
    return {
      columns,
      fetchStart: format(anchor, "yyyy-MM-dd"),
      fetchWeeks: 1,
    };
  }
  if (mode === "month") {
    // `anchor` = 1st of the visible month. Columns = every day in that
    // calendar month.
    const monthStart = startOfMonth(anchor);
    const days = daysInMonth(monthStart);
    const columns = Array.from({ length: days }, (_, i) => ({
      start: format(addDays(monthStart, i), "yyyy-MM-dd"),
      unit: "day" as const,
    }));
    // Walk back to the Monday on/before the 1st, then ask for enough
    // weeks to cover the last day of the month (worst case 6 weeks for
    // a 31-day month starting on Sunday).
    const fetchStart = startOfWeek(monthStart, { weekStartsOn: 1 });
    return {
      columns,
      fetchStart: format(fetchStart, "yyyy-MM-dd"),
      fetchWeeks: 6,
    };
  }
  // Season: Mar..Oct of anchor's year, month-aggregated. Day columns
  // would be 240+ — keep this view summary-level.
  const seasonStart = new Date(anchor.getFullYear(), 2, 1);
  const columns = Array.from({ length: 8 }, (_, i) => ({
    start: format(addMonths(seasonStart, i), "yyyy-MM-dd"),
    unit: "month" as const,
  }));
  return {
    columns,
    fetchStart: format(startOfWeek(seasonStart, { weekStartsOn: 1 }), "yyyy-MM-dd"),
    fetchWeeks: 36,
  };
}

function daysInMonth(monthStart: Date): number {
  // last-day-of-month via the date-overflow trick: day 0 of next month
  // is the last day of this month.
  return new Date(
    monthStart.getFullYear(),
    monthStart.getMonth() + 1,
    0,
  ).getDate();
}

/**
 * /board/:farmId — Operations Board.
 *
 * - Desktop: rows=active blocks × cols=N (weeks | months | season months).
 *   Click a cell to quick-add; shift-click 2+ cells to bulk-add (week mode).
 * - Mobile: vertical timeline per block.
 * - Filters (block, type, assignee) apply locally — the grid still
 *   fetches the full window and we drop chips client-side.
 */
export function BoardPage(): ReactNode {
  const { t } = useTranslation("board");
  const { farmId } = useParams<{ farmId: string }>();
  const canManage = useCapability("plan.manage");
  const isMobile = useIsMobile();

  const [viewMode, setViewMode] = useState<ViewMode>("week");
  const [anchor, setAnchor] = useState<Date>(() =>
    startOfWeek(new Date(), { weekStartsOn: 1 }),
  );

  const range = useMemo(() => computeWindow(viewMode, anchor), [viewMode, anchor]);
  const boardQ = useBoard(farmId ?? null, range.fetchStart, range.fetchWeeks);

  // Filters — empty Set means "all".
  const [filterBlockIds, setFilterBlockIds] = useState<Set<string>>(new Set());
  const [filterTypes, setFilterTypes] = useState<Set<ActivityType>>(new Set());
  const [filterResourceIds, setFilterResourceIds] = useState<Set<string>>(
    new Set(),
  );

  // Bulk selection — set of "${blockId}|${columnStart}" keys.
  const [bulkSelection, setBulkSelection] = useState<Set<string>>(new Set());
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);

  const [quickAdd, setQuickAdd] = useState<{
    blockId: string;
    columnStart: string;
    columnUnit: "day" | "month";
  } | null>(null);
  const [openActivity, setOpenActivity] = useState<BoardActivity | null>(null);

  const scheduleRec = useScheduleRecommendation(farmId ?? null);

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

  // Map (block × column-start) → activities for O(1) cell lookup.
  // Column-start is the day itself in week/month modes (unit=day) or
  // first-of-month in season mode (unit=month).
  const grouped = useMemo(() => {
    const map = new Map<string, BoardActivity[]>();
    const colUnit = range.columns[0]?.unit ?? "day";
    const truncate = (iso: string): string => {
      if (colUnit === "day") return iso; // scheduled_date is already a day.
      return format(startOfMonth(parseISO(iso)), "yyyy-MM-dd");
    };
    for (const a of filteredActivities) {
      const col = truncate(a.scheduled_date);
      const key = `${a.block_id}|${col}`;
      const arr = map.get(key) ?? [];
      arr.push(a);
      map.set(key, arr);
    }
    return map;
  }, [filteredActivities, range.columns]);

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

  function toggleCellSelection(blockId: string, columnStart: string) {
    const key = `${blockId}|${columnStart}`;
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

  // Switching view mode invalidates the selection unit, so wipe it.
  function changeViewMode(next: ViewMode) {
    if (next === viewMode) return;
    setViewMode(next);
    clearBulk();
    // Re-anchor sensibly per mode so the visible window covers "now".
    if (next === "week") {
      setAnchor(startOfWeek(new Date(), { weekStartsOn: 1 }));
    } else if (next === "month") {
      setAnchor(startOfMonth(new Date()));
    } else {
      setAnchor(new Date(new Date().getFullYear(), 2, 1));
    }
  }

  function shiftAnchor(direction: -1 | 1) {
    setAnchor((prev) => {
      // Step one window at a time: ±1 week, ±1 month, ±1 year.
      if (viewMode === "week") return addWeeks(prev, direction);
      if (viewMode === "month") return addMonths(prev, direction);
      return addYears(prev, direction);
    });
  }

  function onTodayPressed() {
    if (viewMode === "week") {
      setAnchor(startOfWeek(new Date(), { weekStartsOn: 1 }));
    } else if (viewMode === "month") {
      setAnchor(startOfMonth(new Date()));
    } else {
      setAnchor(new Date(new Date().getFullYear(), 2, 1));
    }
  }

  // Selected-cell tuples for BulkAddDialog — only week-mode bulk-add
  // is supported (semantic = "same day-of-week across N selected weeks").
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

  // Range label in the navigator depends on the unit shown.
  const rangeLabel = (() => {
    const first = range.columns[0]?.start;
    const last = range.columns[range.columns.length - 1]?.start;
    if (!first || !last) return "";
    if (viewMode === "week") {
      return `${format(parseISO(first), "MMM d")} – ${format(parseISO(last), "MMM d, yyyy")}`;
    }
    if (viewMode === "month") {
      return format(parseISO(first), "MMMM yyyy");
    }
    return `${format(parseISO(first), "MMM")} – ${format(parseISO(last), "MMM yyyy")}`;
  })();

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ap-ink">{t("title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <ViewModeToggle mode={viewMode} onChange={changeViewMode} />
          <RangeNavigator
            label={rangeLabel}
            onShift={shiftAnchor}
            onToday={onTodayPressed}
          />
        </div>
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
        {bulkSelection.size >= 2 && canManage && viewMode !== "season" ? (
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
            setQuickAdd({
              blockId,
              columnStart: range.columns[0]?.start ?? range.fetchStart,
              columnUnit: range.columns[0]?.unit ?? "day",
            })
          }
          canManage={canManage}
        />
      ) : (
        <div className="flex gap-4">
          <div className="min-w-0 flex-1">
            <BoardGrid
              blocks={visibleBlocks}
              columns={range.columns}
              grouped={grouped}
              canManage={canManage}
              selection={bulkSelection}
              viewMode={viewMode}
              onCellClick={(blockId, columnStart, unit, modifiers) => {
                if (!canManage) return;
                // Bulk-select works in week + month modes (day cells);
                // season mode aggregates by month and doesn't bulk.
                if (modifiers.shift && unit === "day") {
                  toggleCellSelection(blockId, columnStart);
                } else if (bulkSelection.size > 0) {
                  clearBulk();
                  setQuickAdd({ blockId, columnStart, columnUnit: unit });
                } else {
                  setQuickAdd({ blockId, columnStart, columnUnit: unit });
                }
              }}
              onChipClick={(activity) => setOpenActivity(activity)}
              onRecDrop={(blockId, columnStart, unit, payload) => {
                if (!canManage) return;
                // Land on the column's start date by default — Monday
                // (week) or first-of-month (month/season). The author
                // can drag the resulting chip later if they want a
                // different day.
                void unit;
                scheduleRec.mutate({
                  recommendationId: payload.recommendationId,
                  payload: { scheduled_date: columnStart, block_id: blockId },
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
          columnStart={quickAdd.columnStart}
          columnUnit={quickAdd.columnUnit}
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

interface ViewModeToggleProps {
  mode: ViewMode;
  onChange: (next: ViewMode) => void;
}

function ViewModeToggle({ mode, onChange }: ViewModeToggleProps): ReactNode {
  const { t } = useTranslation("board");
  const modes: { id: ViewMode; label: string }[] = [
    { id: "week", label: t("view.week") },
    { id: "month", label: t("view.month") },
    { id: "season", label: t("view.season") },
  ];
  return (
    <div
      role="tablist"
      aria-label={t("view.label")}
      className="inline-flex overflow-hidden rounded-md border border-ap-line bg-white text-sm"
    >
      {modes.map((m) => {
        const active = m.id === mode;
        return (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(m.id)}
            className={
              "px-3 py-1 transition-colors " +
              (active
                ? "bg-ap-primary text-white"
                : "text-ap-ink hover:bg-ap-bg/40")
            }
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

interface RangeNavigatorProps {
  label: string;
  onShift: (direction: -1 | 1) => void;
  onToday: () => void;
}

function RangeNavigator({
  label,
  onShift,
  onToday,
}: RangeNavigatorProps): ReactNode {
  const { t } = useTranslation("board");
  return (
    <div className="flex items-center gap-2 text-sm">
      <button
        type="button"
        className="rounded-md border border-ap-line bg-white px-2 py-1"
        onClick={() => onShift(-1)}
      >
        ‹ {t("nav.prev")}
      </button>
      <span className="px-2 text-ap-muted">{label}</span>
      <button
        type="button"
        className="rounded-md border border-ap-line bg-white px-2 py-1"
        onClick={() => onShift(1)}
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
  columns: ColumnDef[];
  grouped: Map<string, BoardActivity[]>;
  canManage: boolean;
  selection: Set<string>;
  viewMode: ViewMode;
  onCellClick: (
    blockId: string,
    columnStart: string,
    unit: "day" | "month",
    modifiers: { shift: boolean },
  ) => void;
  onChipClick: (a: BoardActivity) => void;
  onRecDrop?: (
    blockId: string,
    columnStart: string,
    unit: "day" | "month",
    payload: RecDropPayload,
  ) => void;
}

function BoardGrid({
  blocks,
  columns,
  grouped,
  canManage,
  selection,
  viewMode,
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
  const columnLabel = (col: ColumnDef): string => {
    const d = parseISO(col.start);
    if (col.unit === "day") {
      // "Mon\n12" — two lines so day-of-week label survives narrow cells.
      return viewMode === "week" ? format(d, "EEE d") : format(d, "d");
    }
    return format(d, "MMM");
  };
  // Cap visible chips per cell — month-day cells are narrow (~56px),
  // season month-cells are mid-width but cover ~30 days of activity.
  // Week-day cells are wide enough to show everything.
  const maxVisibleChips =
    viewMode === "week" ? Infinity : viewMode === "month" ? 2 : 3;
  const compactCells = viewMode === "month";
  return (
    <div className="overflow-x-auto rounded-xl border border-ap-line bg-ap-panel">
      <table className="min-w-full table-fixed border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-ap-bg/80">
          <tr>
            <th className="w-32 border-b border-r border-ap-line p-2 text-left text-xs font-semibold uppercase tracking-wider text-ap-muted">
              {t("col.block")}
            </th>
            {columns.map((col) => (
              <th
                key={col.start}
                className={
                  (compactCells ? "min-w-[56px] p-1 " : "min-w-[120px] p-2 ") +
                  "border-b border-r border-ap-line text-left text-xs font-semibold uppercase tracking-wider text-ap-muted"
                }
              >
                {columnLabel(col)}
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
              {columns.map((col) => {
                const key = `${block.id}|${col.start}`;
                const cellActivities = grouped.get(key) ?? [];
                const overflow =
                  cellActivities.length > maxVisibleChips
                    ? cellActivities.length - maxVisibleChips
                    : 0;
                const visible =
                  overflow > 0
                    ? cellActivities.slice(0, maxVisibleChips)
                    : cellActivities;
                const isSelected = selection.has(key);
                return (
                  <BoardCell
                    key={key}
                    canManage={canManage}
                    selected={isSelected}
                    compact={compactCells}
                    onClick={(modifiers) =>
                      onCellClick(block.id, col.start, col.unit, modifiers)
                    }
                    onRecDrop={
                      onRecDrop
                        ? (payload) =>
                            onRecDrop(block.id, col.start, col.unit, payload)
                        : undefined
                    }
                  >
                    {visible.map((a) => (
                      <ActivityChip
                        key={a.id}
                        activity={a}
                        onClick={(evt) => {
                          evt.stopPropagation();
                          onChipClick(a);
                        }}
                      />
                    ))}
                    {overflow > 0 ? (
                      <span className="rounded border border-dashed border-ap-line bg-ap-bg/40 px-1.5 py-0.5 text-[11px] text-ap-muted">
                        {t("cell.more", { count: overflow })}
                      </span>
                    ) : null}
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
