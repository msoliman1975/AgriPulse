import { differenceInCalendarDays, parseISO } from "date-fns";
import clsx from "clsx";
import type { ReactNode } from "react";

import type { Block } from "@/api/blocks";
import type { PlanActivity } from "@/api/plans";
import { activityTypeBgClass, activityTypeLabel } from "@/rules/formatting";
import type { ConflictEdge } from "@/rules/conflicts";
import { usePlanFilters } from "@/state/planFilters";
import { usePlanSelection } from "@/state/planSelection";

interface Props {
  block: Block;
  activities: PlanActivity[];
  conflicts: ConflictEdge[];
  seasonStart: Date;
  totalDays: number;
}

const MIN_BAR_WIDTH_PCT = 1.2;

export function Lane({ block, activities, conflicts, seasonStart, totalDays }: Props): ReactNode {
  const { laneId, activityId, setBoth, setLane } = usePlanSelection();
  const { activeTypes, draftsOnly } = usePlanFilters();
  const isSelected = laneId === block.id;
  const visible = activities.filter(
    (a) => activeTypes.has(a.activity_type) && (!draftsOnly || a.status === "scheduled"),
  );
  const conflictIds = new Set<string>();
  for (const c of conflicts) {
    conflictIds.add(c.activityIds[0]);
    conflictIds.add(c.activityIds[1]);
  }

  return (
    <div
      className={clsx(
        "relative flex border-b border-ap-line",
        isSelected ? "bg-ap-primary-soft/30" : "",
      )}
    >
      <button
        type="button"
        onClick={() => setLane(block.id)}
        className="z-10 flex w-48 flex-none flex-col items-start justify-center border-e border-ap-line bg-ap-panel px-3 py-2 text-start text-sm hover:bg-ap-line/30"
      >
        <span className="font-medium text-ap-ink">{block.name ?? block.code}</span>
        <span className="text-[11px] text-ap-muted">
          {block.area_value.toFixed(1)} {block.area_unit}
          {block.irrigation_system ? ` · ${block.irrigation_system}` : ""}
        </span>
      </button>
      <div className="relative h-16 flex-1">
        {/* Stripes */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              "repeating-linear-gradient(to right, transparent 0, transparent calc(100%/8 - 1px), rgba(0,0,0,0.04) calc(100%/8 - 1px), rgba(0,0,0,0.04) calc(100%/8))",
          }}
        />
        {visible.map((a) => {
          const start = parseISO(a.scheduled_date);
          const startDays = differenceInCalendarDays(start, seasonStart);
          const leftPct = (startDays / totalDays) * 100;
          const widthPct = Math.max((a.duration_days / totalDays) * 100, MIN_BAR_WIDTH_PCT);
          if (leftPct < -widthPct || leftPct > 100) return null;
          const isPicked = activityId === a.id;
          const conflicting = conflictIds.has(a.id);
          return (
            <button
              type="button"
              key={a.id}
              onClick={() => setBoth(block.id, a.id)}
              title={`${activityTypeLabel(a.activity_type)} · ${a.product_name ?? ""}`}
              className={clsx(
                "absolute top-2 h-8 truncate rounded px-2 text-[11px] font-medium text-white shadow-card transition-shadow",
                activityTypeBgClass(a.activity_type),
                a.status === "skipped" && "opacity-30 line-through",
                a.status === "completed" && "ring-1 ring-ap-primary",
                conflicting && "ring-2 ring-ap-warn ring-offset-1",
                isPicked && "outline outline-2 outline-offset-2 outline-ap-ink",
                a.status === "scheduled" && "opacity-90",
              )}
              style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
            >
              {a.product_name ?? activityTypeLabel(a.activity_type)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
