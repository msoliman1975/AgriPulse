import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { getUsageOverview, type UsageOverview, type UsageQuery } from "@/api/usage";

const ROOT = "platformUsage";

/**
 * The whole usage dashboard in one query.
 *
 * `staleTime` is five minutes because the underlying aggregate refreshes
 * hourly. A shorter window would re-run seven scans over the same 30 days to
 * return numbers that have not moved.
 */
export function useUsageOverview(query: UsageQuery): UseQueryResult<UsageOverview> {
  return useQuery({
    queryKey: [ROOT, query.start, query.end, query.tenantId ?? null, query.includeStaff ?? false],
    queryFn: () => getUsageOverview(query),
    staleTime: 5 * 60_000,
  });
}
