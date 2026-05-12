// Map-First validation prototype — see docs/proposals/map-first.md.
// Types follow the spec; values are derived client-side from existing APIs.

export type Health = "healthy" | "watch" | "critical" | "unknown";
export type MapSeverity = "watch" | "critical";
export type SpecUnitType = "block" | "pivot" | "pivot_section";
export type IndexCode = "ndvi" | "ndre" | "ndwi"; // backend has no NDMI; NDWI is the closest moisture-related proxy.

export interface UnitSummary {
  id: string;
  health: Health;
  has_alert: boolean;
  alert_severity: MapSeverity | null;
  alert_count: number;
  ndvi_current: number | null;
  ndre_current: number | null;
  ndwi_current: number | null;
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
  activities: { date: string; label: string; phase: "next7d" | "later" }[];
  weather_3d: { day: string; temp_c_max: number | null }[];
  // Season plan summary (farm-level active plan, mirrored on each block).
  plan: {
    season_label: string;
    season_year: number;
    name: string | null;
    status: string;
  } | null;
  // Current crop assignment for this block.
  crop_assignment: {
    crop_name: string;
    variety_name: string | null;
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
  // Integration health snapshot for the block.
  integration: {
    weather: IntegrationKindStatus;
    imagery: IntegrationKindStatus;
  } | null;
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
  // True when active_from is in the future — block exists but not yet
  // operational. Rendered ghosted on the map.
  is_future: boolean;
}
