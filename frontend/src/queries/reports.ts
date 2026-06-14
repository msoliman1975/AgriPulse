import { useQuery } from "@tanstack/react-query";

import {
  getCropHealthReport,
  getOperationsLogReport,
  getWaterBalanceReport,
  getWeatherSummaryReport,
  getZoneAnomalyReport,
  type CropHealthParams,
  type CropHealthReportResponse,
  type OperationsLogReportResponse,
  type RangeParams,
  type WaterBalanceReportResponse,
  type WeatherSummaryReportResponse,
  type ZoneAnomalyReportResponse,
} from "@/api/reports";

/** Crop-health report for a farm + index over a date range. Keyed on
 * every param so changing the index or range refetches. */
export function useCropHealthReport(
  farmId: string,
  params: CropHealthParams,
): ReturnType<typeof useQuery<CropHealthReportResponse>> {
  return useQuery({
    queryKey: ["reports", "crop-health", farmId, params] as const,
    queryFn: () => getCropHealthReport(farmId, params),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}

/** Field-variability / zone-anomaly report for a farm + index. */
export function useZoneAnomalyReport(
  farmId: string,
  params: CropHealthParams,
): ReturnType<typeof useQuery<ZoneAnomalyReportResponse>> {
  return useQuery({
    queryKey: ["reports", "zone-anomaly", farmId, params] as const,
    queryFn: () => getZoneAnomalyReport(farmId, params),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}

/** Irrigation & water-balance report for a farm over a date range. */
export function useWaterBalanceReport(
  farmId: string,
  params: RangeParams,
): ReturnType<typeof useQuery<WaterBalanceReportResponse>> {
  return useQuery({
    queryKey: ["reports", "water-balance", farmId, params] as const,
    queryFn: () => getWaterBalanceReport(farmId, params),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}

/** Weather & GDD summary report for a farm over a date range. */
export function useWeatherSummaryReport(
  farmId: string,
  params: RangeParams,
): ReturnType<typeof useQuery<WeatherSummaryReportResponse>> {
  return useQuery({
    queryKey: ["reports", "weather-summary", farmId, params] as const,
    queryFn: () => getWeatherSummaryReport(farmId, params),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}

/** Farm operations & agronomy log for a farm over a date range. */
export function useOperationsLogReport(
  farmId: string,
  params: RangeParams,
): ReturnType<typeof useQuery<OperationsLogReportResponse>> {
  return useQuery({
    queryKey: ["reports", "operations-log", farmId, params] as const,
    queryFn: () => getOperationsLogReport(farmId, params),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}
