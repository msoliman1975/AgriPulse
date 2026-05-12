// Mirrors backend/app/modules/integrations_health/schemas.py.

import { apiClient } from "./client";

export interface FarmIntegrationHealth {
  farm_id: string;
  farm_name: string;
  weather_active_subs: number;
  weather_last_sync_at: string | null;
  weather_last_failed_at: string | null;
  imagery_active_subs: number;
  imagery_last_sync_at: string | null;
  imagery_failed_24h: number;
  // PR-IH2 additions
  weather_failed_24h: number;
  weather_running_count: number;
  imagery_running_count: number;
  weather_overdue_count: number;
  imagery_overdue_count: number;
}

export interface BlockIntegrationHealth {
  block_id: string;
  farm_id: string;
  block_name: string;
  weather_active_subs: number;
  weather_last_sync_at: string | null;
  weather_last_failed_at: string | null;
  imagery_active_subs: number;
  imagery_last_sync_at: string | null;
  imagery_failed_24h: number;
  // PR-IH2 additions
  weather_failed_24h: number;
  weather_running_count: number;
  imagery_running_count: number;
  weather_overdue_count: number;
  imagery_overdue_count: number;
}

export type AttemptKind = "weather" | "imagery";
export type AttemptStatus = "running" | "succeeded" | "failed" | "skipped";

export interface IntegrationAttempt {
  attempt_id: string;
  kind: AttemptKind;
  subscription_id: string;
  block_id: string;
  farm_id: string | null;
  provider_code: string | null;
  started_at: string;
  // PR-IH8: when the job entered the queue (imagery has a real queue,
  // weather sets queued_at == started_at). May be null for older rows.
  queued_at: string | null;
  completed_at: string | null;
  status: AttemptStatus;
  // duration_ms == run_ms for back-compat; prefer the split fields.
  duration_ms: number | null;
  wait_ms: number | null;
  run_ms: number | null;
  rows_ingested: number | null;
  error_code: string | null;
  error_message: string | null;
  scene_id: string | null;
  // PR-IH9: position within the current consecutive-failure streak.
  // 0 for non-failures; N for the Nth consecutive failure on this
  // subscription. Surfaced as "Attempt #N" when > 1.
  failed_streak_position: number;
}

export async function listFarmHealth(
  basePath: string = "/v1",
): Promise<FarmIntegrationHealth[]> {
  const { data } = await apiClient.get<FarmIntegrationHealth[]>(
    `${basePath}/integrations/health/farms`,
  );
  return data;
}

export async function listBlockHealth(
  farmId: string,
  basePath: string = "/v1",
): Promise<BlockIntegrationHealth[]> {
  const { data } = await apiClient.get<BlockIntegrationHealth[]>(
    `${basePath}/integrations/health/farms/${farmId}/blocks`,
  );
  return data;
}

export interface RecentAttemptsParams {
  kind?: AttemptKind;
  status?: AttemptStatus;
  farm_id?: string;
  limit?: number;
}

export async function listRecentAttempts(
  params: RecentAttemptsParams = {},
  basePath: string = "/v1",
): Promise<IntegrationAttempt[]> {
  const { data } = await apiClient.get<IntegrationAttempt[]>(
    `${basePath}/integrations/health/recent`,
    { params },
  );
  return data;
}

export type QueueState = "overdue" | "running" | "stuck";

export interface QueueEntry {
  kind: AttemptKind;
  state: QueueState;
  subscription_id: string;
  block_id: string;
  farm_id: string | null;
  provider_code: string | null;
  since: string | null;
  attempt_id: string | null;
}

export interface QueueParams {
  kind?: AttemptKind;
  state?: QueueState;
  stuck_minutes?: number;
}

export async function listQueue(
  params: QueueParams = {},
  basePath: string = "/v1",
): Promise<QueueEntry[]> {
  const { data } = await apiClient.get<QueueEntry[]>(
    `${basePath}/integrations/health/queue`,
    { params },
  );
  return data;
}

export type ProbeStatus = "ok" | "error" | "timeout";

export interface ProviderHealth {
  provider_kind: AttemptKind;
  provider_code: string;
  last_status: ProbeStatus | null;
  last_probe_at: string | null;
  last_latency_ms: number | null;
  last_error_message: string | null;
  failed_24h: number;
}

export interface ProviderProbe {
  probe_at: string;
  status: ProbeStatus;
  latency_ms: number | null;
  error_message: string | null;
}

export interface ProviderErrorHistogramEntry {
  error_code: string;
  count: number;
}

export async function listProviderErrorHistogram(
  provider_kind: AttemptKind,
  provider_code: string,
  hours: number = 24,
): Promise<ProviderErrorHistogramEntry[]> {
  const { data } = await apiClient.get<ProviderErrorHistogramEntry[]>(
    "/v1/admin/integrations/health/error-histogram",
    { params: { provider_kind, provider_code, hours } },
  );
  return data;
}

export async function listProviders(
  basePath: string = "/v1",
): Promise<ProviderHealth[]> {
  const { data } = await apiClient.get<ProviderHealth[]>(
    `${basePath}/integrations/health/providers`,
  );
  return data;
}

export async function listPlatformProviders(): Promise<ProviderHealth[]> {
  const { data } = await apiClient.get<ProviderHealth[]>(
    "/v1/admin/integrations/health/providers",
  );
  return data;
}

export async function listRecentProbes(
  provider_kind: AttemptKind,
  provider_code: string,
  limit: number = 100,
): Promise<ProviderProbe[]> {
  const { data } = await apiClient.get<ProviderProbe[]>(
    "/v1/admin/integrations/health/probes",
    { params: { provider_kind, provider_code, limit } },
  );
  return data;
}

export async function listBlockAttempts(
  blockId: string,
  params: { kind?: AttemptKind; limit?: number } = {},
  basePath: string = "/v1",
): Promise<IntegrationAttempt[]> {
  const { data } = await apiClient.get<IntegrationAttempt[]>(
    `${basePath}/integrations/health/blocks/${blockId}/attempts`,
    { params },
  );
  return data;
}
