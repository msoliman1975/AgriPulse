// Collapsible left navigator for /labs/map-next. Lets the user select a
// unit by list (or by clicking the map) and shows at-a-glance health +
// the current NDVI per unit. No "add" button here — creation lives only
// in the view bar's + Add menu.
import clsx from "clsx";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Block } from "@/api/blocks";
import type { UnitSummary } from "../map/types";
import { HEALTH_DOT } from "./constants";
import { Dot } from "./ui";

interface Props {
  blocks: Block[];
  summaries: Record<string, UnitSummary>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function UnitsRail({ blocks, summaries, selectedId, onSelect }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [collapsed, setCollapsed] = useState(false);

  // Only operational, summarisable units (logical pivots have no summary).
  const units = blocks.filter((b) => summaries[b.id]);
  const realBlocks = units.filter((b) => b.unit_type !== "pivot" && b.unit_type !== "pivot_sector");
  const pivots = units.filter((b) => b.unit_type === "pivot" || b.unit_type === "pivot_sector");

  return (
    <aside
      className={clsx(
        "flex flex-none flex-col border-e border-ap-line bg-ap-panel transition-all",
        collapsed ? "w-[46px]" : "w-[248px]",
      )}
    >
      <div className="flex h-[46px] flex-none items-center gap-2 border-b border-ap-line px-3">
        {!collapsed ? (
          <span className="flex-1 text-[12px] font-bold uppercase tracking-wide text-ap-muted">
            {t("rail.title")}
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="grid h-6 w-6 place-items-center rounded-md text-ap-muted hover:bg-ap-primary-soft"
          title={collapsed ? t("rail.expand") : t("rail.collapse")}
        >
          {collapsed ? "›" : "‹"}
        </button>
      </div>
      {!collapsed ? (
        <div className="flex-1 overflow-auto p-2">
          {realBlocks.length > 0 ? <Group label={t("rail.blocks")} /> : null}
          {realBlocks.map((b) => (
            <Row key={b.id} block={b} summary={summaries[b.id]} active={b.id === selectedId} onSelect={onSelect} />
          ))}
          {pivots.length > 0 ? <Group label={t("rail.pivots")} /> : null}
          {pivots.map((b) => (
            <Row key={b.id} block={b} summary={summaries[b.id]} active={b.id === selectedId} onSelect={onSelect} />
          ))}
          {units.length === 0 ? <div className="px-2 py-6 text-center text-[12px] text-ap-muted">{t("rail.empty")}</div> : null}
        </div>
      ) : null}
    </aside>
  );
}

function Group({ label }: { label: string }): ReactNode {
  return <div className="px-2 pb-1 pt-2.5 text-[11px] font-bold uppercase tracking-wide text-ap-muted">{label}</div>;
}

function Row({
  block,
  summary,
  active,
  onSelect,
}: {
  block: Block;
  summary: UnitSummary;
  active: boolean;
  onSelect: (id: string) => void;
}): ReactNode {
  const name = block.name?.trim() || block.code;
  return (
    <button
      type="button"
      onClick={() => onSelect(block.id)}
      className={clsx(
        "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-start transition-colors",
        active ? "bg-ap-primary-soft shadow-[inset_2px_0_0_var(--tw-shadow-color)] shadow-ap-primary" : "hover:bg-ap-bg/60",
      )}
    >
      <Dot color={HEALTH_DOT[summary.health]} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-semibold text-ap-ink">{name}</div>
        {summary.alert_count > 0 ? (
          <div className="text-[11px] text-ap-crit">⚠ {summary.alert_count}</div>
        ) : null}
      </div>
      <span className="text-[12px] font-semibold tabular-nums text-ap-muted">
        {summary.ndvi_current != null ? summary.ndvi_current.toFixed(2) : "—"}
      </span>
    </button>
  );
}
