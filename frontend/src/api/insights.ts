// Insights API — mirrors backend/app/modules/insights/schemas.py.
// Two read endpoints powering the "Farm health overview" page.

import { apiClient } from "./client";

export type Health = "healthy" | "watch" | "critical" | "unknown";
export type TimeseriesGranularity = "daily" | "weekly";

export interface FarmIndexTimeseriesPoint {
  time: string; // ISO timestamp
  block_id: string;
  block_name: string;
  // Pydantic Decimal serialises as string.
  value: string;
}

export interface FarmIndexTimeseriesResponse {
  farm_id: string;
  index_code: string;
  granularity: TimeseriesGranularity;
  points: FarmIndexTimeseriesPoint[];
}

export interface BlockHealthRow {
  block_id: string;
  block_name: string;
  current_health: Health;
  current_value: string | null;
  trend_30d_pct: string | null;
  alerts_open: number;
  last_observation_at: string | null;
}

export interface FarmHealthSummaryResponse {
  farm_id: string;
  index_code: string;
  blocks: BlockHealthRow[];
}

export interface FarmIndexTimeseriesParams {
  index_code?: string; // default "ndvi"
  granularity?: TimeseriesGranularity; // default "daily"
  since?: string; // ISO timestamp
  until?: string;
}

export async function getFarmIndexTimeseries(
  farmId: string,
  params: FarmIndexTimeseriesParams = {},
): Promise<FarmIndexTimeseriesResponse> {
  const { data } = await apiClient.get<FarmIndexTimeseriesResponse>(
    `/v1/farms/${farmId}/index-timeseries`,
    { params },
  );
  return data;
}

export async function getFarmHealthSummary(farmId: string): Promise<FarmHealthSummaryResponse> {
  const { data } = await apiClient.get<FarmHealthSummaryResponse>(
    `/v1/farms/${farmId}/health-summary`,
  );
  return data;
}

// ---- B.3: annotations + season + alerts sparkline ------------------------

export type AnnotationKind = "alert_opened";
export type AnnotationSeverity = "critical" | "warning" | "info" | null;

export interface TimeseriesAnnotation {
  time: string;
  kind: AnnotationKind;
  label: string;
  severity: AnnotationSeverity;
  block_id: string | null;
}

export interface FarmAnnotationsResponse {
  farm_id: string;
  annotations: TimeseriesAnnotation[];
}

export async function getFarmAnnotations(
  farmId: string,
  params: { since?: string; until?: string } = {},
): Promise<FarmAnnotationsResponse> {
  const { data } = await apiClient.get<FarmAnnotationsResponse>(
    `/v1/farms/${farmId}/insights-annotations`,
    { params },
  );
  return data;
}

export interface SeasonContextCrop {
  crop_id: string;
  name_en: string;
  name_ar: string | null;
  block_count: number;
}

export interface FarmSeasonContextResponse {
  farm_id: string;
  crops: SeasonContextCrop[];
  active_block_count: number;
}

export async function getFarmSeasonContext(farmId: string): Promise<FarmSeasonContextResponse> {
  const { data } = await apiClient.get<FarmSeasonContextResponse>(
    `/v1/farms/${farmId}/season-context`,
  );
  return data;
}

export interface AlertTrendPoint {
  date: string;
  open_count: number;
}

export interface FarmAlertTrendResponse {
  farm_id: string;
  days: number;
  points: AlertTrendPoint[];
}

export async function getFarmAlertTrend(farmId: string, days = 7): Promise<FarmAlertTrendResponse> {
  const { data } = await apiClient.get<FarmAlertTrendResponse>(`/v1/farms/${farmId}/alert-trend`, {
    params: { days },
  });
  return data;
}
