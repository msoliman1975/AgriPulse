// Mirrors backend/app/modules/integrations_health/schemas.py.

import { apiClient } from "./client";

export interface FarmIntegrationHealth {
  farm_id: string;
  farm_name: string;
  weather_active_subs: number;
  weather_last_sync_at: string | null;
  weather_last_failed_at: string | null;
  imagery_active_subs: number;
  imagery_last_sync_at: string | null;
  imagery_failed_24h: number;
}

export interface BlockIntegrationHealth {
  block_id: string;
  farm_id: string;
  block_name: string;
  weather_active_subs: number;
  weather_last_sync_at: string | null;
  weather_last_failed_at: string | null;
  imagery_active_subs: number;
  imagery_last_sync_at: string | null;
  imagery_failed_24h: number;
}

export async function listFarmHealth(): Promise<FarmIntegrationHealth[]> {
  const { data } = await apiClient.get<FarmIntegrationHealth[]>(
    "/v1/integrations/health/farms",
  );
  return data;
}

export async function listBlockHealth(
  farmId: string,
): Promise<BlockIntegrationHealth[]> {
  const { data } = await apiClient.get<BlockIntegrationHealth[]>(
    `/v1/integrations/health/farms/${farmId}/blocks`,
  );
  return data;
}
