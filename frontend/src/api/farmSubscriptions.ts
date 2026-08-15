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
   * Which path this farm is fetched on: its own boundary, or block rasters
   * stitched together.
   *
   * Not a user setting — it is the cutover switch, driven platform-side. The
   * UI reports it and never writes it: turning it on for a farm the provider
   * cannot return in one request stops that farm's imagery entirely, because
   * this same flag excludes its blocks from the block sweep.
   */
  fetch_farm_aoi: boolean;
  /** False when the farm is too big for one provider request. Measured per read. */
  farm_aoi_fetchable: boolean;
  /** The measurement behind `farm_aoi_fetchable`; null when it could not be taken. */
  farm_aoi_width_px: number | null;
  farm_aoi_height_px: number | null;
  /** Provider limit per side, for the message. 2500 for Sentinel Hub's Process API. */
  farm_aoi_max_px: number;
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
