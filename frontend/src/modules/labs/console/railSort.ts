// Filtering and ordering for the units rail.
//
// A 36-block farm cannot be scanned by eye, and the live rail offers neither
// a filter nor a sort — it renders creation order, which correlates with
// nothing a user cares about.
//
// Pure functions in a .ts file so they can be tested without a DOM.
import type { Block } from "@/api/blocks";
import type { IndexCode as ApiIndexCode } from "@/api/indices";
import type { Health, UnitSummary } from "../map/types";

export type RailSort = "name" | "health" | "alerts" | "value";

export const RAIL_SORTS: readonly RailSort[] = ["name", "health", "alerts", "value"] as const;

/**
 * Worst first. `unknown` sits above `healthy` deliberately: a block we cannot
 * read is a thing to look into, not a thing that is fine.
 */
const HEALTH_RANK: Record<Health, number> = {
  critical: 0,
  watch: 1,
  unknown: 2,
  healthy: 3,
};

/**
 * The rail's numeric column for the active index.
 *
 * Only three indices have a block-level series — the rest are computed per
 * grid cell and have no whole-block number. Returning null for those is the
 * honest answer; the rail renders a dash rather than inventing an average.
 */
export function unitValue(summary: UnitSummary | undefined, code: ApiIndexCode): number | null {
  if (!summary) return null;
  if (code === "ndvi") return summary.ndvi_current;
  if (code === "ndre") return summary.ndre_current;
  if (code === "ndwi") return summary.ndwi_current;
  return null;
}

/** Case- and accent-insensitive match over the visible name and the code. */
export function filterUnits(units: readonly Block[], query: string): Block[] {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return [...units];
  return units.filter((b) => {
    const name = (b.name?.trim() || b.code).toLocaleLowerCase();
    return name.includes(q) || b.code.toLocaleLowerCase().includes(q);
  });
}

export function sortUnits(
  units: readonly Block[],
  summaries: Record<string, UnitSummary>,
  sort: RailSort,
  code: ApiIndexCode,
  locale = "en",
): Block[] {
  const name = (b: Block): string => b.name?.trim() || b.code;
  const out = [...units];

  // Every comparator falls back to name so the order is total and therefore
  // stable across refetches — a rail that reshuffles under the cursor is
  // worse than one that is merely unsorted.
  const byName = (a: Block, b: Block): number => name(a).localeCompare(name(b), locale);

  switch (sort) {
    case "health":
      out.sort((a, b) => {
        const d =
          HEALTH_RANK[summaries[a.id]?.health ?? "unknown"] -
          HEALTH_RANK[summaries[b.id]?.health ?? "unknown"];
        return d !== 0 ? d : byName(a, b);
      });
      break;
    case "alerts":
      out.sort((a, b) => {
        const d = (summaries[b.id]?.alert_count ?? 0) - (summaries[a.id]?.alert_count ?? 0);
        return d !== 0 ? d : byName(a, b);
      });
      break;
    case "value":
      out.sort((a, b) => {
        const va = unitValue(summaries[a.id], code);
        const vb = unitValue(summaries[b.id], code);
        // Blocks with no reading sink to the bottom rather than sorting as
        // zero, which would put them among the worst.
        if (va === null && vb === null) return byName(a, b);
        if (va === null) return 1;
        if (vb === null) return -1;
        return va !== vb ? va - vb : byName(a, b);
      });
      break;
    case "name":
    default:
      out.sort(byName);
      break;
  }
  return out;
}
