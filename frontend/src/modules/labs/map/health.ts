// Health-bucket classification — frontend logic since the backend has no
// rolled-up summary endpoint. Conservative: any critical alert wins.

import type { Health, MapSeverity } from "./types";
import type { AlertSeverity } from "@/api/alerts";

export function mapAlertSeverity(s: AlertSeverity): MapSeverity | null {
  if (s === "critical") return "critical";
  if (s === "warning") return "watch";
  return null;
}

export function classifyHealth(args: {
  worstAlertSeverity: MapSeverity | null;
  ndviCurrent: number | null;
}): Health {
  if (args.worstAlertSeverity === "critical") return "critical";
  if (args.worstAlertSeverity === "watch") return "watch";
  if (args.ndviCurrent == null) return "unknown";
  if (args.ndviCurrent < 0.4) return "critical";
  if (args.ndviCurrent < 0.55) return "watch";
  return "healthy";
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
