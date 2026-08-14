import { apiClient } from "./client";

// Platform-admin backfill console. Every call here is gated on
// `platform.run_backfill` server-side — backfill spends a shared CDSE
// processing-unit allowance, so it is deliberately not a tenant surface.

export interface BackfillTenant {
  id: string;
  name: string;
  slug: string;
  schema_name: string;
}

export interface BackfillFarm {
  id: string;
  name: string | null;
  code: string | null;
  block_count: number;
  /** Set when a run already holds this farm — only one run per farm. */
  active_run_id: string | null;
}

export interface BackfillEstimate {
  days: number;
  blocks: number;
  /** Provider fetches the run will dispatch, block AOIs and whole-farm ones together. */
  subscriptions: number;
  /** How many of those are whole-farm fetches — non-zero means this farm has cut over. */
  farm_aoi_subscriptions: number;
  estimated_scenes: number;
  estimated_units: number;
  /** Always true today: there is no CDSE metering, so this is an approximation. */
  units_estimated: boolean;
  weather_hours: number;
  /** Weather fetches the run will dispatch — one per provider. Zero means nothing to fetch. */
  weather_subscriptions: number;
  /** Provider codes the farm is actually subscribed to, e.g. ["open_meteo"]. */
  weather_providers: string[];
}

export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed";
export type RunKind = "backfill" | "indices";

export interface BackfillRun {
  id: string;
  tenant_id: string;
  tenant_name: string | null;
  farm_id: string;
  farm_name: string | null;
  kind: RunKind;
  sources: Record<string, boolean>;
  window_from: string;
  window_to: string;
  status: RunStatus;
  error: string | null;
  /** Per-source counters written by the tasks, e.g. { imagery: { scenes: 12 } }. */
  progress: Record<string, Record<string, unknown>>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  created_by_email: string | null;
}

export interface RunPayload {
  farm_id: string;
  window_from: string;
  window_to: string;
  imagery: boolean;
  weather: boolean;
  kind?: RunKind;
}

const BASE = "/v1/admin/backfill";

export async function listBackfillTenants(): Promise<BackfillTenant[]> {
  const { data } = await apiClient.get<BackfillTenant[]>(`${BASE}/tenants`);
  return data;
}

export async function listBackfillFarms(tenantId: string): Promise<BackfillFarm[]> {
  const { data } = await apiClient.get<BackfillFarm[]>(`${BASE}/tenants/${tenantId}/farms`);
  return data;
}

export async function estimateBackfill(
  tenantId: string,
  payload: Omit<RunPayload, "kind">,
): Promise<BackfillEstimate> {
  const { data } = await apiClient.post<BackfillEstimate>(
    `${BASE}/tenants/${tenantId}:estimate`,
    payload,
  );
  return data;
}

export async function createBackfillRun(
  tenantId: string,
  payload: RunPayload,
): Promise<BackfillRun> {
  const { data } = await apiClient.post<BackfillRun>(`${BASE}/tenants/${tenantId}/runs`, payload);
  return data;
}

export async function listBackfillRuns(params?: {
  tenantId?: string;
  status?: RunStatus;
  limit?: number;
}): Promise<BackfillRun[]> {
  const { data } = await apiClient.get<BackfillRun[]>(`${BASE}/runs`, {
    params: {
      tenant_id: params?.tenantId,
      status: params?.status,
      limit: params?.limit,
    },
  });
  return data;
}

/** True while a run is still doing work — drives the list's auto-refresh. */
export function isRunActive(run: BackfillRun): boolean {
  return run.status === "queued" || run.status === "running";
}
