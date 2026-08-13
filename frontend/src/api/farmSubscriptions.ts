import { apiClient } from "./client";

// Mirrors the FarmSubscription* schemas in backend/app/modules/{imagery,weather}
// — keep in lock-step. Mirrored constants drift silently in this codebase and
// the only defence is tests that read both sides.

/**
 * A farm's subscription to an imagery product.
 *
 * The farm is the unit imagery is fetched for, so it is the unit configured
 * here. The per-block rows still exist underneath until the cutover, which is
 * what lets a farm move over one at a time.
 */
export interface FarmImagerySubscription {
  id: string;
  farm_id: string;
  product_id: string;
  cadence_hours: number | null;
  cloud_cover_max_pct: number | null;
  is_active: boolean;
  /**
   * Fetch the farm's own boundary rather than stitching block rasters.
   *
   * Off by default, and worth leaving off until someone wants it: it is a
   * second, larger provider request per pass. What it buys is pixels over
   * ground no block was ever drawn around — a quarter of the reference farm.
   */
  fetch_farm_aoi: boolean;
  last_successful_ingest_at: string | null;
  last_attempted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface FarmWeatherSubscription {
  id: string;
  farm_id: string;
  provider_code: string;
  cadence_hours: number | null;
  is_active: boolean;
  last_successful_ingest_at: string | null;
  last_attempted_at: string | null;
  created_at: string;
  updated_at: string;
}

export async function listFarmImagerySubscriptions(
  farmId: string,
  includeInactive = false,
): Promise<FarmImagerySubscription[]> {
  const { data } = await apiClient.get<FarmImagerySubscription[]>(
    `/v1/farms/${farmId}/imagery/subscriptions`,
    { params: { include_inactive: includeInactive || undefined } },
  );
  return data;
}

export async function subscribeFarmImagery(
  farmId: string,
  body: {
    product_id: string;
    cadence_hours?: number | null;
    cloud_cover_max_pct?: number | null;
    fetch_farm_aoi?: boolean;
  },
): Promise<FarmImagerySubscription> {
  const { data } = await apiClient.post<FarmImagerySubscription>(
    `/v1/farms/${farmId}/imagery/subscriptions`,
    body,
  );
  return data;
}

export async function updateFarmImagerySubscription(
  farmId: string,
  subscriptionId: string,
  body: {
    cadence_hours?: number | null;
    cloud_cover_max_pct?: number | null;
    fetch_farm_aoi?: boolean;
    is_active?: boolean;
  },
): Promise<FarmImagerySubscription> {
  const { data } = await apiClient.patch<FarmImagerySubscription>(
    `/v1/farms/${farmId}/imagery/subscriptions/${subscriptionId}`,
    body,
  );
  return data;
}

export async function listFarmWeatherSubscriptions(
  farmId: string,
  includeInactive = false,
): Promise<FarmWeatherSubscription[]> {
  const { data } = await apiClient.get<FarmWeatherSubscription[]>(
    `/v1/farms/${farmId}/weather/subscriptions`,
    { params: { include_inactive: includeInactive || undefined } },
  );
  return data;
}

export async function subscribeFarmWeather(
  farmId: string,
  body: { provider_code: string; cadence_hours?: number | null },
): Promise<FarmWeatherSubscription> {
  const { data } = await apiClient.post<FarmWeatherSubscription>(
    `/v1/farms/${farmId}/weather/subscriptions`,
    body,
  );
  return data;
}

export async function updateFarmWeatherSubscription(
  farmId: string,
  subscriptionId: string,
  body: { cadence_hours?: number | null; is_active?: boolean },
): Promise<FarmWeatherSubscription> {
  const { data } = await apiClient.patch<FarmWeatherSubscription>(
    `/v1/farms/${farmId}/weather/subscriptions/${subscriptionId}`,
    body,
  );
  return data;
}
