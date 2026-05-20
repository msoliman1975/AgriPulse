// TanStack Query hooks for tenant parameter overrides (PR-C consumer).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type TreeParameterOverrideResponse,
  type TreeParameterOverridesResponse,
  deleteTreeParameterOverride,
  getTreeParameterOverrides,
  upsertTreeParameterOverride,
} from "@/api/parameterOverrides";

/** Cache key prefix for invalidation. Reads + mutations both touch
 *  one key per `code`, keyed `["tree_param_overrides", code]`. */
const key = (code: string): readonly unknown[] => ["tree_param_overrides", code];

export function useTreeParameterOverrides(code: string | undefined) {
  return useQuery<TreeParameterOverridesResponse>({
    queryKey: code ? key(code) : ["tree_param_overrides", "_disabled"],
    queryFn: () => getTreeParameterOverrides(code!),
    enabled: Boolean(code),
    staleTime: 10_000,
  });
}

export function useUpsertTreeParameterOverride(code: string) {
  const qc = useQueryClient();
  return useMutation<
    TreeParameterOverrideResponse,
    Error,
    { paramName: string; value: unknown }
  >({
    mutationFn: ({ paramName, value }) => upsertTreeParameterOverride(code, paramName, value),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: key(code) });
    },
  });
}

export function useDeleteTreeParameterOverride(code: string) {
  const qc = useQueryClient();
  return useMutation<void, Error, { paramName: string }>({
    mutationFn: ({ paramName }) => deleteTreeParameterOverride(code, paramName),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: key(code) });
    },
  });
}
