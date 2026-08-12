import { apiClient } from "./client";

// Mirrors backend/app/modules/indices/schemas.py — keep in lock-step.

export type TimeseriesGranularity = "daily" | "weekly";

// ndmi (NIR/SWIR moisture) was added backend-side after the original six
// (migration 0027); bsi + msi came later still from the indices-guide gap
// audit (migration 0056). All three are computed + stored per scene/cell for
// SWIR-bearing products (Sentinel-2).
// NB: SWIR-free products (future PlanetScope 3 m) won't carry ndmi/bsi/msi.
//
// ⚠️ `msi` is the odd one out: it is a plain SWIR1/NIR ratio, so its range is
// roughly [0, 3] rather than [-1, 1], and it reads BACKWARDS (higher = more
// stress). Anything that rescales, clamps or colour-ramps on a [-1, 1]
// "higher is healthier" assumption has to special-case it.
//
// Mirrors backend STANDARD_INDEX_CODES; the pairing is enforced by
// backend/tests/unit/shared/test_index_codes_frontend_parity.py.
export type IndexCode =
  | "ndvi"
  | "ndwi"
  | "evi"
  | "savi"
  | "ndre"
  | "gndvi"
  | "ndmi"
  | "bsi"
  | "msi";

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
