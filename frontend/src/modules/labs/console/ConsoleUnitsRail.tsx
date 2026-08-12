// The units rail, with the two things a 36-block farm needs and the live
// rail does not have: a filter and a sort.
//
// Forked from mapnext/UnitsRail rather than extended in place. The filter and
// sort have to happen INSIDE the list construction, so extending would have
// meant four new props and a new toolbar row threaded through a component the
// live console renders — a bigger change to shared code than a separate file.
//
// The value column follows the selected index instead of being hardcoded to
// NDVI. A rail pinned to NDVI while the map paints moisture is quietly
// misleading, which is worse than showing nothing.
import clsx from "clsx";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Block } from "@/api/blocks";
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import type { UnitSummary } from "../map/types";
import { HEALTH_DOT, INDEX_META } from "../mapnext/constants";
import { Dot } from "../mapnext/ui";
import { filterUnits, sortUnits, unitValue, RAIL_SORTS, type RailSort } from "./railSort";

interface Props {
  blocks: Block[];
  summaries: Record<string, UnitSummary>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  activeIndex: ApiIndexCode;
}

export function ConsoleUnitsRail({
  blocks,
  summaries,
  selectedId,
  onSelect,
  activeIndex,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("farmConsole");
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<RailSort>("health");
  // The rail sits on the inline-start edge, so the collapse chevron points
  // toward that edge — which flips under RTL.
  const rtl = i18n.dir() === "rtl";

  // Only operational, summarisable units (logical pivots have no summary).
  const units = useMemo(() => blocks.filter((b) => summaries[b.id]), [blocks, summaries]);

  const { realBlocks, pivots, hiddenByFilter } = useMemo(() => {
    const matched = filterUnits(units, query);
    const ordered = sortUnits(matched, summaries, sort, activeIndex, i18n.language);
    return {
      realBlocks: ordered.filter((b) => b.unit_type !== "pivot" && b.unit_type !== "pivot_sector"),
      pivots: ordered.filter((b) => b.unit_type === "pivot" || b.unit_type === "pivot_sector"),
      hiddenByFilter: units.length - matched.length,
    };
  }, [units, query, sort, summaries, activeIndex, i18n.language]);

  return (
    <aside
      className={clsx(
        "flex flex-none flex-col border-e border-ap-line bg-ap-panel transition-all",
        collapsed ? "w-[46px]" : "w-[248px]",
      )}
    >
      <div className="flex h-[46px] flex-none items-center gap-2 border-b border-ap-line px-3">
        {!collapsed ? (
          <span className="flex-1 text-meta font-bold uppercase tracking-wide text-ap-muted">
            {t("rail.title")}
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="grid h-6 w-6 place-items-center rounded-md text-ap-muted hover:bg-ap-primary-soft"
          title={collapsed ? t("rail.expand") : t("rail.collapse")}
          aria-expanded={!collapsed}
        >
          {collapsed ? (rtl ? "‹" : "›") : rtl ? "›" : "‹"}
        </button>
      </div>

      {collapsed ? null : (
        <>
          <div className="flex flex-none gap-1.5 border-b border-ap-line px-2 py-2">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("railTools.filterPlaceholder")}
              aria-label={t("railTools.filterLabel")}
              className="min-w-0 flex-1 rounded-md border border-ap-line bg-ap-bg px-2 py-1 text-meta text-ap-ink focus:border-ap-primary focus:outline-none"
            />
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as RailSort)}
              aria-label={t("railTools.sortLabel")}
              className="w-[86px] flex-none rounded-md border border-ap-line bg-ap-bg px-1 py-1 text-meta text-ap-ink focus:border-ap-primary focus:outline-none"
            >
              {RAIL_SORTS.map((s) => (
                <option key={s} value={s}>
                  {t(`railTools.sort.${s}`)}
                </option>
              ))}
            </select>
          </div>

          <div className="flex-1 overflow-auto p-2">
            {realBlocks.length > 0 ? (
              <Group label={t("rail.blocks")} count={realBlocks.length} />
            ) : null}
            {realBlocks.map((b) => (
              <Row
                key={b.id}
                block={b}
                summary={summaries[b.id]}
                active={b.id === selectedId}
                onSelect={onSelect}
                activeIndex={activeIndex}
              />
            ))}
            {pivots.length > 0 ? <Group label={t("rail.pivots")} count={pivots.length} /> : null}
            {pivots.map((b) => (
              <Row
                key={b.id}
                block={b}
                summary={summaries[b.id]}
                active={b.id === selectedId}
                onSelect={onSelect}
                activeIndex={activeIndex}
              />
            ))}

            {units.length === 0 ? (
              <div className="px-2 py-6 text-center text-meta text-ap-muted">{t("rail.empty")}</div>
            ) : null}
            {units.length > 0 && realBlocks.length + pivots.length === 0 ? (
              <div className="px-2 py-6 text-center text-meta text-ap-muted">
                {t("railTools.noMatch", { query })}
              </div>
            ) : null}
            {hiddenByFilter > 0 && realBlocks.length + pivots.length > 0 ? (
              <div className="px-2 pb-1 pt-2 text-center text-meta text-ap-muted">
                {t("railTools.hidden", { count: hiddenByFilter })}
              </div>
            ) : null}
          </div>
        </>
      )}
    </aside>
  );
}

function Group({ label, count }: { label: string; count: number }): ReactNode {
  return (
    <div className="flex items-baseline gap-1.5 px-2 pb-1 pt-2.5 text-meta font-bold uppercase tracking-wide text-ap-muted">
      <span>{label}</span>
      <span className="tabular-nums opacity-70">{count}</span>
    </div>
  );
}

function Row({
  block,
  summary,
  active,
  onSelect,
  activeIndex,
}: {
  block: Block;
  summary: UnitSummary;
  active: boolean;
  onSelect: (id: string) => void;
  activeIndex: ApiIndexCode;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const name = block.name?.trim() || block.code;
  const value = unitValue(summary, activeIndex);
  const gridOnly = value === null;

  return (
    <button
      type="button"
      onClick={() => onSelect(block.id)}
      className={clsx(
        "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-start transition-colors",
        active
          ? "bg-ap-primary-soft shadow-[inset_2px_0_0_var(--tw-shadow-color)] shadow-ap-primary"
          : "hover:bg-ap-bg/60",
      )}
    >
      <Dot color={HEALTH_DOT[summary.health]} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-ap-ink">{name}</div>
        {summary.alert_count > 0 ? (
          <div className="text-meta text-ap-crit">⚠ {summary.alert_count}</div>
        ) : null}
      </div>
      <span
        className="text-meta font-semibold tabular-nums text-ap-muted"
        title={
          gridOnly
            ? t("inspector.gridOnlyIndex", { code: INDEX_META[activeIndex].label })
            : INDEX_META[activeIndex].label
        }
      >
        {value != null ? value.toFixed(2) : "—"}
      </span>
    </button>
  );
}
