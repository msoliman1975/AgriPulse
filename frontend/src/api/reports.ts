// Reports API — mirrors backend/app/modules/reports/schemas.py. Read-only
// per-farm report payloads; Decimals serialise as strings (Pydantic).

import { apiClient } from "./client";

export interface ReportPeriod {
  since: string;
  until: string;
}

// ---- PR-1: Seasonal Crop Health ------------------------------------------

export type CropHealthStatus = "normal" | "watch" | "stressed" | "unknown";

export interface CropHealthBlockRow {
  block_id: string;
  block_name: string;
  crop_name_en: string | null;
  crop_name_ar: string | null;
  status: CropHealthStatus;
  last_value: string | null;
  last_observed_at: string | null;
  baseline_z: string | null;
  trend_pct: string | null;
  min_value: string | null;
  max_value: string | null;
  p10: string | null;
  p50: string | null;
  p90: string | null;
  avg_valid_pixel_pct: string | null;
  avg_cloud_pct: string | null;
  scene_count: number;
}

export interface CropHealthSummary {
  block_count: number;
  with_data_count: number;
  normal: number;
  watch: number;
  stressed: number;
  unknown: number;
  avg_last_value: string | null;
}

export interface CropHealthReportResponse {
  farm_id: string;
  farm_name: string;
  index_code: string;
  period: ReportPeriod;
  blocks: CropHealthBlockRow[];
  summary: CropHealthSummary;
}

export interface CropHealthParams {
  index_code?: string;
  since?: string;
  until?: string;
}

export async function getCropHealthReport(
  farmId: string,
  params: CropHealthParams = {},
): Promise<CropHealthReportResponse> {
  const { data } = await apiClient.get<CropHealthReportResponse>(
    `/v1/farms/${farmId}/reports/crop-health`,
    { params },
  );
  return data;
}

// ---- PR-2: Field Variability / Zone Anomaly ------------------------------

export type ZoneAnomalyStatus =
  | "anomalies"
  | "clear"
  | "insufficient"
  | "no_data"
  | "no_grid";

export interface ZoneAnomalyBlockRow {
  block_id: string;
  block_name: string;
  status: ZoneAnomalyStatus;
  scene_time: string | null;
  cell_count: number;
  flagged_count: number;
  flagged_area_ha: string | null;
  worst_z: string | null;
  block_mean: string | null;
  block_std: string | null;
  threshold_k: string | null;
}

export interface ZoneAnomalySummary {
  block_count: number;
  blocks_with_grid: number;
  blocks_with_anomalies: number;
  total_flagged_cells: number;
  total_flagged_area_ha: string | null;
}

export interface ZoneAnomalyReportResponse {
  farm_id: string;
  farm_name: string;
  index_code: string;
  period: ReportPeriod;
  blocks: ZoneAnomalyBlockRow[];
  summary: ZoneAnomalySummary;
}

export async function getZoneAnomalyReport(
  farmId: string,
  params: CropHealthParams = {},
): Promise<ZoneAnomalyReportResponse> {
  const { data } = await apiClient.get<ZoneAnomalyReportResponse>(
    `/v1/farms/${farmId}/reports/zone-anomaly`,
    { params },
  );
  return data;
}

// ---- PR-3: Irrigation & Water Balance ------------------------------------

/** Date-range-only params shared by the non-index reports. */
export interface RangeParams {
  since?: string;
  until?: string;
}

export interface WaterBalanceWeather {
  days_with_data: number;
  et0_mm_total: string | null;
  precip_mm_total: string | null;
  et0_mm_avg_daily: string | null;
}

export interface WaterBalanceBlockRow {
  block_id: string;
  block_name: string;
  scheduled_count: number;
  applied_count: number;
  skipped_count: number;
  pending_count: number;
  recommended_mm_total: string | null;
  applied_mm_total: string | null;
  adherence_pct: string | null;
  last_scheduled_for: string | null;
}

export interface WaterBalanceSummary {
  block_count: number;
  blocks_with_schedules: number;
  recommended_mm_total: string | null;
  applied_mm_total: string | null;
  applied_count: number;
  skipped_count: number;
  pending_count: number;
}

export interface WaterBalanceReportResponse {
  farm_id: string;
  farm_name: string;
  period: ReportPeriod;
  weather: WaterBalanceWeather;
  blocks: WaterBalanceBlockRow[];
  summary: WaterBalanceSummary;
}

export async function getWaterBalanceReport(
  farmId: string,
  params: RangeParams = {},
): Promise<WaterBalanceReportResponse> {
  const { data } = await apiClient.get<WaterBalanceReportResponse>(
    `/v1/farms/${farmId}/reports/water-balance`,
    { params },
  );
  return data;
}

// ---- PR-4: Weather & GDD Summary -----------------------------------------

export interface WeatherSummaryStats {
  days_with_data: number;
  temp_min_c: string | null;
  temp_max_c: string | null;
  temp_mean_c: string | null;
  precip_mm_total: string | null;
  rain_days: number;
  et0_mm_total: string | null;
  et0_mm_avg_daily: string | null;
  gdd_base10_total: string | null;
  gdd_cumulative_season: string | null;
}

export interface WeatherDailyPoint {
  date: string;
  temp_min_c: string | null;
  temp_max_c: string | null;
  temp_mean_c: string | null;
  precip_mm: string | null;
  et0_mm: string | null;
  gdd_base10: string | null;
  gdd_cumulative_season: string | null;
}

export interface WeatherCropContext {
  crop_id: string;
  name_en: string;
  name_ar: string | null;
  block_count: number;
  gdd_base_temp_c: string | null;
  default_growing_season_days: number | null;
}

export interface WeatherSummaryReportResponse {
  farm_id: string;
  farm_name: string;
  period: ReportPeriod;
  stats: WeatherSummaryStats;
  daily: WeatherDailyPoint[];
  crops: WeatherCropContext[];
}

export async function getWeatherSummaryReport(
  farmId: string,
  params: RangeParams = {},
): Promise<WeatherSummaryReportResponse> {
  const { data } = await apiClient.get<WeatherSummaryReportResponse>(
    `/v1/farms/${farmId}/reports/weather-summary`,
    { params },
  );
  return data;
}

// ---- PR-5: Farm Operations & Agronomy Log --------------------------------

export type OpsLogKind = "activity" | "alert" | "recommendation";

export interface OpsLogEntry {
  time: string;
  kind: OpsLogKind;
  block_name: string | null;
  title: string;
  status: string | null;
  severity: string | null;
  detail: string | null;
}

export interface OpsLogSummary {
  activities_total: number;
  activities_completed: number;
  activities_skipped: number;
  alerts_opened: number;
  alerts_resolved: number;
  recommendations_total: number;
  recommendations_applied: number;
  recommendations_dismissed: number;
}

export interface OperationsLogReportResponse {
  farm_id: string;
  farm_name: string;
  period: ReportPeriod;
  entries: OpsLogEntry[];
  summary: OpsLogSummary;
}

export async function getOperationsLogReport(
  farmId: string,
  params: RangeParams = {},
): Promise<OperationsLogReportResponse> {
  const { data } = await apiClient.get<OperationsLogReportResponse>(
    `/v1/farms/${farmId}/reports/operations-log`,
    { params },
  );
  return data;
}
