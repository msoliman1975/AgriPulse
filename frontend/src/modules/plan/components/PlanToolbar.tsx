import type { ReactNode } from "react";

import type { ActivityType } from "@/api/plans";
import { FilterChip } from "@/components/FilterChip";
import { activityTypeBgClass, activityTypeLabel } from "@/rules/formatting";
import { usePlanFilters } from "@/state/planFilters";

const TOGGLEABLE_TYPES: readonly ActivityType[] = [
  "planting",
  "fertilizing",
  "spraying",
  "pruning",
  "harvesting",
  "irrigation",
];

interface Props {
  totals: { all: number; visible: number; completed: number; atRisk: number; upcoming: number };
}

export function PlanToolbar({ totals }: Props): ReactNode {
  const { activeTypes, draftsOnly, toggleType, setDraftsOnly } = usePlanFilters();
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-ap-line bg-ap-panel px-4 py-2">
      <span className="text-xs font-medium uppercase tracking-wider text-ap-muted">Filter</span>
      <div className="flex flex-wrap items-center gap-2">
        {TOGGLEABLE_TYPES.map((t) => (
          <FilterChip
            key={t}
            active={activeTypes.has(t)}
            onToggle={() => toggleType(t)}
            swatchClassName={activityTypeBgClass(t)}
          >
            {activityTypeLabel(t)}
          </FilterChip>
        ))}
        <FilterChip active={draftsOnly} onToggle={() => setDraftsOnly(!draftsOnly)}>
          Drafts only
        </FilterChip>
      </div>
      <div className="ms-auto flex items-center gap-3 text-xs text-ap-muted">
        <Stat label="Activities" value={totals.visible} />
        <Stat label="Completed" value={totals.completed} />
        <Stat label="Upcoming" value={totals.upcoming} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }): ReactNode {
  return (
    <div className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-center">
      <div className="text-sm font-semibold text-ap-ink">{value}</div>
      <div className="text-[10px] uppercase tracking-wider">{label}</div>
    </div>
  );
}
