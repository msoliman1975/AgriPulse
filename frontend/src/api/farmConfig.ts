// Mirrors backend/app/modules/farms/config_router.py — keep in lock-step.
// Gated by the FARM_CONFIG_TEMPLATE_ENABLED flag on the backend; the
// UI surfaces these routes only behind the Defaults tab.

import { apiClient } from "./client";

export interface ImageryTemplateRow {
  product_id: string;
  cadence_hours: number;
  cloud_cover_max_pct: number | null;
  is_active: boolean;
}

export interface WeatherTemplateRow {
  provider_code: string;
  cadence_hours: number;
  is_active: boolean;
}

export interface SubscriptionsTemplate {
  imagery: ImageryTemplateRow[];
  weather: WeatherTemplateRow[];
}

export interface BlockDiff {
  block_id: string;
  will_add: Record<string, unknown>[];
  will_update: Record<string, unknown>[];
  will_deactivate: Record<string, unknown>[];
  matches: boolean;
}

export interface ApplyPreview {
  imagery: BlockDiff[];
  weather: BlockDiff[];
  total_blocks: number;
  matched_blocks: number;
}

export interface ApplyCounts {
  blocks_touched: number;
  imagery_added: number;
  imagery_updated: number;
  imagery_deactivated: number;
  weather_added: number;
  weather_updated: number;
  weather_deactivated: number;
}

export async function getSubscriptionsTemplate(
  farmId: string,
): Promise<SubscriptionsTemplate> {
  const { data } = await apiClient.get<SubscriptionsTemplate>(
    `/v1/farms/${farmId}/config/subscriptions/template`,
  );
  return data;
}

export async function replaceSubscriptionsTemplate(
  farmId: string,
  body: SubscriptionsTemplate,
): Promise<SubscriptionsTemplate> {
  const { data } = await apiClient.put<SubscriptionsTemplate>(
    `/v1/farms/${farmId}/config/subscriptions/template`,
    body,
  );
  return data;
}

export async function previewApplySubscriptions(
  farmId: string,
  blockIds: string[] | null = null,
): Promise<ApplyPreview> {
  const { data } = await apiClient.post<ApplyPreview>(
    `/v1/farms/${farmId}/config/subscriptions/apply-preview`,
    { block_ids: blockIds },
  );
  return data;
}

export async function applySubscriptions(
  farmId: string,
  blockIds: string[],
): Promise<ApplyCounts> {
  const { data } = await apiClient.post<ApplyCounts>(
    `/v1/farms/${farmId}/config/subscriptions/apply`,
    { block_ids: blockIds },
  );
  return data;
}
