// Reports API — mirrors backend/app/modules/reports/schemas.py. Read-only
// per-farm report payloads; Decimals serialise as strings (Pydantic).

import { apiClient } from "./client";

export interface ReportPeriod {
  since: string;
  until: string;
}

// ---- Custom (tenant-defined) report columns ------------------------------
//
// Crop attributes and custom signals, the two catalogs a tenant defines for
// itself. Both render as one more column on a block-grained report, so they
// share one envelope regardless of which catalog they came from.

export type CustomFieldSource = "crop_attribute" | "signal";

export interface CustomFieldOption {
  code: string;
  name_en: string;
  name_ar: string | null;
}

export interface CustomFieldDef {
  /** `"{source}:{code}"` — the column id, and what `fields` carries. */
  key: string;
  source: CustomFieldSource;
  code: string;
  name_en: string;
  /** Always null for a signal: that catalog has no Arabic name column. */
  name_ar: string | null;
  /** The source's own type name — see backend schemas.CustomFieldDef. */
  value_type: string;
  unit_en: string | null;
  unit_ar: string | null;
  decimal_places: number | null;
  options: CustomFieldOption[] | null;
}

export interface CustomFieldValue {
  key: string;
  source: CustomFieldSource;
  code: string;
  value_numeric: string | null;
  value_text: string | null;
  value_boolean: boolean | null;
  value_date: string | null;
  value_options: string[] | null;
  /** Signals only: when the observation behind this cell was taken. */
  observed_at: string | null;
}

/** A block's custom cells, keyed by `CustomFieldDef.key`. A key that is
 * absent means no value — which is not the same as zero. */
export type CustomFieldCells = Record<string, CustomFieldValue | undefined>;

export interface CustomFieldsResponse {
  farm_id: string;
  fields: CustomFieldDef[];
}

/** The column picker's menu for one farm. */
export async function getReportCustomFields(farmId: string): Promise<CustomFieldsResponse> {
  const { data } = await apiClient.get<CustomFieldsResponse>(
    `/v1/farms/${farmId}/reports/custom-fields`,
  );
  return data;
}

/** Comma-separated `source:code` list. Every block-grained report takes it. */
export interface CustomFieldParams {
  fields?: string;
}

// ---- PR-1: Seasonal Crop Health ------------------------------------------

export type CropHealthStatus = "normal" | "watch" | "stressed" | "unknown";

export interface CropHealthBlockRow {
  block_id: string;
  block_name: string;
  block_name_ar: string | null;
  crop_name_en: string | null;
  crop_name_ar: string | null;
  crop_path: string | null;
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
  custom: CustomFieldCells;
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
  farm_name_ar: string | null;
  index_code: string;
  period: ReportPeriod;
  crop_path: string | null;
  blocks: CropHealthBlockRow[];
  summary: CropHealthSummary;
  custom_fields: CustomFieldDef[];
}

