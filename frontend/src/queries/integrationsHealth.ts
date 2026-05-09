import { useQuery } from "@tanstack/react-query";

import { listBlockHealth, listFarmHealth } from "@/api/integrationsHealth";

const REFETCH_MS = 30_000;

export function useFarmIntegrationHealth() {
  return useQuery({
    queryKey: ["integrations", "health", "farms"] as const,
    queryFn: listFarmHealth,
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}

export function useBlockIntegrationHealth(farmId: string | null) {
  return useQuery({
    queryKey: ["integrations", "health", "blocks", farmId] as const,
    queryFn: () => listBlockHealth(farmId!),
    enabled: Boolean(farmId),
    refetchInterval: REFETCH_MS,
    staleTime: REFETCH_MS / 2,
  });
}
