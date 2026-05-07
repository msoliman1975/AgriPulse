import clsx from "clsx";
import type { ReactNode } from "react";

import type { Block } from "@/api/blocks";
import { Skeleton } from "@/components/Skeleton";
import { usePlanSelection } from "@/state/planSelection";

interface Props {
  blocks: Block[];
  isLoading: boolean;
}

export function LaneSidebar({ blocks, isLoading }: Props): ReactNode {
  const { laneId, setLane } = usePlanSelection();
  return (
    <aside
      aria-label="Land units sidebar"
      className="w-64 flex-none overflow-y-auto border-e border-ap-line bg-ap-panel"
    >
      <header className="px-3 py-3 text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
        Land units
      </header>
      <div className="flex flex-col gap-0.5 px-2 pb-3">
        {isLoading ? (
          <>
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </>
        ) : blocks.length === 0 ? (
          <p className="px-2 py-3 text-sm text-ap-muted">
            No land units in this farm yet.
          </p>
        ) : (
          blocks.map((b) => (
            <button
              type="button"
              key={b.id}
              onClick={() => setLane(b.id)}
              className={clsx(
                "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-start text-sm",
                laneId === b.id
                  ? "bg-ap-primary-soft text-ap-primary"
                  : "text-ap-ink hover:bg-ap-line/40",
              )}
            >
              <span
                aria-hidden="true"
                className={clsx(
                  "mt-1 h-2.5 w-2.5 flex-none",
                  b.unit_type === "block" ? "rounded-sm" : "rounded-full",
                  "bg-ap-primary",
                )}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{b.name ?? b.code}</span>
                <span className="block truncate text-[11px] text-ap-muted">
                  {b.area_value.toFixed(1)} {b.area_unit}
                  {b.irrigation_system ? ` · ${b.irrigation_system}` : ""}
                </span>
              </span>
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
