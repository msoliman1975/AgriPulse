import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  acknowledgePlatformAlert,
  getPlatformAlertSummary,
  listPlatformAlerts,
  resolvePlatformAlert,
  runPlatformAlertSweep,
  type PlatformAlertFilters,
} from "@/api/platformAlerts";

// The sweep runs on a 10-minute Beat cadence, so polling faster than that
// only re-reads the same rows. 60s is a compromise: fast enough that an
// operator who just fixed something sees the banner clear without a manual
// reload, slow enough that the summary query is not a background load.
const SUMMARY_REFETCH_MS = 60_000;
const LIST_REFETCH_MS = 60_000;

export const platformAlertKeys = {
  all: ["platform", "alerts"] as const,
  summary: () => [...platformAlertKeys.all, "summary"] as const,
  list: (filters: PlatformAlertFilters) => [...platformAlertKeys.all, "list", filters] as const,
};

/**
 * Feeds the red bar. `enabled` is passed in rather than read here so the
 * banner can hold the hook unconditionally and still not fire the request
 * for a non-platform-admin, who would only get a 403.
 */
export function usePlatformAlertSummary(enabled: boolean) {
  return useQuery({
    queryKey: platformAlertKeys.summary(),
    queryFn: getPlatformAlertSummary,
    enabled,
    refetchInterval: SUMMARY_REFETCH_MS,
    staleTime: SUMMARY_REFETCH_MS / 2,
    // A failing summary must not surface an error to a user who is midway
    // through unrelated work — the banner just stays hidden.
    retry: 1,
  });
}

/**
 * `enabled` defaults to true for the page, which is always fetching while
 * it is mounted. The bell drawer passes `false` while it is closed - a
 * drawer nobody has opened should not be polling every 60 seconds on every
 * page in the app.
 */
export function usePlatformAlerts(filters: PlatformAlertFilters, enabled = true) {
  return useQuery({
    queryKey: platformAlertKeys.list(filters),
    queryFn: () => listPlatformAlerts(filters),
    enabled,
    refetchInterval: LIST_REFETCH_MS,
    staleTime: LIST_REFETCH_MS / 2,
  });
}

/** Acknowledging keeps the alert live, so the summary has to refetch too. */
export function useAcknowledgePlatformAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (alertId: string) => acknowledgePlatformAlert(alertId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: platformAlertKeys.all });
    },
  });
}

export function useResolvePlatformAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (alertId: string) => resolvePlatformAlert(alertId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: platformAlertKeys.all });
    },
  });
}

export function useRunPlatformAlertSweep() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runPlatformAlertSweep,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: platformAlertKeys.all });
    },
  });
}
