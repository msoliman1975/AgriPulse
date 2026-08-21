// Mirrors backend/app/modules/platform_alerts/schemas.py.
//
// Keep the unions below in lock-step with the CHECK constraints in public
// migration 0069. A mirrored constant that drifts does not throw here - it
// silently degrades the UI into rendering a raw enum string where a label
// belongs, which is the failure mode this codebase has hit before.

import { apiClient } from "./client";

export type AlertCategory = "imagery" | "thermal" | "weather" | "index_calc" | "task";
export type AlertKind =
  | "stream_silent"
  | "peer_lag"
  | "failure_streak"
  | "task_error"
  | "stuck_job";
export type AlertSeverity = "critical" | "warning";
export type AlertStatus = "open" | "acknowledged" | "resolved";

/** `live` is not a stored status - it is the filter meaning open OR acknowledged. */
export type AlertStatusFilter = AlertStatus | "live";

export interface PlatformAlert {
  id: string;
  alert_key: string;
  category: AlertCategory;
  kind: AlertKind;
  severity: AlertSeverity;
  status: AlertStatus;

  tenant_id: string | null;
  tenant_slug: string | null;
  tenant_name: string | null;
  farm_id: string | null;
  farm_name: string | null;

  title: string;
  detail: string | null;
  context: Record<string, unknown>;

  first_seen_at: string;
  last_seen_at: string;
  occurrences: number;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  acknowledged_by_email: string | null;
  resolved_at: string | null;
  resolved_reason: string | null;
}

export interface PlatformAlertPage {
  items: PlatformAlert[];
  total: number;
  limit: number;
  offset: number;
}

export interface PlatformAlertSummary {
  critical: number;
  warning: number;
  open: number;
  acknowledged: number;
  newest_at: string | null;
}

export interface SweepResult {
  tenants_scanned: number;
  tenants_failed: number;
  findings: number;
  resolved: number;
  swept_at: string;
}

export interface PlatformAlertFilters {
  status?: AlertStatusFilter;
  severity?: AlertSeverity;
  category?: AlertCategory;
  tenant_id?: string;
  limit?: number;
  offset?: number;
}

export async function listPlatformAlerts(
  filters: PlatformAlertFilters = {},
): Promise<PlatformAlertPage> {
  const { data } = await apiClient.get<PlatformAlertPage>("/v1/admin/alerts", {
    params: filters,
  });
  return data;
}

export async function getPlatformAlertSummary(): Promise<PlatformAlertSummary> {
  const { data } = await apiClient.get<PlatformAlertSummary>("/v1/admin/alerts/summary");
  return data;
}

export async function acknowledgePlatformAlert(alertId: string): Promise<PlatformAlert> {
  const { data } = await apiClient.post<PlatformAlert>(`/v1/admin/alerts/${alertId}/acknowledge`);
  return data;
}

export async function resolvePlatformAlert(alertId: string): Promise<PlatformAlert> {
  const { data } = await apiClient.post<PlatformAlert>(`/v1/admin/alerts/${alertId}/resolve`);
  return data;
}

export async function runPlatformAlertSweep(): Promise<SweepResult> {
  const { data } = await apiClient.post<SweepResult>("/v1/admin/alerts/sweep");
  return data;
}
