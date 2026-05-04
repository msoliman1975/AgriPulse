import { apiClient } from "./client";

// Mirrors backend/app/modules/indices/schemas.py — keep in lock-step.

export type TimeseriesGranularity = "daily" | "weekly";

export type IndexCode = "ndvi" | "ndwi" | "evi" | "savi" | "ndre" | "gndvi";

export interface IndexTimeseriesPoint {
  time: string;
  mean: string | null;
  min: string | null;
  max: string | null;
  valid_pixels: number | null;
  valid_pixel_pct: string | null;
}

export interface IndexTimeseriesResponse {
  block_id: string;
  index_code: string;
  granularity: TimeseriesGranularity;
  points: IndexTimeseriesPoint[];
}

export interface GetTimeseriesParams {
  granularity?: TimeseriesGranularity;
  from?: string;
  to?: string;
}

export async function getTimeseries(
  blockId: string,
  indexCode: IndexCode,
  params: GetTimeseriesParams = {},
): Promise<IndexTimeseriesResponse> {
  const { data } = await apiClient.get<IndexTimeseriesResponse>(
    `/v1/blocks/${blockId}/indices/${indexCode}/timeseries`,
    {
      params: {
        granularity: params.granularity ?? "daily",
        from: params.from ?? undefined,
        to: params.to ?? undefined,
      },
    },
  );
  return data;
}
