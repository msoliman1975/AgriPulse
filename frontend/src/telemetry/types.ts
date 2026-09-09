import type { TelemetryEventName, TelemetryFeature, TelemetryFlow } from "./taxonomy.generated";

/**
 * One queued event.
 *
 * Note what is absent: `user_id`, `tenant_id`, `actor_role`, `locale`. The
 * client never asserts identity — the server stamps all of it from the
 * validated JWT and silently discards any it finds in the payload. Adding those
 * fields here would not make them land; it would only make the code lie.
 */
export interface TelemetryEvent {
  id: string;
  /** ISO-8601. Clamped server-side to now ± 5 min, so a skewed clock cannot
   *  scatter rows into future chunks. */
  time: string;
  event_name: TelemetryEventName;
  feature?: TelemetryFeature;
  /** Route TEMPLATE ("/insights/:farmId"), never a resolved path. */
  route?: string;
  farm_id?: string;
  flow?: TelemetryFlow;
  step?: string;
  outcome?: "ok" | "error" | "abandoned" | "cancelled";
  duration_ms?: number;
  status_code?: number;
  error_code?: string;
  correlation_id?: string;
  props?: Record<string, string | number | boolean | null>;
}

/** One flush. `dropped` reports ring-buffer overflow so a blind client is
 *  distinguishable from an idle one. */
export interface TelemetryBatch {
  session_id: string;
  app_version?: string;
  device_kind?: "desktop" | "tablet" | "mobile";
  viewport_w?: number;
  dropped: number;
  events: TelemetryEvent[];
}
