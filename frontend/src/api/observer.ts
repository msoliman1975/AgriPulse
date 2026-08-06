import { apiClient } from "./client";

// AgriPulse Observer — platform-admin transparency for the indices pipeline.
//
// Gated server-side on `platform.observe_pipeline`, which is read-only and
// separate from `platform.run_backfill`: seeing that a number is wrong does
// not grant the right to spend provider quota recomputing it.

export interface ObserverTenant {
  id: string;
  name: string;
  slug: string;
  schema_name: string;
}

/**
 * Farm picker row.
 *
 * The extra fields exist so an operator can tell "never configured" from
 * "configured and broken" before committing to a selection — both show zero
 * scenes, and nothing else distinguishes them.
 */
export interface ObserverFarm {
  id: string;
  name: string | null;
  code: string | null;
  block_count: number;
  blocks_with_imagery_sub: number;
  blocks_with_grid: number;
  has_weather_sub: boolean;
  first_scene_at: string | null;
  last_scene_at: string | null;
}

export interface ObserverProduct {
  id: string;
  code: string;
  name: string;
  resolution_m: number;
  bands: string[];
  supported_indices: string[];
  provider_code: string;
  provider_name: string;
}

export type StageVerdict = "ok" | "warn" | "bad" | "info" | "not_applicable";

export interface ObserverStage {
  key: string;
  label: string;
  count: number;
  /** Null where no denominator is meaningful (first stage; consumers). */
  expected: number | null;
  shortfall: number | null;
  verdict: StageVerdict;
  detail: Record<string, unknown>;
}

export interface ObserverOverview {
  farm_id: string;
  block_count: number;
  window_from: string;
  window_to: string;
  stages: ObserverStage[];
  calc_versions: Array<Record<string, unknown>>;
  /**
   * `block_index_daily` has no product dimension, so with two products on a
   * block the trend-coverage count cannot be attributed to the selected one.
   */
  trend_product_ambiguous: boolean;
  /** Consumers are counted by creation time in the window, not by lineage. */
  consumers_are_window_proxy: boolean;
}

export type HistogramBucketSize = "day" | "week" | "month";

export interface HistogramBucket {
  bucket: string;
  /** Succeeded AND wrote block aggregates. */
  computed: number;
  /** Succeeded but no aggregates — the download worked, the maths did not. */
  acquired_only: number;
  skipped: number;
  failed: number;
  pending: number;
  total: number;
}

export type JobStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped_cloud"
  | "skipped_duplicate";

export interface ObserverScene {
  job_id: string;
  block_id: string;
  block_name: string | null;
  block_code: string | null;
  product_id: string;
  scene_id: string;
  scene_datetime: string;
  status: JobStatus;
  cloud_cover_pct: number | null;
  valid_pixel_pct: number | null;
  error_code: string | null;
  error_message: string | null;
  stac_item_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_s: number | null;
  indices_written: number;
  cells_written: number;
  cells_expected: number;
  /** False means no grid governed this scene's time — 0 cells is correct. */
  gridded: boolean;
}

export interface ObserverIndexRow {
  index_code: string;
  mean: number | null;
  min: number | null;
  max: number | null;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  std_dev: number | null;
  valid_pixel_count: number;
  total_pixel_count: number;
  valid_pixel_pct: number | null;
  cloud_cover_pct: number | null;
  baseline_deviation: number | null;
  stac_item_id: string;
  inserted_at: string;
}

/** The selection rail, as the API sees it. */
export interface ObserverScope {
  farmId: string;
  from: string;
  to: string;
  blockIds?: string[];
  productId?: string | null;
}

const BASE = "/v1/admin/observer";

function scopeParams(scope: ObserverScope): Record<string, unknown> {
  return {
    farm_id: scope.farmId,
    from: scope.from,
    to: scope.to,
    // Repeated `blocks=` params; axios serializes an array that way by
    // default, which is what FastAPI's `list[UUID]` query expects.
    blocks: scope.blockIds?.length ? scope.blockIds : undefined,
    product: scope.productId || undefined,
  };
}

export async function listObserverTenants(): Promise<ObserverTenant[]> {
  const { data } = await apiClient.get<ObserverTenant[]>(`${BASE}/tenants`);
  return data;
}

export async function listObserverFarms(tenantId: string): Promise<ObserverFarm[]> {
  const { data } = await apiClient.get<ObserverFarm[]>(`${BASE}/tenants/${tenantId}/farms`);
  return data;
}

export async function listObserverProducts(
  tenantId: string,
  farmId: string,
): Promise<ObserverProduct[]> {
  const { data } = await apiClient.get<ObserverProduct[]>(
    `${BASE}/tenants/${tenantId}/farms/${farmId}/products`,
  );
  return data;
}

export async function getObserverOverview(
  tenantId: string,
  scope: ObserverScope,
): Promise<ObserverOverview> {
  const { data } = await apiClient.get<ObserverOverview>(`${BASE}/tenants/${tenantId}/overview`, {
    params: scopeParams(scope),
  });
  return data;
}

