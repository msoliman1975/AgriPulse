import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getRbacChanges,
  getRbacMatrix,
  resetRbacOverride,
  setRbacOverride,
  type RbacChange,
  type RbacMatrix,
  type RbacOverrideResult,
} from "@/api/rbacMatrix";

const ROOT = "rbacMatrix";

/**
 * The role -> capability matrix, with grants already resolved to their
 * effective values.
 *
 * `staleTime` is short now that the matrix is editable: it can change under a
 * session, and two admins on this page at once should not spend minutes
 * looking at each other's stale view.
 */
export function useRbacMatrix(): UseQueryResult<RbacMatrix> {
  return useQuery({
    queryKey: [ROOT, "matrix"],
    queryFn: getRbacMatrix,
    staleTime: 30_000,
  });
}

/** The change trail. Only fetched when the log is actually opened. */
export function useRbacChanges(enabled: boolean): UseQueryResult<RbacChange[]> {
  return useQuery({
    queryKey: [ROOT, "changes"],
    queryFn: () => getRbacChanges(),
    enabled,
    staleTime: 30_000,
  });
}

interface OverrideVars {
  role: string;
  capability: string;
  /** `null` resets to the shipped default; a boolean grants or revokes. */
  granted: boolean | null;
  note?: string;
}

/**
 * Apply or reset one override.
 *
 * Invalidates the matrix *and* `["me"]`: the caller's own effective grants may
 * have just changed, and `/v1/me` is what `useCapability` resolves against. An
 * admin who revokes a capability from a role they themselves hold should watch
 * the affordance disappear, not discover it on the next reload.
 */
export function useSetRbacOverride(): UseMutationResult<RbacOverrideResult, Error, OverrideVars> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: OverrideVars) =>
      vars.granted === null
        ? resetRbacOverride({ role: vars.role, capability: vars.capability, note: vars.note })
        : setRbacOverride({
            role: vars.role,
            capability: vars.capability,
            granted: vars.granted,
            note: vars.note,
          }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [ROOT] });
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
