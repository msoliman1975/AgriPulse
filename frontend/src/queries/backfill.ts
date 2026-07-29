import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import {
  createBackfillRun,
  isRunActive,
  listBackfillFarms,
  listBackfillRuns,
  listBackfillTenants,
  type BackfillFarm,
  type BackfillRun,
  type BackfillTenant,
  type RunPayload,
} from "@/api/backfill";

const ROOT = "backfill";

export function useBackfillTenants(): UseQueryResult<BackfillTenant[]> {
  return useQuery({
    queryKey: [ROOT, "tenants"],
    queryFn: listBackfillTenants,
    staleTime: 60_000,
  });
}

export function useBackfillFarms(tenantId: string | null): UseQueryResult<BackfillFarm[]> {
  return useQuery({
    queryKey: [ROOT, "farms", tenantId],
    queryFn: () => listBackfillFarms(tenantId as string),
    enabled: Boolean(tenantId),
  });
}

/**
 * Run history.
 *
 * Polls only while something is actually in flight — a console left open
 * on a settled list should not hammer the API. Once every run is terminal
 * the interval drops to `false` and the query goes quiet until a mutation
 * invalidates it.
 */
export function useBackfillRuns(): UseQueryResult<BackfillRun[]> {
  return useQuery({
    queryKey: [ROOT, "runs"],
    queryFn: () => listBackfillRuns({ limit: 100 }),
    refetchInterval: (query) => {
      const rows = query.state.data;
      return rows?.some(isRunActive) ? 5_000 : false;
    },
  });
}

export function useCreateBackfillRun(): UseMutationResult<
  BackfillRun,
  unknown,
  { tenantId: string; payload: RunPayload }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, payload }) => createBackfillRun(tenantId, payload),
    onSuccess: (_run, { tenantId }) => {
      // The new row belongs in the list, and the farm it claimed must now
      // read as occupied in the picker.
      void qc.invalidateQueries({ queryKey: [ROOT, "runs"] });
      void qc.invalidateQueries({ queryKey: [ROOT, "farms", tenantId] });
    },
  });
}
