import { addMonths, differenceInCalendarDays, format, parseISO, startOfMonth } from "date-fns";
import type { ReactNode } from "react";

import type { Block } from "@/api/blocks";
import type { PlanActivity } from "@/api/plans";
import type { ConflictEdge } from "@/rules/conflicts";

import { Lane } from "./Lane";

interface Props {
  blocks: Block[];
  activities: PlanActivity[];
  conflicts: ConflictEdge[];
  seasonStart: Date;
  seasonEnd: Date;
}

export function Timeline({
  blocks,
  activities,
  conflicts,
  seasonStart,
  seasonEnd,
}: Props): ReactNode {
  const totalDays = differenceInCalendarDays(seasonEnd, seasonStart);
  const months = monthsBetween(seasonStart, seasonEnd);
  const today = new Date();
  const todayPct =
    today >= seasonStart && today <= seasonEnd
      ? (differenceInCalendarDays(today, seasonStart) / totalDays) * 100
      : null;

  return (
    <div className="flex-1 overflow-x-auto overflow-y-auto">
      <div className="relative min-w-[1000px]">
        {/* Month header */}
        <div className="sticky top-0 z-10 flex border-b border-ap-line bg-ap-panel">
          {months.map((m) => {
            const monthStart = m.start;
            const monthEnd = m.end;
            const startPct = (differenceInCalendarDays(monthStart, seasonStart) / totalDays) * 100;
            const widthPct = (differenceInCalendarDays(monthEnd, monthStart) / totalDays) * 100;
            return (
              <div
                key={m.start.toISOString()}
                className="border-e border-ap-line px-2 py-2 text-xs font-medium text-ap-muted"
                style={{ position: "absolute", left: `${startPct}%`, width: `${widthPct}%` }}
              >
                {format(m.start, "MMM yyyy")}
              </div>
            );
          })}
          <div className="h-9 w-full" aria-hidden="true" />
        </div>

        {/* Today line */}
        {todayPct !== null ? (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 z-20 w-[2px] bg-ap-accent"
            style={{ left: `${todayPct}%` }}
          >
            <div className="absolute -top-px left-0 -translate-x-1/2 rounded bg-ap-accent px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white shadow-card">
              Today
            </div>
          </div>
        ) : null}

        {/* Lanes */}
        <div>
          {blocks.map((b) => {
            const laneActivities = activities.filter((a) => a.block_id === b.id);
            const laneConflicts = conflicts.filter((c) => {
              return laneActivities.some((a) => c.activityIds.includes(a.id));
            });
            return (
              <Lane
                key={b.id}
                block={b}
                activities={laneActivities}
                conflicts={laneConflicts}
                seasonStart={seasonStart}
                totalDays={totalDays}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

function monthsBetween(start: Date, end: Date): { start: Date; end: Date }[] {
  const out: { start: Date; end: Date }[] = [];
  let cursor = startOfMonth(start);
  while (cursor < end) {
    const next = addMonths(cursor, 1);
    out.push({ start: cursor, end: next > end ? end : next });
    cursor = next;
  }
  return out;
}

// Suppress unused import warning if parseISO ends up not needed.
void parseISO;
