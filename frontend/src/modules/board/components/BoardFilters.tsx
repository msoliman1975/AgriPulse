import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityType, BoardBlock, BoardResourceChip } from "@/api/plans";

const ALL_TYPES: ActivityType[] = [
  "irrigation",
  "fertilizing",
  "spraying",
  "observation",
  "planting",
  "harvesting",
  "pruning",
  "soil_prep",
];

interface BoardFiltersProps {
  blocks: BoardBlock[];
  knownResources: BoardResourceChip[];
  blockIds: Set<string>;
  setBlockIds: (next: Set<string>) => void;
  types: Set<ActivityType>;
  setTypes: (next: Set<ActivityType>) => void;
  resourceIds: Set<string>;
  setResourceIds: (next: Set<string>) => void;
  onClear: () => void;
}

/** Filter strip above the grid. Each control is a multi-select dropdown
 * with a chip-style summary. Empty Set = "all".
 */
export function BoardFilters({
  blocks,
  knownResources,
  blockIds,
  setBlockIds,
  types,
  setTypes,
  resourceIds,
  setResourceIds,
  onClear,
}: BoardFiltersProps): ReactNode {
  const { t } = useTranslation("board");
  const isFiltered = blockIds.size + types.size + resourceIds.size > 0;

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <MultiSelect
        label={t("filters.blocks")}
        all={blocks.map((b) => ({ id: b.id, label: b.code }))}
        selected={blockIds}
        onChange={setBlockIds}
      />
      <MultiSelect
        label={t("filters.types")}
        all={ALL_TYPES.map((typ) => ({ id: typ, label: t(`type.${typ}`) }))}
        selected={types as unknown as Set<string>}
        onChange={(s) => setTypes(s as unknown as Set<ActivityType>)}
      />
      <MultiSelect
        label={t("filters.assignees")}
        all={knownResources.map((r) => ({
          id: r.id,
          label: `${r.kind === "worker" ? "👤" : "🔧"} ${r.name}`,
        }))}
        selected={resourceIds}
        onChange={setResourceIds}
      />
      {isFiltered ? (
        <button
          type="button"
          onClick={onClear}
          className="ms-2 text-xs text-ap-muted underline-offset-2 hover:underline"
        >
          {t("filters.clear")}
        </button>
      ) : null}
    </div>
  );
}

interface MultiSelectProps {
  label: string;
  all: { id: string; label: string }[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}

function MultiSelect({
  label,
  all,
  selected,
  onChange,
}: MultiSelectProps): ReactNode {
  const summary =
    selected.size === 0
      ? label
      : `${label} (${selected.size})`;
  return (
    <details className="relative">
      <summary
        className={
          "cursor-pointer list-none rounded-md border px-2 py-1 text-sm " +
          (selected.size > 0
            ? "border-ap-primary bg-ap-primary-soft text-ap-primary"
            : "border-ap-line bg-white text-ap-ink")
        }
      >
        {summary}
      </summary>
      <div className="absolute z-20 mt-1 max-h-64 w-56 overflow-y-auto rounded-md border border-ap-line bg-white shadow-lg">
        {all.length === 0 ? (
          <p className="p-2 text-xs text-ap-muted">—</p>
        ) : (
          all.map((opt) => (
            <label
              key={opt.id}
              className="flex cursor-pointer items-center gap-2 px-2 py-1 hover:bg-ap-bg/50"
            >
              <input
                type="checkbox"
                checked={selected.has(opt.id)}
                onChange={() => {
                  const next = new Set(selected);
                  if (next.has(opt.id)) next.delete(opt.id);
                  else next.add(opt.id);
                  onChange(next);
                }}
              />
              <span className="text-sm">{opt.label}</span>
            </label>
          ))
        )}
      </div>
    </details>
  );
}
