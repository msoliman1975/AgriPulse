// GENERATED FILE — do not edit by hand.
//
// Source: backend/app/modules/telemetry/taxonomy.yaml
// Regenerate: python backend/scripts/gen_telemetry_taxonomy.py
//
// The server validates every event against the same YAML and rejects anything
// not named there, so editing this file alone changes nothing except which
// calls the compiler lets you write. Edit the YAML and re-run the script.

export const TAXONOMY_VERSION = 1;

export type TelemetryEventName =
  | "api_error"
  | "client_error"
  | "feature_used"
  | "flow_complete"
  | "flow_start"
  | "flow_step"
  | "page_leave"
  | "page_view"
  | "session_end"
  | "session_start";

export type TelemetryFeature =
  | "alerts"
  | "backfill_console"
  | "block_create"
  | "block_defaults"
  | "board"
  | "bulk_aoi_upload"
  | "decision_tree_authoring"
  | "decision_tree_dryrun"
  | "farm_console"
  | "farm_create"
  | "grid_config"
  | "imagery_config"
  | "index_chart"
  | "insights"
  | "plan_template"
  | "platform_admin"
  | "recommendations"
  | "report_export"
  | "reports"
  | "settings"
  | "signals"
  | "users_admin"
  | "weather_chart"
  | "weather_config";

export type TelemetryFlow =
  | "backfill_run"
  | "block_bulk_upload"
  | "decision_tree_authoring"
  | "farm_onboarding";

/** Props keys the server keeps per event. Anything else is dropped on ingest. */
export const ALLOWED_PROPS: Record<TelemetryEventName, readonly string[]> = {
  api_error: ["method", "problem_type", "retry_count"],
  client_error: ["component", "digest"],
  feature_used: ["action", "index_code", "count", "source"],
  flow_complete: ["steps_taken"],
  flow_start: ["entry_point"],
  flow_step: ["attempt"],
  page_leave: ["hidden_ms"],
  page_view: [],
  session_end: [],
  session_start: [],
} as const;

export const FEATURES: readonly TelemetryFeature[] = [
  "alerts",
  "backfill_console",
  "block_create",
  "block_defaults",
  "board",
  "bulk_aoi_upload",
  "decision_tree_authoring",
  "decision_tree_dryrun",
  "farm_console",
  "farm_create",
  "grid_config",
  "imagery_config",
  "index_chart",
  "insights",
  "plan_template",
  "platform_admin",
  "recommendations",
  "report_export",
  "reports",
  "settings",
  "signals",
  "users_admin",
  "weather_chart",
  "weather_config",
] as const;

/** `timeoutMinutes` is what the server-side abandonment query uses; the client
 * never enforces it, because the case we care about is the user who left. */
export const FLOWS: Record<TelemetryFlow, { timeoutMinutes: number; steps: readonly string[] }> = {
  backfill_run: { timeoutMinutes: 30, steps: ["select_farm", "select_range", "preview", "submit"] },
  block_bulk_upload: { timeoutMinutes: 30, steps: ["pick_files", "map_columns", "reconcile", "commit"] },
  decision_tree_authoring: { timeoutMinutes: 120, steps: ["open", "edit", "dry_run", "publish"] },
  farm_onboarding: { timeoutMinutes: 60, steps: ["draw_or_upload", "details", "blocks", "subscriptions"] },
} as const;

export type TelemetryFlowStep<F extends TelemetryFlow = TelemetryFlow> =
  (typeof FLOWS)[F]["steps"][number];
