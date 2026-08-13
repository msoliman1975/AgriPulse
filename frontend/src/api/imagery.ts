import { apiClient } from "./client";
import type { CursorPage } from "./pagination";

// Mirrors backend/app/modules/imagery/schemas.py — keep in lock-step.

export type IngestionJobStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped_cloud"
  | "skipped_duplicate";

export interface IngestionJob {
  id: string;
  block_id: string;
  subscription_id: string;
  product_id: string;
  scene_id: string;
  scene_datetime: string;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  status: IngestionJobStatus;
  cloud_cover_pct: string | null;
  valid_pixel_pct: string | null;
  error_message: string | null;
  stac_item_id: string | null;
}

export interface Subscription {
  id: string;
  block_id: string;
  product_id: string;
  cadence_hours: number | null;
  cloud_cover_max_pct: number | null;
  is_active: boolean;
  last_successful_ingest_at: string | null;
  last_attempted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubscriptionCreatePayload {
  product_id: string;
  cadence_hours?: number | null;
  cloud_cover_max_pct?: number | null;
}

export interface RefreshResponse {
  queued_subscription_ids: string[];
  correlation_id: string | null;
}

export interface ListScenesParams {
  cursor?: string | null;
  limit?: number;
  from?: string;
  to?: string;
}

// --- Subscriptions --------------------------------------------------------

export async function listSubscriptions(
  blockId: string,
  options: { include_inactive?: boolean } = {},
): Promise<Subscription[]> {
  const { data } = await apiClient.get<Subscription[]>(
    `/v1/blocks/${blockId}/imagery/subscriptions`,
    { params: { include_inactive: options.include_inactive ?? false } },
  );
  return data;
}

export async function createSubscription(
  blockId: string,
  payload: SubscriptionCreatePayload,
): Promise<Subscription> {
  const { data } = await apiClient.post<Subscription>(
    `/v1/blocks/${blockId}/imagery/subscriptions`,
    payload,
  );
  return data;
}

export async function revokeSubscription(blockId: string, subscriptionId: string): Promise<void> {
  await apiClient.delete(`/v1/blocks/${blockId}/imagery/subscriptions/${subscriptionId}`);
}

// --- Refresh + Scenes ----------------------------------------------------

export async function triggerRefresh(blockId: string): Promise<RefreshResponse> {
  const { data } = await apiClient.post<RefreshResponse>(`/v1/blocks/${blockId}/imagery/refresh`);
  return data;
}

/** One acquisition DAY across a farm — a column of the console's scene strip. */
export interface FarmScene {
  scene_date: string;
  /** Instant to send as `at` on grid-cells: the last sensing time of the day. */
  at: string;
  block_count: number;
  succeeded_count: number;
  skipped_cloud_count: number;
  /**
   * Blocks whose index rasters exist for this pass — how much of the day can
   * actually be drawn. Ingestion and index computation are separate tasks and
   * a historical backfill runs only the first, so a day can be entirely
   * "succeeded" and still render nothing. Zero means never processed.
   */
  computed_count: number;
  /** Mean across jobs that reported one; null when none did. */
  cloud_cover_pct: string | null;
}

export interface FarmScenesResponse {
  farm_id: string;
  items: FarmScene[];
  /** Median gap between recent acquisitions, in days; null if unknowable. */
  median_gap_days: number | null;
}

/**
 * A farm's acquisition history in one request.
 *
 * Returns `null` on 404 so the console can degrade to "no timeline" while an
 * older API is still serving — charts deploy independently, so a new frontend
 * can meet an api that predates this route. Same contract as
 * `getFarmGridCells`, and for the same reason.
 */
export async function listFarmScenes(
  farmId: string,
  limit = 120,
): Promise<FarmScenesResponse | null> {
  try {
    const { data } = await apiClient.get<FarmScenesResponse>(`/v1/farms/${farmId}/scenes`, {
      params: { limit },
    });
    return data;
  } catch (err: unknown) {
    if (typeof err === "object" && err !== null && "response" in err) {
      const resp = (err as { response?: { status?: number } }).response;
      if (resp?.status === 404) return null;
    }
    throw err;
  }
}

export interface FarmSceneAsset {
  block_id: string;
  product_id: string;
  /**
   * `provider/product/scene/aoi` — every part of the COG object key except
   * the index code. Build a key as `${stac_item_id}/${index}.tif`; the aoi
   * hash it ends with is why a reshaped block's old rasters cannot leak in.
   */
  stac_item_id: string;
  scene_datetime: string;
  /** Ground sample distance in metres; null when the product is unreadable. */
  resolution_m: string | null;
}

export interface FarmSceneAssetsResponse {
  farm_id: string;
  at: string | null;
  items: FarmSceneAsset[];
}

/**
 * Which index raster to draw for each block at one pass.
 *
 * Blocks absent from the response have no usable raster for that pass — a
 * cloud-skipped or failed job — and the caller must leave them to the base
 * map rather than falling back to an older scene, which would contradict the
 * date the timeline is parked on.
 *
 * Returns `null` on 404 so the console degrades to "no pixel layer" against
 * an api that predates the route, exactly as `listFarmScenes` does.
 */
export async function listFarmSceneAssets(
  farmId: string,
  at?: string,
): Promise<FarmSceneAssetsResponse | null> {
  try {
    const { data } = await apiClient.get<FarmSceneAssetsResponse>(
      `/v1/farms/${farmId}/scene-assets`,
      { params: { at: at ?? undefined } },
    );
    return data;
  } catch (err: unknown) {
    if (typeof err === "object" && err !== null && "response" in err) {
      const resp = (err as { response?: { status?: number } }).response;
      if (resp?.status === 404) return null;
    }
    throw err;
  }
}

export async function listScenes(
  blockId: string,
  params: ListScenesParams = {},
): Promise<CursorPage<IngestionJob>> {
  const { data } = await apiClient.get<CursorPage<IngestionJob>>(`/v1/blocks/${blockId}/scenes`, {
    params: {
      cursor: params.cursor ?? undefined,
      limit: params.limit ?? undefined,
      from: params.from ?? undefined,
      to: params.to ?? undefined,
    },
  });
  return data;
}
