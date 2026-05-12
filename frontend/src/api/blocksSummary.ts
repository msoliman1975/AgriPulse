// Mirrors backend/app/modules/farms/blocks_summary_router.py — keep in lock-step.

import { apiClient } from "./client";

export type Health = "healthy" | "watch" | "critical" | "unknown";
export type MapSeverity = "watch" | "critical";

export interface BlockSummary {
  id: string;
  health: Health;
  alert_count: number;
  alert_severity: MapSeverity | null;
  ndvi_current: number | null;
  ndre_current: number | null;
  ndwi_current: number | null;
  last_index_at: string | null;
}

export interface BlocksSummaryResponse {
  farm_id: string;
  as_of: string;
  units: BlockSummary[];
}

export async function getBlocksSummary(
  farmId: string,
): Promise<BlocksSummaryResponse> {
  const { data } = await apiClient.get<BlocksSummaryResponse>(
    `/v1/farms/${farmId}/blocks/summary`,
  );
  return data;
}
