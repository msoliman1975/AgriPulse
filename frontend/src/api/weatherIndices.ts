import { apiClient } from "./client";

// Mirrors backend/app/modules/weather/schemas.py (weather-index surface) +
// the public weather_indices_catalog. Numeric fields arrive as JSON strings
// (Decimal -> string convention) or null — keep in lock-step.

// --- Catalog (platform-curated, tenant-readable) --------------------------

export interface WeatherIndexCatalogItem {
  code: string;
  name_en: string;
  name_ar: string | null;
  unit: string;
  description_en: string | null;
  description_ar: string | null;
  value_min: string | null;
  value_max: string | null;
  source_kind: string;
  default_visible: boolean;
  sort_order: number;
  relation_indices_en: string | null;
  relation_indices_ar: string | null;
  relation_disease_en: string | null;
  relation_disease_ar: string | null;
  relation_insect_en: string | null;
  relation_insect_ar: string | null;
}

export async function getWeatherIndexCatalog(): Promise<WeatherIndexCatalogItem[]> {
  const { data } = await apiClient.get<WeatherIndexCatalogItem[]>("/v1/weather/indices/catalog");
  return data;
}

// --- Per-farm summary (latest value + anomaly + 7-day trend) --------------

export interface WeatherIndexSummaryEntry {
  index_code: string;
  latest_date: string;
  value: string | null;
  zscore: string | null;
  trend_7d_delta: string | null;
}

export interface WeatherIndexSummaryResponse {
  farm_id: string;
  as_of: string;
  indices: WeatherIndexSummaryEntry[];
}

export async function getWeatherIndexSummary(farmId: string): Promise<WeatherIndexSummaryResponse> {
  const { data } = await apiClient.get<WeatherIndexSummaryResponse>(
    `/v1/farms/${farmId}/weather-indices/summary`,
  );
  return data;
}

// --- Per-farm daily timeseries (+ climatology band) -----------------------

export interface WeatherIndexPoint {
  date: string;
  value: string | null;
  value_min: string | null;
  value_max: string | null;
  value_aux: Record<string, string>;
  zscore: string | null;
  baseline_mean: string | null;
  baseline_std: string | null;
}

export interface WeatherIndexTimeseriesResponse {
  farm_id: string;
  index_code: string;
  points: WeatherIndexPoint[];
}

export interface GetWeatherIndexTimeseriesParams {
  /** Inclusive lower bound, YYYY-MM-DD. */
  from?: string;
  /** Exclusive upper bound, YYYY-MM-DD. */
  to?: string;
}

export async function getWeatherIndexTimeseries(
  farmId: string,
  indexCode: string,
  params: GetWeatherIndexTimeseriesParams = {},
): Promise<WeatherIndexTimeseriesResponse> {
  const { data } = await apiClient.get<WeatherIndexTimeseriesResponse>(
    `/v1/farms/${farmId}/weather-indices/${indexCode}/timeseries`,
    { params: { from: params.from ?? undefined, to: params.to ?? undefined } },
  );
  return data;
}
