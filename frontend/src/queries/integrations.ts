import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { integrationsApi } from "@/api/integrations";

const STALE = 30_000;

/** Email + webhook categories were dropped with public migration 0048. */
export type IntegrationCategory = "weather" | "imagery" | "detection";

export function useTenantIntegration(category: IntegrationCategory) {
  return useQuery({
    queryKey: ["integrations", category, "tenant"] as const,
    queryFn: () => integrationsApi[category].getTenant(),
    staleTime: STALE,
  });
}

export function usePutTenantIntegration(category: IntegrationCategory) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      integrationsApi[category].putTenant(key, value),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["integrations", category] });
    },
  });
}

export function useDeleteTenantIntegration(category: "weather" | "imagery") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => integrationsApi[category].deleteTenant(key),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["integrations", category] });
    },
  });
}

export function useFarmWeather(farmId: string | null) {
  return useQuery({
    queryKey: ["integrations", "weather", "farm", farmId] as const,
    queryFn: () => integrationsApi.weather.getFarm(farmId!),
    enabled: Boolean(farmId),
  });
}

export function usePutFarmWeather() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      farmId,
      payload,
    }: {
      farmId: string;
      payload: { provider_code: string | null; cadence_hours: number | null };
    }) => integrationsApi.weather.putFarm(farmId, payload),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({
        queryKey: ["integrations", "weather", "farm", vars.farmId],
      });
    },
  });
}

export function useFarmImagery(farmId: string | null) {
  return useQuery({
    queryKey: ["integrations", "imagery", "farm", farmId] as const,
    queryFn: () => integrationsApi.imagery.getFarm(farmId!),
    enabled: Boolean(farmId),
  });
}

export function usePutFarmImagery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      farmId,
      payload,
    }: {
      farmId: string;
      payload: { cloud_cover_threshold_pct: number | null };
    }) => integrationsApi.imagery.putFarm(farmId, payload),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({
        queryKey: ["integrations", "imagery", "farm", vars.farmId],
      });
    },
  });
}

export function useApplyImageryToBlocks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ farmId, mode }: { farmId: string; mode: "inherit" | "lock" }) =>
      integrationsApi.imagery.applyToBlocks(farmId, mode),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["integrations", "imagery"] });
    },
  });
}
