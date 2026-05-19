import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchMe, type Me } from "@/api/me";

/**
 * Cached react-query wrapper around /v1/me. Centralises the
 * fetchMe call so every shell + page component can derive
 * tenant, role, and preferences without re-fetching.
 *
 * Stale-time is intentionally long (5 min) — `/me` rarely changes
 * within a session and the data is small enough that refetching
 * isn't worth the bandwidth. Components that need a guaranteed-
 * fresh value should call `qc.invalidateQueries({queryKey: ["me"]})`
 * after a write (e.g. profile edit).
 */
export function useMe(): UseQueryResult<Me> {
  return useQuery({
    queryKey: ["me"] as const,
    queryFn: fetchMe,
    staleTime: 5 * 60_000,
    retry: false,
  });
}
