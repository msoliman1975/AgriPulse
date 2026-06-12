import type { ComponentType } from "react";

import type { Capability } from "@/rbac/capabilities";

import { CropHealthReport } from "./components/CropHealthReport";
import { OperationsLogReport } from "./components/OperationsLogReport";
import { WaterBalanceReport } from "./components/WaterBalanceReport";
import { WeatherSummaryReport } from "./components/WeatherSummaryReport";
import { ZoneAnomalyReport } from "./components/ZoneAnomalyReport";

/** Props every report component receives from the ReportsPage. The
 * period bounds are ISO timestamps already resolved to the active
 * range; the report passes them straight to its query. */
export interface ReportProps {
  farmId: string;
  since: string;
  until: string;
}

export interface ReportDef {
  /** URL-safe id; also the i18n key suffix under `reports.catalog.*`. */
  id: string;
  /** FE capability gate. The backend re-checks on its own endpoint —
   * this only decides whether the report shows in the selector. */
  capability: Capability;
  Component: ComponentType<ReportProps>;
}

/**
 * The report catalog. Each PR appends its entry here as it ships its
 * endpoint + component; the ReportsPage maps over this list
 * (capability-filtered) to build the selector. Array order is display
 * order. Empty until PR-1 lands the first report.
 */
export const REPORTS: readonly ReportDef[] = [
  { id: "crop-health", capability: "index.read", Component: CropHealthReport },
  { id: "zone-anomaly", capability: "index.read", Component: ZoneAnomalyReport },
  {
    id: "water-balance",
    capability: "irrigation.schedule.read",
    Component: WaterBalanceReport,
  },
  { id: "weather-summary", capability: "weather.read", Component: WeatherSummaryReport },
  { id: "operations-log", capability: "plan.read", Component: OperationsLogReport },
];
