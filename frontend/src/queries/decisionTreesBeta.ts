import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  appendBetaDraft,
  betaCellWalk,
  betaDryRun,
  createBetaTree,
  createFinding,
  deactivateFinding,
  discardBetaDraft,
  getBetaTree,
  listBetaTrees,
  listDryRunBlocks,
  listFindings,
  publishBetaVersion,
  updateFinding,
  type BetaCandidateBlock,
  type BetaCellWalkResponse,
  type BetaDryRunResponse,
  type BetaTreeCreatePayload,
  type BetaTreeDetail,
  type BetaTreeVersion,
  type Finding,
  type FindingSource,
  type FindingWritePayload,
} from "@/api/decisionTreesBeta";
import type { BetaTreeDoc } from "@/modules/decisionTrees/beta/lib/betaTree";
import type { AuthoringScope } from "@/modules/decisionTrees/lib/authoringScope";

/**
 * Query hooks for the beta designer.
 *
 * Every one of them reads `@/api/decisionTreesBeta`, which is the only file
 * that knows a URL. There is no compile hook: the contract has no compile
 * route, and the checks come back as a 422 on the save or the publish that
 * asked for them. `beta/lib/betaCompile.ts` is what answers while the author
 * types, and it does not block anything.
 */

const KEY = ["decision_trees_beta"] as const;

export function useFindingCatalogue(scope: AuthoringScope) {
  return useQuery({
    queryKey: [...KEY, "findings", scope] as const,
    queryFn: () => listFindings(scope),
    staleTime: 60_000,
  });
}

function useInvalidateFindings() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: [...KEY, "findings"] });
}

export function useCreateFinding() {
  const invalidate = useInvalidateFindings();
  return useMutation<
    Finding,
    Error,
    { source: FindingSource; code: string; payload: FindingWritePayload }
  >({
    mutationFn: ({ source, code, payload }) => createFinding(source, code, payload),
    onSuccess: invalidate,
  });
}

export function useUpdateFinding() {
  const invalidate = useInvalidateFindings();
  return useMutation<
    Finding,
    Error,
    { source: FindingSource; code: string; payload: FindingWritePayload }
  >({
    mutationFn: ({ source, code, payload }) => updateFinding(source, code, payload),
    onSuccess: invalidate,
  });
}

/** Deactivate, not delete — the row stays and `is_active` is cleared. */
export function useDeactivateFinding() {
  const invalidate = useInvalidateFindings();
  return useMutation<void, Error, { source: FindingSource; code: string }>({
    mutationFn: ({ source, code }) => deactivateFinding(source, code),
    onSuccess: invalidate,
  });
}

export function useBetaTrees() {
  return useQuery({
    queryKey: [...KEY, "list"] as const,
    queryFn: listBetaTrees,
    staleTime: 30_000,
  });
}

export function useCreateBetaTree() {
  const qc = useQueryClient();
  return useMutation<BetaTreeDetail, Error, BetaTreeCreatePayload>({
    mutationFn: createBetaTree,
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...KEY, "list"] }),
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

/** Invalidate one tree and the list it appears in. Every write does both:
 *  a publish moves the published column on the list row too. */
function useInvalidateTree() {
  const qc = useQueryClient();
  return (code: string) => {
    void qc.invalidateQueries({ queryKey: [...KEY, "detail", code] });
    void qc.invalidateQueries({ queryKey: [...KEY, "list"] });
  };
}

/**
 * Append a draft version.
 *
 * `code` is carried only so the cache knows which tree to drop; the route
 * takes the id.
 */
export function useSaveBetaDraft() {
  const invalidate = useInvalidateTree();
  return useMutation<
    BetaTreeVersion,
    Error,
    { code: string; treeId: string; definition: BetaTreeDoc; notes?: string | null }
  >({
    mutationFn: ({ treeId, definition, notes }) => appendBetaDraft(treeId, definition, notes),
    onSuccess: (_, vars) => invalidate(vars.code),
  });
}

export function usePublishBetaTree() {
  const invalidate = useInvalidateTree();
  return useMutation<BetaTreeDetail, Error, { code: string; treeId: string; versionId: string }>({
    mutationFn: ({ treeId, versionId }) => publishBetaVersion(treeId, versionId),
    onSuccess: (_, vars) => invalidate(vars.code),
  });
}

/**
 * Discard the draft.
 *
 * Not the same as saving over it: appending an identical body writes no
 * version, so a draft that cannot compile cannot be replaced by editing it
 * back — it has to be removed, or it blocks every later author.
 */
export function useDiscardBetaDraft() {
  const invalidate = useInvalidateTree();
  return useMutation<void, Error, { code: string; treeId: string }>({
    mutationFn: ({ treeId }) => discardBetaDraft(treeId),
    onSuccess: (_, vars) => invalidate(vars.code),
  });
}

/**
 * Blocks the dry run can be pointed at.
 *
 * Disabled outside a tenant: farms and blocks are tenant-scoped, so a
 * platform caller would get a 403 and a picker with nothing in it.
 */
export function useDryRunBlocks(scope: AuthoringScope) {
  return useQuery<BetaCandidateBlock[]>({
    queryKey: [...KEY, "dry_run_blocks"] as const,
    queryFn: listDryRunBlocks,
    enabled: scope === "tenant",
    staleTime: 60_000,
  });
}

export function useBetaDryRun() {
  return useMutation<BetaDryRunResponse, Error, { treeId: string; blockId: string }>({
    mutationFn: ({ treeId, blockId }) => betaDryRun(treeId, blockId),
  });
}

/**
 * Why one cell got the result it got.
 *
 * A query, not a mutation, so re-opening the same row is free. The key holds
 * the version the walk ran against, so switching version or saving a draft
 * asks again rather than showing the previous body's path.
 *
 * `staleTime` is zero on purpose. This call re-walks, and a stale answer is
 * exactly the drift the panel exists to report.
 */
export function useBetaCellWalk(args: {
  treeId: string | null;
  blockId: string | null;
  cellId: string | null;
  versionId?: string | null;
}) {
  const { treeId, blockId, cellId, versionId = null } = args;
  return useQuery<BetaCellWalkResponse>({
    queryKey: [...KEY, "cell_walk", treeId, blockId, cellId, versionId] as const,
    queryFn: () =>
      betaCellWalk(treeId as string, blockId as string, cellId as string, { versionId }),
    enabled: treeId !== null && blockId !== null && cellId !== null,
    staleTime: 0,
    gcTime: 5 * 60_000,
  });
}
