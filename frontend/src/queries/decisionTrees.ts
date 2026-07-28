import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type DecisionTree,
  type DecisionTreeCreatePayload,
  type DecisionTreeDetail,
  type DecisionTreeListStatus,
  type DecisionTreeUpdatePayload,
  type DecisionTreeVersionCreatePayload,
  type DryRunPayload,
  type DryRunResponse,
  appendDecisionTreeVersion,
  archiveDecisionTree,
  createDecisionTree,
  dryRunDecisionTree,
  getDecisionTree,
  getDecisionTreeCandidateBlocks,
  listDecisionTrees,
  publishDecisionTreeVersion,
  restoreDecisionTree,
  updateDecisionTree,
} from "@/api/decisionTrees";

export function useDecisionTrees(status: DecisionTreeListStatus = "active") {
  return useQuery({
    queryKey: ["decision_trees", "list", status] as const,
    queryFn: () => listDecisionTrees(status),
    staleTime: 30_000,
  });
}

export function useDecisionTree(code: string | undefined) {
  return useQuery({
    queryKey: ["decision_trees", "detail", code] as const,
    queryFn: () => getDecisionTree(code!),
    enabled: Boolean(code),
    staleTime: 10_000,
  });
}

export function useCreateDecisionTree() {
  const qc = useQueryClient();
  return useMutation<DecisionTreeDetail, Error, DecisionTreeCreatePayload>({
    mutationFn: createDecisionTree,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["decision_trees"] });
    },
  });
}

export function useUpdateDecisionTree() {
  const qc = useQueryClient();
  return useMutation<
    DecisionTreeDetail,
    Error,
    { code: string; payload: DecisionTreeUpdatePayload }
  >({
    mutationFn: ({ code, payload }) => updateDecisionTree(code, payload),
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: ["decision_trees", "detail", vars.code] });
      void qc.invalidateQueries({ queryKey: ["decision_trees", "list"] });
    },
  });
}

export function useArchiveDecisionTree() {
  const qc = useQueryClient();
  return useMutation<void, Error, { code: string }>({
    mutationFn: ({ code }) => archiveDecisionTree(code),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["decision_trees"] });
    },
  });
}

export function useRestoreDecisionTree() {
  const qc = useQueryClient();
  return useMutation<DecisionTreeDetail, Error, { code: string }>({
    mutationFn: ({ code }) => restoreDecisionTree(code),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["decision_trees"] });
    },
  });
}

export function useAppendDecisionTreeVersion() {
  const qc = useQueryClient();
  return useMutation<
    DecisionTreeDetail,
    Error,
    { code: string; payload: DecisionTreeVersionCreatePayload }
  >({
    mutationFn: ({ code, payload }) => appendDecisionTreeVersion(code, payload),
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: ["decision_trees", "detail", vars.code] });
      void qc.invalidateQueries({ queryKey: ["decision_trees", "list"] });
    },
  });
}

export function usePublishDecisionTreeVersion() {
  const qc = useQueryClient();
  return useMutation<
    { code: string; version: number; published_at: string },
    Error,
    { code: string; version: number }
  >({
    mutationFn: ({ code, version }) => publishDecisionTreeVersion(code, version),
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: ["decision_trees", "detail", vars.code] });
      void qc.invalidateQueries({ queryKey: ["decision_trees", "list"] });
    },
  });
}

export function useDryRunDecisionTree() {
  return useMutation<DryRunResponse, Error, { code: string; payload: DryRunPayload }>({
    mutationFn: ({ code, payload }) => dryRunDecisionTree(code, payload),
  });
}

// Blocks the tree's targeting admits — populates the dry-run picker. Keyed
// off the published targeting (not the live draft), so it refetches when the
// detail is invalidated after a publish.
export function useDecisionTreeCandidateBlocks(code: string | undefined) {
  return useQuery({
    queryKey: ["decision_trees", "candidate_blocks", code] as const,
    queryFn: () => getDecisionTreeCandidateBlocks(code!),
    enabled: Boolean(code),
    staleTime: 30_000,
  });
}

// Re-exports so callers can grab the type from one place.
export type { DecisionTree, DecisionTreeDetail };
