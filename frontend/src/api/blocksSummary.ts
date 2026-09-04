// Mirrors backend/app/modules/farms/blocks_summary_router.py — keep in lock-step.

import { apiClient } from "./client";

export type Health = "healthy" | "watch" | "critical" | "unknown";
export type MapSeverity = "watch" | "critical";

/** Why a block is in its health class. Mirrors
 *  `app.shared.health_definition.HealthReason` — eight words, closed set.
 *  Copy lives once, under `common:healthReason.*`, so the Farm Console dock
 *  and the Insights scorecard cannot word the same block differently. */
export type HealthReason =
  | "critical_alert"
  | "warning_alert"
  | "cell_share"
  | "strong_recommendation"
  | "no_coverage"
  | "no_tree"
  | "stale"
  | "all_clear";

/** Which tier had the last word on a block's health definition. Mirrors
 *  `app.modules.health.service.DefinitionSource`. The reason says what the
 *  evidence showed; the source says whose rule read it. */
export type HealthSource = "platform" | "crop" | "farm";

export interface BlockSummary {
  id: string;
  health: Health;
  /** Why `health` is what it is. Null while the backend's
   *  `health_definition_enabled` is off: the NDVI rule it falls back to has
   *  no reason to give, because it cannot tell "every tree came out clear"
   *  from "nothing ever ran". Optional so an older API still parses. */
  health_reason?: HealthReason | null;
  /** Which tier decided, and the version of the crop row behind it. Null for
   *  the same reason `health_reason` is: the NDVI rule has no tiers. */
  health_source?: HealthSource | null;
  health_definition_version?: number | null;
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
