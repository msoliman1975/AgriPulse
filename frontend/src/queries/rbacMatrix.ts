import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { getRbacMatrix, type RbacMatrix } from "@/api/rbacMatrix";

const ROOT = "rbacMatrix";

/**
 * The role -> capability matrix.
 *
 * Compiled from YAML at boot, so it only changes on deploy — a long staleTime
 * costs nothing. Phase 2 makes it mutable at runtime and will invalidate
 * `[ROOT]` from the write path.
 */
export function useRbacMatrix(): UseQueryResult<RbacMatrix> {
  return useQuery({
    queryKey: [ROOT, "matrix"],
    queryFn: getRbacMatrix,
    staleTime: 5 * 60_000,
  });
}
