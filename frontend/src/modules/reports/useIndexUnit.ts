import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { getIndexCatalog } from "@/api/indices";

/**
 * The unit symbol for an index, from `public.indices_catalog`.
 *
 * Every index was a dimensionless ratio until `lst` (Landsat surface
 * temperature) arrived, so the reports rendered `value.toFixed(3)` for all of
 * them. That is wrong for a temperature twice over — `31.850` claims a
 * precision a 100 m thermal pixel does not have, and a bare `31.85` next to an
 * NDVI of `0.723` reads as the same kind of number.
 *
 * Not gated on a farm: the catalog is platform-wide curated data, cached
 * across every farm and index the reader visits. A failure falls back to `""`,
 * the dimensionless case, so the report still renders numbers.
 */
export function useIndexUnit(indexCode: string): string {
  const catalogQ = useQuery({
    queryKey: ["indices", "catalog"] as const,
    queryFn: getIndexCatalog,
    staleTime: 60 * 60_000,
  });
  return useMemo(
    () => catalogQ.data?.find((entry) => entry.code === indexCode)?.unit ?? "",
    [catalogQ.data, indexCode],
  );
}
