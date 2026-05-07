import { apiClient } from "./client";

// Mirrors backend/app/modules/weather/schemas.py — keep in lock-step.

export interface Subscription {
  id: string;
  block_id: string;
  provider_code: string;
  cadence_hours: number | null;
  is_active: boolean;
  last_successful_ingest_at: string | null;
  last_attempted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubscriptionCreatePayload {
  provider_code: string;
  cadence_hours?: number | null;
}

export interface RefreshResponse {
  queued_farm_ids: string[];
  correlation_id: string | null;
}

export interface DailyForecast {
  date: string;
  high_c: string | null;
  low_c: string | null;
  precip_mm_total: string | null;
  precip_probability_max_pct: string | null;
}

export interface ForecastResponse {
  farm_id: string;
  provider_code: string;
  timezone: string;
  forecast_issued_at: string | null;
  days: DailyForecast[];
}

// --- Subscriptions --------------------------------------------------------

export async function listSubscriptions(
  blockId: string,
  options: { include_inactive?: boolean } = {},
): Promise<Subscription[]> {
  const { data } = await apiClient.get<Subscription[]>(
    `/v1/blocks/${blockId}/weather/subscriptions`,
    { params: { include_inactive: options.include_inactive ?? false } },
  );
  return data;
}

export async function createSubscription(
  blockId: string,
  payload: SubscriptionCreatePayload,
): Promise<Subscription> {
  const { data } = await apiClient.post<Subscription>(
    `/v1/blocks/${blockId}/weather/subscriptions`,
    payload,
  );
  return data;
}

export async function revokeSubscription(blockId: string, subscriptionId: string): Promise<void> {
  await apiClient.delete(`/v1/blocks/${blockId}/weather/subscriptions/${subscriptionId}`);
}

// --- Refresh + Forecast ---------------------------------------------------

export async function triggerRefresh(blockId: string): Promise<RefreshResponse> {
  const { data } = await apiClient.post<RefreshResponse>(`/v1/blocks/${blockId}/weather/refresh`);
  return data;
}

export async function getForecast(
  blockId: string,
  options: { horizon_days?: number; provider_code?: string } = {},
): Promise<ForecastResponse> {
  const { data } = await apiClient.get<ForecastResponse>(
    `/v1/blocks/${blockId}/weather/forecast`,
    {
      params: {
        horizon_days: options.horizon_days ?? 5,
        provider_code: options.provider_code ?? "open_meteo",
      },
    },
  );
  return data;
}
