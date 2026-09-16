import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  betaDryRun,
  compileBetaTreeRemote,
  createFinding,
  deleteFinding,
  getBetaCandidateBlocks,
  getBetaTree,
  listBetaTrees,
  listFindings,
  publishBetaTreeVersion,
  saveBetaTreeDraft,
  updateFinding,
  type BetaCompileResponse,
  type BetaDryRunPayload,
  type BetaDryRunResponse,
  type BetaTreeDetail,
  type Finding,
  type FindingSource,
  type FindingWritePayload,
} from "@/api/decisionTreesBeta";

/**
 * Query hooks for the beta designer.
 *
 * These read from `@/api/decisionTreesBeta`, which is mocked in this branch.
 * Nothing here knows that, so the swap to the real endpoints touches only that
 * one file.
 */

const KEY = ["decision_trees_beta"] as const;

export function useFindingCatalogue() {
  return useQuery({
    queryKey: [...KEY, "findings"] as const,
    queryFn: listFindings,
    staleTime: 60_000,
  });
}

export function useCreateFinding() {
  const qc = useQueryClient();
  return useMutation<Finding, Error, { source: FindingSource; payload: FindingWritePayload }>({
    mutationFn: ({ source, payload }) => createFinding(source, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...KEY, "findings"] }),
  });
}

export function useUpdateFinding() {
  const qc = useQueryClient();
  return useMutation<
    Finding,
    Error,
    { source: FindingSource; code: string; payload: FindingWritePayload }
  >({
    mutationFn: ({ source, code, payload }) => updateFinding(source, code, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...KEY, "findings"] }),
  });
}

export function useDeleteFinding() {
  const qc = useQueryClient();
  return useMutation<void, Error, { source: FindingSource; code: string }>({
    mutationFn: ({ source, code }) => deleteFinding(source, code),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...KEY, "findings"] }),
  });
}

export function useBetaTrees() {
  return useQuery({
    queryKey: [...KEY, "list"] as const,
    queryFn: listBetaTrees,
    staleTime: 30_000,
  });
}

export function useBetaTree(code: string | undefined) {
  return useQuery({
    queryKey: [...KEY, "detail", code] as const,
    queryFn: () => getBetaTree(code!),
    enabled: Boolean(code),
    staleTime: 10_000,
  });
}

export function useSaveBetaDraft() {
  const qc = useQueryClient();
  return useMutation<
    BetaTreeDetail,
    Error,
    { code: string; tree_yaml: string; notes?: string | null }
  >({
    mutationFn: ({ code, tree_yaml, notes }) => saveBetaTreeDraft(code, tree_yaml, notes),
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: [...KEY, "detail", vars.code] });
      void qc.invalidateQueries({ queryKey: [...KEY, "list"] });
    },
  });
}

/**
 * The publish checks.
 *
 * Deliberately a mutation, not a query: the author asks for it, and an answer
 * that arrived on its own would go stale the moment they moved a node. The
 * page also runs the same rules locally on every keystroke; this is the
 * authoritative pass before a publish.
 */
export function useCompileBetaTree() {
  return useMutation<BetaCompileResponse, Error, { code: string; tree_yaml: string }>({
    mutationFn: ({ code, tree_yaml }) => compileBetaTreeRemote(code, tree_yaml),
  });
}

export function usePublishBetaTree() {
  const qc = useQueryClient();
  return useMutation<BetaTreeDetail, Error, { code: string; version: number }>({
    mutationFn: ({ code, version }) => publishBetaTreeVersion(code, version),
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: [...KEY, "detail", vars.code] });
      void qc.invalidateQueries({ queryKey: [...KEY, "list"] });
    },
  });
}

export function useBetaCandidateBlocks(code: string | undefined) {
  return useQuery({
    queryKey: [...KEY, "candidate_blocks", code] as const,
    queryFn: () => getBetaCandidateBlocks(code!),
    enabled: Boolean(code),
    staleTime: 60_000,
  });
}

export function useBetaDryRun() {
  return useMutation<BetaDryRunResponse, Error, { code: string; payload: BetaDryRunPayload }>({
    mutationFn: ({ code, payload }) => betaDryRun(code, payload),
  });
}
