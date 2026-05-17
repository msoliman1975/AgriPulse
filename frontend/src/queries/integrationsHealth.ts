import { useQuery } from "@tanstack/react-query";

import {
  listBlockAttempts,
  listBlockHealth,
  listFarmHealth,
  listPlatformProviders,
  listProviderErrorHistogram,
  listProviders,
  listQueue,
  listRecentAttempts,
  listRecentProbes,
  type AttemptKind,
  type AttemptStatus,
  type QueueState,
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

export function useBlockIntegrationHealth(farmId: string | null, basePath: string = "/v1") {
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

export function useRecentAttempts(filters: RecentAttemptsFilters = {}, basePath: string = "/v1") {
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

export function useIntegrationQueue(
  kind: AttemptKind | undefined,
  state: QueueState | undefined,
  basePath: string = "/v1",
) {
  return useQuery({
    queryKey: ["integrations", "health", "queue", basePath, kind ?? "all", state ?? "all"] as const,
    queryFn: () => listQueue({ kind, state }, basePath),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}

export function useProvidersHealth(platformScope: boolean, basePath: string = "/v1") {
  return useQuery({
    queryKey: [
      "integrations",
      "health",
      "providers",
      platformScope ? "platform" : "tenant",
      basePath,
    ] as const,
    queryFn: () => (platformScope ? listPlatformProviders() : listProviders(basePath)),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}

export function useProviderErrorHistogram(
  provider_kind: AttemptKind | null,
  provider_code: string | null,
  hours: number = 24,
) {
  return useQuery({
    queryKey: [
      "integrations",
      "health",
      "providers",
      "error-histogram",
      provider_kind,
      provider_code,
      hours,
    ] as const,
    queryFn: () => listProviderErrorHistogram(provider_kind!, provider_code!, hours),
    enabled: Boolean(provider_kind && provider_code),
    staleTime: REFETCH_MS / 2,
  });
}

export function useProviderProbes(provider_kind: AttemptKind | null, provider_code: string | null) {
  return useQuery({
    queryKey: [
      "integrations",
      "health",
      "providers",
      "probes",
      provider_kind,
      provider_code,
    ] as const,
    queryFn: () => listRecentProbes(provider_kind!, provider_code!, 100),
    enabled: Boolean(provider_kind && provider_code),
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