export async function getObserverHistogram(
  tenantId: string,
  scope: ObserverScope,
  bucket: HistogramBucketSize,
): Promise<HistogramBucket[]> {
  const { data } = await apiClient.get<HistogramBucket[]>(`${BASE}/tenants/${tenantId}/histogram`, {
    params: { ...scopeParams(scope), bucket },
  });
  return data;
}

export interface SceneFilters {
  status?: JobStatus[];
  maxValidPct?: number | null;
  withError?: boolean;
  limit?: number;
  offset?: number;
}

export async function listObserverScenes(
  tenantId: string,
  scope: ObserverScope,
  filters: SceneFilters = {},
): Promise<ObserverScene[]> {
  const { data } = await apiClient.get<ObserverScene[]>(`${BASE}/tenants/${tenantId}/scenes`, {
    params: {
      ...scopeParams(scope),
      status: filters.status?.length ? filters.status : undefined,
      max_valid_pct: filters.maxValidPct ?? undefined,
      with_error: filters.withError || undefined,
      limit: filters.limit ?? 100,
      offset: filters.offset ?? 0,
    },
  });
  return data;
}

export async function getSceneIndices(
  tenantId: string,
  args: { blockId: string; productId: string; sceneTime: string },
): Promise<ObserverIndexRow[]> {
  const { data } = await apiClient.get<ObserverIndexRow[]>(
    `${BASE}/tenants/${tenantId}/scenes/indices`,
    {
      params: {
        block_id: args.blockId,
        product_id: args.productId,
        scene_time: args.sceneTime,
      },
    },
  );
  return data;
}

// ---- L2: scene detail + pixel explain ------------------------------------

export interface GridSnapshot {
  grid_config_id: string;
  cell_size_m: number;
  utm_srid: number;
  cell_count: number;
  effective_from: string | null;
  effective_to: string | null;
}

export interface SceneDetail {
  /** The tenant /v1/config route needs a tenant scope; Observer has none. */
  tile_server_base_url: string;
  s3_bucket: string;
  job_id: string;
  block_id: string;
  product_id: string;
  block_code: string | null;
  block_name: string | null;
  farm_id: string;
  scene_id: string;
  scene_datetime: string;
  status: JobStatus;
  stac_item_id: string | null;
  cloud_cover_pct: number | null;
  valid_pixel_pct: number | null;
  error_code: string | null;
  error_message: string | null;
  requested_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  provider_code: string;
  provider_name: string;
  product_code: string;
  product_name: string;
  resolution_m: number;
  bands: string[];
  supported_indices: string[];
  aoi_hash: string;
  boundary_geojson: Record<string, unknown>;
  area_m2: number;
  raw_asset_key: string | null;
  index_asset_keys: Record<string, string>;
  mask_ruleset: string;
  mask_classes: number[];
  /** Null when no grid config governed this scene's time. */
  grid: GridSnapshot | null;
}

export interface PixelIndexResult {
  /** What this pixel contributed to the aggregate — null when nothing. */
  value: number | null;
  /** What the formula produced regardless, so a dropped pixel still shows it. */
  raw_value: number | null;
  formula_text: string | null;
  substituted: string | null;
  excluded_reason: string | null;
}

export interface PixelExplain {
  job_id: string;
  scene_id: string;
  scene_datetime: string;
  block_id: string;
  raw_asset_key: string;
  row: number;
  col: number;
  lon: number;
  lat: number;
  inside_aoi: boolean;
  band_values: Record<string, number | null>;
  scl_value: number | null;
  scl_label: string | null;
  masked: boolean;
  mask_reason: string | null;
  indices: Record<string, PixelIndexResult>;
  unavailable_indices: Record<string, string>;
  /** False = the product ships no SCL band, so no cloud masking happened. */
  masking_available: boolean;
}

export interface PixelBudget {
  job_id: string;
  aoi_pixel_count: number;
  masked_pixel_count: number;
  per_index: Record<string, { aoi: number; masked: number; nodata: number; valid: number }>;
  recomputed_live: boolean;
}

export async function getSceneDetail(tenantId: string, jobId: string): Promise<SceneDetail> {
  const { data } = await apiClient.get<SceneDetail>(`${BASE}/tenants/${tenantId}/scenes/${jobId}`);
  return data;
}

export async function explainPixel(
  tenantId: string,
  jobId: string,
  lon: number,
  lat: number,
): Promise<PixelExplain> {
  const { data } = await apiClient.get<PixelExplain>(
    `${BASE}/tenants/${tenantId}/scenes/${jobId}/pixel`,
    { params: { lon, lat } },
  );
  return data;
}

export async function getPixelBudget(tenantId: string, jobId: string): Promise<PixelBudget> {
  const { data } = await apiClient.get<PixelBudget>(
    `${BASE}/tenants/${tenantId}/scenes/${jobId}/pixel-budget`,
  );
  return data;
}
