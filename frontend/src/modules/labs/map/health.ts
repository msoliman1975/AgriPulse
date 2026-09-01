// Health vocabulary and palette. The CLASSIFICATION is not here.
//
// It used to be: this file carried its own copy of the rule, and so did
// `app/shared/health.py` and `farms/blocks_summary_router.py`. The map
// polygons already coloured from the server's `health` field while the
// block dock re-derived its own from a different NDVI window, so one page
// could show two answers for one block. The rule now lives once, in
// `backend/app/shared/health.py`, and reaches the frontend as the `health`
// field on GET /farms/{id}/blocks/summary.
//
// `mapAlertSeverity` stays: it is not the health rule, it is how an alert
// row's severity is narrowed for the alert list the dock renders.

import type { Health, MapSeverity } from "./types";
import type { AlertSeverity } from "@/api/alerts";

export function mapAlertSeverity(s: AlertSeverity): MapSeverity | null {
  if (s === "critical") return "critical";
  if (s === "warning") return "watch";
  return null;
}

export const HEALTH_FILL: Record<Health, string> = {
  healthy: "#97C459",
  watch: "#EF9F27",
  critical: "#E24B4A",
  unknown: "#9C9C9C",
};

export const HEALTH_STROKE: Record<Health, string> = {
  healthy: "#3B6D11",
  watch: "#854F0B",
  critical: "#A32D2D",
  unknown: "#5F5E5A",
};

export const HEALTH_FILL_OPACITY: Record<Health, number> = {
  healthy: 0.7,
  watch: 0.7,
  critical: 0.6,
  unknown: 0.5,
};
