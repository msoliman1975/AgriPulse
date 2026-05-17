import { apiClient } from "./client";

export interface PlatformTenantHealthRow {
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  farms_count: number;
  weather_active_subs: number;
  weather_last_sync_at: string | null;
  weather_failed_24h: number;
  imagery_active_subs: number;
  imagery_last_sync_at: string | null;
  imagery_failed_24h: number;
}

export async function listCrossTenantHealth(): Promise<PlatformTenantHealthRow[]> {
  const { data } = await apiClient.get<PlatformTenantHealthRow[]>("/v1/admin/integrations/health");
  return data;
}
