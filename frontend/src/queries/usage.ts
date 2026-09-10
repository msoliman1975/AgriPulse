import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  getUsageFilterOptions,
  getUsageOverview,
  type UsageFilterOptions,
  type UsageOverview,
  type UsageQuery,
} from "@/api/usage";

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
    queryKey: [
      ROOT,
      query.start,
      query.end,
      query.tenantId ?? null,
      query.userId ?? null,
      query.includeStaff ?? false,
    ],
    queryFn: () => getUsageOverview(query),
    staleTime: 5 * 60_000,
  });
}

/**
 * The picker option lists.
 *
 * `staleTime` is longer than the overview's: a tenant that used the product
 * yesterday is still a valid choice a quarter of an hour later, and this list
 * is re-requested every time the tenant filter changes (it narrows the people
 * list), so it should not re-scan on each keystroke of a date change.
 */
export function useUsageFilterOptions(query: {
  start: string;
  end: string;
  tenantId?: string | null;
  includeStaff?: boolean;
}): UseQueryResult<UsageFilterOptions> {
  return useQuery({
    queryKey: [
      ROOT,
      "filters",
      query.start,
      query.end,
      query.tenantId ?? null,
      query.includeStaff ?? false,
    ],
    queryFn: () => getUsageFilterOptions(query),
    staleTime: 15 * 60_000,
  });
}
