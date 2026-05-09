import { useQuery } from "@tanstack/react-query";

import { listCrossTenantHealth } from "@/api/platformHealthRollup";

export function useCrossTenantHealth() {
  return useQuery({
    queryKey: ["platform_cross_tenant_health"] as const,
    queryFn: listCrossTenantHealth,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}