export interface CropHealthParams extends CustomFieldParams {
  index_code?: string;
  since?: string;
  until?: string;
  /** Crop-taxonomy path prefix filter (e.g. "mango.alphonso.short"). */
  crop_path?: string;
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

export type ZoneAnomalyStatus = "anomalies" | "clear" | "insufficient" | "no_data" | "no_grid";

export interface ZoneAnomalyBlockRow {
  block_id: string;
  block_name: string;
  block_name_ar: string | null;
  status: ZoneAnomalyStatus;
  scene_time: string | null;
  cell_count: number;
  flagged_count: number;
  flagged_area_ha: string | null;
  worst_z: string | null;
  block_mean: string | null;
  block_std: string | null;
  threshold_k: string | null;
  custom: CustomFieldCells;
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
  farm_name_ar: string | null;
  index_code: string;
  period: ReportPeriod;
  blocks: ZoneAnomalyBlockRow[];
  summary: ZoneAnomalySummary;
  custom_fields: CustomFieldDef[];
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

/** Date range plus custom columns — the block-grained non-index reports. */
export interface BlockRangeParams extends RangeParams, CustomFieldParams {}

export interface WaterBalanceWeather {
  days_with_data: number;
  et0_mm_total: string | null;
  precip_mm_total: string | null;
  et0_mm_avg_daily: string | null;
}

export interface WaterBalanceBlockRow {
  block_id: string;
  block_name: string;
  block_name_ar: string | null;
  scheduled_count: number;
  applied_count: number;
  skipped_count: number;
  pending_count: number;
  recommended_mm_total: string | null;
  applied_mm_total: string | null;
  adherence_pct: string | null;
  last_scheduled_for: string | null;
  custom: CustomFieldCells;
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
  farm_name_ar: string | null;
  period: ReportPeriod;
  weather: WaterBalanceWeather;
  blocks: WaterBalanceBlockRow[];
  summary: WaterBalanceSummary;
  custom_fields: CustomFieldDef[];
}

export async function getWaterBalanceReport(
  farmId: string,
  params: BlockRangeParams = {},
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
  // Climatology anomaly roll-up (PR-W6); null until baselines exist.
  days_with_anomaly: number | null;
  heat_anomaly_days: number | null;
  et0_anomaly_days: number | null;
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
  // Per-day z-scores vs the seasonal climatology (PR-W6).
  temp_anomaly_z: string | null;
  precip_anomaly_z: string | null;
  et0_anomaly_z: string | null;
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
  farm_name_ar: string | null;
  period: ReportPeriod;
  crop_path: string | null;
  stats: WeatherSummaryStats;
  daily: WeatherDailyPoint[];
  crops: WeatherCropContext[];
}

/** Weather-summary params: date range plus an optional crop-taxonomy
 * path prefix that narrows the crop context list. */
export interface WeatherSummaryParams extends RangeParams {
  crop_path?: string;
}

export async function getWeatherSummaryReport(
  farmId: string,
  params: WeatherSummaryParams = {},
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
  block_name_ar: string | null;
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
  farm_name_ar: string | null;
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

// ---- PR-R5: Disease & Pest Pressure --------------------------------------

export interface WeatherRiskPressureRow {
  block_id: string;
  block_name: string;
  block_name_ar: string | null;
  risk_code: string;
  days_observed: number;
  peak_score: number;
  mean_score: number | null;
  days_high: number;
  days_moderate: number;
  latest_level: "low" | "moderate" | "high";
  latest_score: number;
  latest_date: string;
  custom: CustomFieldCells;
}

export interface WeatherRiskPressureSummary {
  block_count: number;
  pathogen_count: number;
  blocks_at_risk: number;
  total_high_days: number;
  row_count: number;
}

export interface WeatherRiskPressureReportResponse {
  farm_id: string;
  farm_name: string;
  farm_name_ar: string | null;
  period: ReportPeriod;
  rows: WeatherRiskPressureRow[];
  summary: WeatherRiskPressureSummary;
  custom_fields: CustomFieldDef[];
}

export async function getWeatherRiskPressureReport(
  farmId: string,
  params: BlockRangeParams = {},
): Promise<WeatherRiskPressureReportResponse> {
  const { data } = await apiClient.get<WeatherRiskPressureReportResponse>(
    `/v1/farms/${farmId}/reports/weather-risk-pressure`,
    { params },
  );
  return data;
}

// ---- PR-R6: Signal Details -----------------------------------------------
//
// The one report whose rows are observations rather than blocks. Every other
// report collapses custom signals to one value per block, which cannot answer
// what the scouts actually recorded, who recorded it, and what they wrote.

export interface SignalDetailFilters {
  signal_codes: string[];
  block_ids: string[];
  categorical_values: string[];
  min_value: string | null;
  max_value: string | null;
  recorded_by: string | null;
  location_mode: string | null;
  with_notes_only: boolean;
  with_attachment_only: boolean;
}

export interface SignalDetailRow {
  observation_id: string;
  observed_at: string;
  recorded_at: string;
  signal_code: string;
  signal_name: string;
  signal_name_ar: string | null;
  /** numeric | categorical | event | boolean | geopoint. Pick the value
   * column from this rather than probing for the non-null one: `false` and
   * `0` are real values. */
  value_kind: string;
  unit: string | null;
  unit_ar: string | null;
  /** The definition's value list and its Arabic labels, matched by position.
   * The stored reading is always the English code, so both are needed to
   * show an Arabic label for it. */
  categorical_values: string[] | null;
  categorical_values_ar: string[] | null;
  value_numeric: string | null;
  value_categorical: string | null;
  value_event: string | null;
  value_boolean: boolean | null;
  /** Null for a farm-level observation. */
  block_id: string | null;
  block_name: string | null;
  block_name_ar: string | null;
  crop_path: string | null;
  notes: string | null;
  recorded_by: string;
  recorded_by_name: string | null;
  recorded_by_name_ar: string | null;
  location_mode: string;
  has_attachment: boolean;
  /** Set when the row was part of a grouped template submission. */
  template_observation_id: string | null;
  /** Set when the row came from a CSV upload. */
  import_batch_id: string | null;
}

export interface SignalDetailCategoryCount {
  value: string;
  count: number;
}

export interface SignalDetailStat {
  signal_code: string;
  signal_name: string;
  signal_name_ar: string | null;
  value_kind: string;
  unit: string | null;
  observation_count: number;
  block_count: number;
  recorder_count: number;
  first_observed_at: string;
  last_observed_at: string;
  min_value: string | null;
  mean_value: string | null;
  max_value: string | null;
  categories: SignalDetailCategoryCount[];
}

export interface SignalDetailSummary {
  observation_count: number;
  signal_count: number;
  block_count: number;
  recorder_count: number;
  /** True when the row cap cut the table short — the stats above then
   * describe the returned page, not the whole period. */
  truncated: boolean;
}

export interface SignalDetailsReportResponse {
  farm_id: string;
  farm_name: string;
  farm_name_ar: string | null;
  period: ReportPeriod;
  filters: SignalDetailFilters;
  rows: SignalDetailRow[];
  stats: SignalDetailStat[];
  summary: SignalDetailSummary;
}

export interface SignalDetailsParams extends RangeParams {
  /** Repeatable: axios serialises an array as `?signal_code=a&signal_code=b`. */
  signal_code?: string[];
  block_id?: string[];
  value?: string[];
  min_value?: string;
  max_value?: string;
  recorded_by?: string;
  location_mode?: string;
  with_notes_only?: boolean;
  with_attachment_only?: boolean;
  limit?: number;
}

export async function getSignalDetailsReport(
  farmId: string,
  params: SignalDetailsParams = {},
): Promise<SignalDetailsReportResponse> {
  const { data } = await apiClient.get<SignalDetailsReportResponse>(
    `/v1/farms/${farmId}/reports/signal-details`,
    { params },
  );
  return data;
}
