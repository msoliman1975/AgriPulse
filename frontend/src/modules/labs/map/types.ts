// Map-First validation prototype — see docs/proposals/map-first.md.
// Types follow the spec; values are derived client-side from existing APIs.

export type Health = "healthy" | "watch" | "critical" | "unknown";
export type MapSeverity = "watch" | "critical";
export type SpecUnitType = "block" | "pivot" | "pivot_section";
// The three indices `GET /farms/{id}/blocks/summary` publishes as columns, and
// so the three `loadUnitDetail` seeds into `UnitDetail.indices`. NOT the set
// the block time-series route serves — that one takes any of the thirteen
// codes (see api/indices.ts::getTimeseries), which is what the Block Dock
// reads for every other index.
export type IndexCode = "ndvi" | "ndre" | "ndwi";

export interface UnitSummary {
  id: string;
  health: Health;
  has_alert: boolean;
  alert_severity: MapSeverity | null;
  alert_count: number;
  /** Verb of the worst open alert. Picks the marker glyph — see markerIcons. */
  alert_action_type: string | null;
  ndvi_current: number | null;
  ndre_current: number | null;
  ndwi_current: number | null;
  /** Product the block's sub-block grid is configured against, if gridded. */
  grid_product_id: string | null;
}

export interface IndexSeries {
  current: number | null;
  trend_7d_delta: number | null;
  series_30d: { time: string; value: number | null }[];
}

export interface UnitAlert {
  id: string;
  severity: MapSeverity;
  code: string;
  message: string;
  raised_at: string;
}

export interface IrrigationEventSummary {
  date: string;
  volume_mm: number;
  is_emergency?: boolean;
}

export interface UnitDetail {
  id: string;
  name: string;
  type: SpecUnitType;
  parent_pivot_id: string | null;
  crop: string | null;
  area_ha: number;
  health: Health;
  last_updated: string | null;
  alerts: UnitAlert[];
  indices: Record<IndexCode, IndexSeries>;
  irrigation: {
    last: IrrigationEventSummary | null;
    next: IrrigationEventSummary | null;
    soil_moisture_pct: number | null;
    soil_status: "optimal" | "low" | "critical" | "unknown";
  };
  recommendations: string[];
  // `label` is the English humanised activity type, kept for the legacy
  // DetailPanel. New surfaces read `activity_type` and translate it, so the
  // label switches with the UI language instead of being frozen at fetch time.
  activities: {
    date: string;
    label: string;
    activity_type: string;
    phase: "next7d" | "later";
  }[];
  // Same split: `day` is a pre-rendered en-US weekday, `date` is the raw ISO
  // day so a locale-aware caller can format it itself.
  weather_3d: { day: string; date: string; temp_c_max: number | null }[];
  // Season plan summary (farm-level active plan, mirrored on each block).
  plan: {
    season_label: string;
    season_year: number;
    name: string | null;
    status: string;
  } | null;
  // The member responsible for this block — `blocks.agronomist_membership_id`.
  // Surfaced here because it is what dispatch defaults to, and until now it was
  // only settable on a legacy form that nothing in the console linked to.
  responsible_membership_id: string | null;
  // Current crop assignment for this block.
  crop_assignment: {
    // block_crops.id — the key for the crop-attributes endpoints.
    id: string;
    crop_name: string;
    variety_name: string | null;
    strain_name: string | null;
    // Denormalized hierarchical path, e.g. "mango.alphonso.short".
    crop_path: string;
    season_label: string;
    planting_date: string | null;
    growth_stage: string | null;
    status: string;
  } | null;
  // Latest observation per custom signal recorded against this block.
  signals: {
    code: string;
    value: string;
    unit: string | null;
    recorded_at: string;
  }[];
}

// Integration health snapshot for a block. Deliberately NOT part of
// UnitDetail: it comes from a different endpoint on a different (slower)
// clock, and folding it in here is what let it block the map render. The
// pages fetch it separately and pass it to the panel alongside the detail.
export interface UnitIntegration {
  weather: IntegrationKindStatus;
  imagery: IntegrationKindStatus;
}

export interface IntegrationKindStatus {
  active_subs: number;
  last_sync_at: string | null;
  last_failed_at: string | null;
  failed_24h: number;
  running_count: number;
  overdue_count: number;
}

export interface UnitFeatureProps {
  id: string;
  type: SpecUnitType | "pivot_logical_group";
  parent_pivot_id: string | null;
  is_logical_pivot: boolean;
  name: string;
  // Joined from summary so MapLibre paint expressions can read it directly.
  health: Health;
  has_alert: boolean;
  alert_severity: MapSeverity | "none";
  // How many open alerts the block carries, and the verb of the worst one.
  // Both are read by the alert marker: the count is fitted into the chip and
  // the verb picks its glyph. The summary endpoint has published the count
  // since it shipped, but the old circle badge had nowhere to draw it, so a
  // block with one alert and a block with eleven looked the same.
  alert_count: number;
  alert_action_type: string | null;
  // True when active_from is in the future — block exists but not yet
  // operational. Rendered ghosted on the map.
  is_future: boolean;
  // Worst current weather-driven disease/pest risk level (PR-R4b); "none"
  // when the block has no scored risk. Read by the map fill expression when
  // the risk overlay is toggled on.
  risk_level: "low" | "moderate" | "high" | "none";
  /**
   * The crop this block carried on the date being drawn, already localized.
   *
   * Absent unless the caller asked for crop labels, and absent per block when
   * that block had no assignment covering the date — the label expression
   * falls back to `name`, so an unplanted block still says which block it is.
   */
  crop_label?: string;
  /** Injected by Farm Console v2: the block's index class colour. */
  class_color?: string;
}
