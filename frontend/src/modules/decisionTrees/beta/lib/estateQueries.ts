/**
 * Query hooks for the estate dry run and the run-results screen.
 *
 * The run poll is the only unusual one. A run is a Celery task, so the screen
 * asks again while the row says `running` and stops the moment it says `done`
 * or `failed`. Polling for ever after a failure is how a screen ends up
 * hammering a route for a row that will never change.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getEstateDryRun,
  listBetaRunResults,
  listEstateDryRuns,
  startEstateDryRun,
  type EstateRun,
  type EstateRunStarted,
} from "./estateApi";

const KEY = ["decision_trees_estate"] as const;

/** How often a running report is asked about. */
const POLL_MS = 3000;

export function useEstateRuns(treeId: string | null, tenantId: string | null) {
  return useQuery({
    queryKey: [...KEY, "runs", treeId, tenantId] as const,
    queryFn: () => listEstateDryRuns(treeId!, tenantId),
    enabled: Boolean(treeId) && Boolean(tenantId),
  });
}

export function useEstateRun(treeId: string | null, runId: string | null, tenantId: string | null) {
  return useQuery<EstateRun>({
    queryKey: [...KEY, "run", treeId, runId, tenantId] as const,
    queryFn: () => getEstateDryRun(treeId!, runId!, tenantId),
    enabled: Boolean(treeId) && Boolean(runId) && Boolean(tenantId),
    refetchInterval: (query) => (query.state.data?.state === "running" ? POLL_MS : false),
  });
}

export function useStartEstateDryRun(treeId: string | null) {
  const qc = useQueryClient();
  return useMutation<EstateRunStarted, Error, { tenantId: string; blockLimit?: number }>({
    mutationFn: ({ tenantId, blockLimit }) => startEstateDryRun(treeId!, tenantId, blockLimit),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...KEY, "runs"] }),
  });
}

export function useBetaRunResults(treeId: string | null, tenantId: string | null) {
  return useQuery({
    queryKey: [...KEY, "results", treeId, tenantId] as const,
    queryFn: () => listBetaRunResults(treeId!, tenantId),
    enabled: Boolean(treeId) && Boolean(tenantId),
  });
}
