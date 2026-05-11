import { useQuery } from "@tanstack/react-query";

import {
  listBlockAttempts,
  listBlockHealth,
  listFarmHealth,
  listRecentAttempts,
  type AttemptKind,
  type AttemptStatus,
} from "@/api/integrationsHealth";

const REFETCH_MS = 30_000;

/**
 * basePath lets the platform tenant drill-in (PR-IH7) reuse these hooks
 * by pointing them at `/v1/admin/integrations/health/tenants/:id` while
 * the tenant portal stays on `/v1`.
 */

export function useFarmIntegrationHealth(basePath: string = "/v1") {
  return useQuery({
    queryKey: ["integrations", "health", "farms", basePath] as const,
    queryFn: () => listFarmHealth(basePath),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}

export function useBlockIntegrationHealth(
  farmId: string | null,
  basePath: string = "/v1",
) {
  return useQuery({
    queryKey: ["integrations", "health", "blocks", basePath, farmId] as const,
    queryFn: () => listBlockHealth(farmId!, basePath),
    enabled: Boolean(farmId),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}

export interface RecentAttemptsFilters {
  kind?: AttemptKind;
  status?: AttemptStatus;
  farm_id?: string;
}

export function useRecentAttempts(
  filters: RecentAttemptsFilters = {},
  basePath: string = "/v1",
) {
  return useQuery({
    queryKey: [
      "integrations",
      "health",
      "recent",
      basePath,
      filters.kind ?? "all",
      filters.status ?? "all",
      filters.farm_id ?? "all",
    ] as const,
    queryFn: () => listRecentAttempts({ ...filters, limit: 200 }, basePath),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}

export function useBlockAttempts(
  blockId: string | null,
  kind?: AttemptKind,
  basePath: string = "/v1",
) {
  return useQuery({
    queryKey: [
      "integrations",
      "health",
      "block-attempts",
      basePath,
      blockId,
      kind ?? "all",
    ] as const,
    queryFn: () => listBlockAttempts(blockId!, { kind, limit: 100 }, basePath),
    enabled: Boolean(blockId),
    staleTime: REFETCH_MS / 2,
  });
}
