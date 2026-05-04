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
