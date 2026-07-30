import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type OrphanScan,
  type PurgeJob,
  type PurgeKind,
  type PurgePreview,
  type PurgeSubmitPayload,
  type TenantEntities,
  getPurgeJob,
  getPurgePreview,
  getTenantEntities,
  listPurgeJobs,
  scanOrphans,
  submitPurge,
} from "@/api/purge";

export const PURGE_KEY = "admin-purge" as const;

export function useTenantEntities(tenantId: string | undefined) {
  return useQuery<TenantEntities>({
    queryKey: [PURGE_KEY, "entities", tenantId] as const,
    queryFn: () => getTenantEntities(tenantId as string),
    enabled: Boolean(tenantId),
  });
}

export function usePurgePreview(target: { kind: PurgeKind; id: string; tenantId: string } | null) {
  return useQuery<PurgePreview>({
    queryKey: [PURGE_KEY, "preview", target?.kind, target?.id] as const,
    queryFn: () => getPurgePreview(target as NonNullable<typeof target>),
    enabled: Boolean(target),
    // Counts move as the tenant is used; a stale impact table is the one
    // thing this dialog must not show.
    staleTime: 0,
  });
}

export function useSubmitPurge(tenantId: string | undefined) {
  const qc = useQueryClient();
  return useMutation<PurgeJob, unknown, PurgeSubmitPayload>({
    mutationFn: submitPurge,
    onSuccess: (job) => {
      // A dry run touched nothing, so leave the caches alone.
      if (job.dry_run) return;
      void qc.invalidateQueries({ queryKey: [PURGE_KEY, "entities", tenantId] });
      void qc.invalidateQueries({ queryKey: [PURGE_KEY, "jobs"] });
      void qc.invalidateQueries({ queryKey: [PURGE_KEY, "orphans"] });
    },
  });
}

/** Polls while a queued/running job is in flight; stops once it settles. */
export function usePurgeJob(jobId: string | undefined) {
  return useQuery<PurgeJob>({
    queryKey: [PURGE_KEY, "job", jobId] as const,
    queryFn: () => getPurgeJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 2000 : false;
    },
  });
}

export function usePurgeJobs(tenantId?: string) {
  return useQuery<PurgeJob[]>({
    queryKey: [PURGE_KEY, "jobs", tenantId] as const,
    queryFn: () => listPurgeJobs(tenantId),
  });
}

export function useOrphanScan(enabled: boolean) {
  return useQuery<OrphanScan>({
    queryKey: [PURGE_KEY, "orphans"] as const,
    queryFn: scanOrphans,
    // The scan sweeps every tenant schema — run it on demand, not on mount.
    enabled,
    staleTime: 60_000,
  });
}
