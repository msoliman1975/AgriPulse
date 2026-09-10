import { apiClient } from "./client";

/**
 * The usage dashboard's read API (TEL-7).
 *
 * One request returns the whole page. The alternative — a query per section —
 * would make seven round trips that each re-scan the same window, and would
 * let the sections disagree with each other while they land one by one.
 */

export interface UsageFilters {
  start: string;
  end: string;
  tenant_id: string | null;
  user_id: string | null;
  include_staff: boolean;
}

export interface EngagementKpis {
  dau: number;
  wau: number;
  mau: number;
  /** DAU ÷ WAU. Computed server-side so every surface reads the same number. */
  stickiness: number;
  median_session_seconds: number;
  sessions: number;
  sessions_per_user: number;
}

export interface DailyPoint {
  day: string;
  events: number;
  users: number;
}

export interface RouteDwell {
  route: string;
  total_ms: number;
  visits: number;
  median_ms: number;
}

export interface FeatureAdoption {
  feature: string;
  events: number;
  users: number;
  tenants: number;
  last_used: string | null;
}

export interface FlowFunnel {
  flow: string;
  entries: number;
  completions: number;
  abandoned: number;
  /** null means they left before any step — they bounced at entry. */
  died_at: string | null;
}

export interface FlowStep {
  flow: string;
  step: string;
  sessions: number;
}

export interface ErrorDenseRoute {
  route: string;
  views: number;
  errors: number;
  error_rate: number;
}

export interface RecentError {
  time: string;
  route: string | null;
  status_code: number | null;
  error_code: string | null;
  /** Joins straight to the server log line and the trace. */
  correlation_id: string | null;
  method: string | null;
}

export interface RetryStorm {
  feature: string | null;
  action: string | null;
  storms: number;
  users: number;
}

export interface SlowAction {
  feature: string;
  p95_ms: number;
  samples: number;
}

export interface TenantHealth {
  tenant_id: string;
  /** Slug, then name, then a short id — joined server-side, since the
   *  telemetry store deliberately holds no names. */
  label: string;
  last_seen: string | null;
  wau: number;
  features_used: number;
  events: number;
}

export interface UsageOverview {
  filters: UsageFilters;
  kpis: EngagementKpis;
  daily: DailyPoint[];
  routes: RouteDwell[];
  features: FeatureAdoption[];
  cold_features: string[];
  funnels: FlowFunnel[];
  funnel_steps: FlowStep[];
  error_routes: ErrorDenseRoute[];
  recent_errors: RecentError[];
  retry_storms: RetryStorm[];
  slow_actions: SlowAction[];
  tenants: TenantHealth[];
}

export interface UsageQuery {
  start: string;
  end: string;
  tenantId?: string | null;
  userId?: string | null;
  includeStaff?: boolean;
}

export interface TenantOption {
  tenant_id: string;
  label: string;
  events: number;
}

export interface UserOption {
  user_id: string;
  label: string;
  actor_role: string | null;
  events: number;
}

export interface UsageFilterOptions {
  tenants: TenantOption[];
  users: UserOption[];
}

/**
 * What the pickers may offer, derived from the events in the window.
 *
 * Deliberately a separate request from the overview: the lists change far more
 * slowly than the numbers, so they cache on their own instead of being
 * re-fetched every time the date range moves.
 */
export async function getUsageFilterOptions(query: {
  start: string;
  end: string;
  tenantId?: string | null;
  includeStaff?: boolean;
}): Promise<UsageFilterOptions> {
  const { data } = await apiClient.get<UsageFilterOptions>("/v1/platform/usage/filters", {
    params: {
      start: query.start,
      end: query.end,
      tenant_id: query.tenantId || undefined,
      include_staff: query.includeStaff ?? false,
    },
  });
  return data;
}

export async function getUsageOverview(query: UsageQuery): Promise<UsageOverview> {
  const { data } = await apiClient.get<UsageOverview>("/v1/platform/usage/overview", {
    params: {
      start: query.start,
      end: query.end,
      tenant_id: query.tenantId || undefined,
      user_id: query.userId || undefined,
      include_staff: query.includeStaff ?? false,
    },
  });
  return data;
}
