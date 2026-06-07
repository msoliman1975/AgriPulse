import type { SignalDefinition, ValueKind } from "@/api/signals";

export interface CatalogFilter {
  search: string;
  kinds: ReadonlySet<ValueKind>;
  showArchived: boolean;
}

/**
 * Client-side catalog filter for the definitions list (CS-13): free-text
 * over name/code/description, value-kind multi-select, and archived
 * visibility. Pure so the page's useMemo and the tests share one source.
 */
export function filterDefinitions(
  defs: readonly SignalDefinition[],
  { search, kinds, showArchived }: CatalogFilter,
): SignalDefinition[] {
  const q = search.trim().toLowerCase();
  return defs.filter((d) => {
    if (!showArchived && !d.is_active) return false;
    if (kinds.size > 0 && !kinds.has(d.value_kind)) return false;
    if (!q) return true;
    return (
      d.name.toLowerCase().includes(q) ||
      d.code.toLowerCase().includes(q) ||
      (d.description ?? "").toLowerCase().includes(q)
    );
  });
}
