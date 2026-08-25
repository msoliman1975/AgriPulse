import { useQuery } from "@tanstack/react-query";

import {
  getCropHealthReport,
  getReportCustomFields,
  getSignalDetailsReport,
  getOperationsLogReport,
  getWaterBalanceReport,
  getWeatherRiskPressureReport,
  getWeatherSummaryReport,
  getZoneAnomalyReport,
  type BlockRangeParams,
  type CropHealthParams,
  type CropHealthReportResponse,
  type CustomFieldsResponse,
  type OperationsLogReportResponse,
  type RangeParams,
  type SignalDetailsParams,
  type SignalDetailsReportResponse,
  type WaterBalanceReportResponse,
  type WeatherRiskPressureReportResponse,
  type WeatherSummaryParams,
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
  params: BlockRangeParams,
): ReturnType<typeof useQuery<WaterBalanceReportResponse>> {
  return useQuery({
    queryKey: ["reports", "water-balance", farmId, params] as const,
    queryFn: () => getWaterBalanceReport(farmId, params),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}

/** Disease & pest pressure report for a farm over a date range. */
export function useWeatherRiskPressureReport(
  farmId: string,
  params: BlockRangeParams,
): ReturnType<typeof useQuery<WeatherRiskPressureReportResponse>> {
  return useQuery({
    queryKey: ["reports", "weather-risk-pressure", farmId, params] as const,
    queryFn: () => getWeatherRiskPressureReport(farmId, params),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}

/** Weather & GDD summary report for a farm over a date range. */
export function useWeatherSummaryReport(
  farmId: string,
  params: WeatherSummaryParams,
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

/** The custom columns a farm offers, for the report column picker.

 * Long `staleTime`: crop-attribute definitions are platform-curated and
 * signal definitions change when somebody authors one, so re-fetching this on
 * every report switch would be pure noise. */
export function useReportCustomFields(
  farmId: string,
): ReturnType<typeof useQuery<CustomFieldsResponse>> {
  return useQuery({
    queryKey: ["reports", "custom-fields", farmId] as const,
    queryFn: () => getReportCustomFields(farmId),
    enabled: Boolean(farmId),
    staleTime: 10 * 60_000,
  });
}

/** Signal-details report for a farm — every observation matching the filters. */
export function useSignalDetailsReport(
  farmId: string,
  params: SignalDetailsParams,
): ReturnType<typeof useQuery<SignalDetailsReportResponse>> {
  return useQuery({
    queryKey: ["reports", "signal-details", farmId, params] as const,
    queryFn: () => getSignalDetailsReport(farmId, params),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}
