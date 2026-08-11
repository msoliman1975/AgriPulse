import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  enrolFieldWorker,
  fetchFieldEnrolmentAudit,
  reRoleFieldWorkers,
  reissueFieldPin,
  type EnrolPayload,
  type FieldEnrolmentAudit,
} from "@/api/fieldAccess";

export function useFieldEnrolmentAudit(farmId: string | null) {
  return useQuery<FieldEnrolmentAudit>({
    queryKey: ["field-access", "audit", farmId],
    queryFn: () => fetchFieldEnrolmentAudit(farmId as string),
    enabled: !!farmId,
    // Short: enrolling, re-roling and archiving all move people between the
    // four buckets, and a stale worklist invites the same action twice.
    staleTime: 10_000,
  });
}

/**
 * Enrolment moves a worker from `ready_to_enrol` into `enrolled`, and the
 * resources list gains a `membership_id`, so both have to be invalidated —
 * the worker row is written by the same call.
 */
export function useEnrolFieldWorker(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: EnrolPayload) => enrolFieldWorker(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["field-access", "audit", farmId] });
      void qc.invalidateQueries({ queryKey: ["resources", farmId] });
    },
  });
}

export function useReRoleFieldWorkers(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (worker_ids: string[]) =>
      reRoleFieldWorkers({ farm_id: farmId as string, worker_ids }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["field-access", "audit", farmId] });
      void qc.invalidateQueries({ queryKey: ["resources", farmId] });
    },
  });
}

/**
 * Deliberately not invalidating anything: a new PIN changes no list. The
 * result is the PIN itself, shown once.
 */
export function useReissueFieldPin(farmId: string | null) {
  return useMutation({
    mutationFn: (user_id: string) => reissueFieldPin({ user_id, farm_id: farmId as string }),
  });
}
