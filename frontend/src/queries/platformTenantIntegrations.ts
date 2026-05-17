import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearTenantIntegration,
  readTenantIntegration,
  writeTenantIntegration,
  type Category,
} from "@/api/platformTenantIntegrations";

export function usePlatformTenantIntegration(tenantId: string, category: Category) {
  return useQuery({
    queryKey: ["platform_tenant_integration", tenantId, category] as const,
    queryFn: () => readTenantIntegration(tenantId, category),
    staleTime: 30_000,
  });
}

export function usePutPlatformTenantIntegration(tenantId: string, category: Category) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      writeTenantIntegration(tenantId, category, key, value),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["platform_tenant_integration", tenantId, category],
      });
    },
  });
}

export function useClearPlatformTenantIntegration(tenantId: string, category: Category) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => clearTenantIntegration(tenantId, category, key),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["platform_tenant_integration", tenantId, category],
      });
    },
  });
}
