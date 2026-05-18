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
