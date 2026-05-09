import { apiClient } from "./client";

export type SettingSource = "platform" | "tenant" | "farm" | "resource";

export interface ResolvedSetting {
  key: string;
  value: unknown;
  source: SettingSource;
  overridden_at: string | null;
}

export interface SettingsBag {
  settings: ResolvedSetting[];
}

// ---- Tenant tier ---------------------------------------------------------

async function getTenant(category: string): Promise<SettingsBag> {
  const { data } = await apiClient.get<SettingsBag>(
    `/v1/integrations/${category}/tenant`,
  );
  return data;
}

async function putTenant(
  category: string,
  key: string,
  value: unknown,
): Promise<ResolvedSetting> {
  const { data } = await apiClient.put<ResolvedSetting>(
    `/v1/integrations/${category}/tenant`,
    { value },
    { params: { key } },
  );
  return data;
}

async function deleteTenant(
  category: string,
  key: string,
): Promise<ResolvedSetting> {
  const { data } = await apiClient.delete<ResolvedSetting>(
    `/v1/integrations/${category}/tenant`,
    { params: { key } },
  );
  return data;
}

export const integrationsApi = {
  weather: {
    getTenant: () => getTenant("weather"),
    putTenant: (key: string, value: unknown) => putTenant("weather", key, value),
    deleteTenant: (key: string) => deleteTenant("weather", key),
    getFarm: async (farmId: string): Promise<SettingsBag> => {
      const { data } = await apiClient.get<SettingsBag>(
        `/v1/integrations/weather/farms/${farmId}`,
      );
      return data;
    },
    putFarm: async (
      farmId: string,
      payload: { provider_code: string | null; cadence_hours: number | null },
    ): Promise<SettingsBag> => {
      const { data } = await apiClient.put<SettingsBag>(
        `/v1/integrations/weather/farms/${farmId}`,
        payload,
      );
      return data;
    },
  },
  imagery: {
    getTenant: () => getTenant("imagery"),
    putTenant: (key: string, value: unknown) => putTenant("imagery", key, value),
    deleteTenant: (key: string) => deleteTenant("imagery", key),
    getFarm: async (farmId: string): Promise<SettingsBag> => {
      const { data } = await apiClient.get<SettingsBag>(
        `/v1/integrations/imagery/farms/${farmId}`,
      );
      return data;
    },
    putFarm: async (
      farmId: string,
      payload: {
        product_code: string | null;
        cloud_cover_threshold_pct: number | null;
      },
    ): Promise<SettingsBag> => {
      const { data } = await apiClient.put<SettingsBag>(
        `/v1/integrations/imagery/farms/${farmId}`,
        payload,
      );
      return data;
    },
    putBlock: async (
      blockId: string,
      payload: { cloud_cover_max_pct: number | null },
    ): Promise<{ block_id: string; cloud_cover_max_pct: number | null }> => {
      const { data } = await apiClient.put(
        `/v1/integrations/imagery/blocks/${blockId}`,
        payload,
      );
      return data as { block_id: string; cloud_cover_max_pct: number | null };
    },
    applyToBlocks: async (
      farmId: string,
      mode: "inherit" | "lock",
    ): Promise<{ mode: string; blocks_affected: number }> => {
      const { data } = await apiClient.post(
        `/v1/integrations/imagery/farms/${farmId}:apply-to-blocks`,
        { mode },
      );
      return data as { mode: string; blocks_affected: number };
    },
  },
  email: {
    getTenant: () => getTenant("email"),
    putTenant: (key: string, value: unknown) => putTenant("email", key, value),
  },
  webhook: {
    getTenant: () => getTenant("webhook"),
    putTenant: (key: string, value: unknown) => putTenant("webhook", key, value),
  },
};
