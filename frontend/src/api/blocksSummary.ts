// Mirrors backend/app/modules/farms/blocks_summary_router.py — keep in lock-step.

import { apiClient } from "./client";

export type Health = "healthy" | "watch" | "critical" | "unknown";
export type MapSeverity = "watch" | "critical";

export interface BlockSummary {
  id: string;
  health: Health;
  alert_count: number;
  alert_severity: MapSeverity | null;
  /** Verb of the worst open alert (`irrigate`, `spray`, ...). Drives the map
   *  marker's glyph. Null when there is no open alert, or the tree leaf that
   *  opened it named no verb. */
  alert_action_type?: string | null;
  ndvi_current: number | null;
  ndre_current: number | null;
  ndwi_current: number | null;
  last_index_at: string | null;
  /** Imagery product this block's sub-block grid is configured against, or
   *  null when it has no grid. Drives the map's default grid overlay. */
  grid_product_id: string | null;
}

export interface BlocksSummaryResponse {
  farm_id: string;
  as_of: string;
  units: BlockSummary[];
}

/**
 * @param at Answer the alert rollup AS OF this instant instead of now: only
 *   alerts raised on or before it, and still unresolved then, are counted.
 *   The map's date bar sends it when the reader has scrubbed to a past pass,
 *   so the chips agree with the scene being drawn. Omitted means "now", which
 *   is what every caller before this did.
 */
export async function getBlocksSummary(
  farmId: string,
  at?: string | null,
): Promise<BlocksSummaryResponse> {
  const { data } = await apiClient.get<BlocksSummaryResponse>(
    `/v1/farms/${farmId}/blocks/summary`,
    { params: { at: at ?? undefined } },
  );
  return data;
}
