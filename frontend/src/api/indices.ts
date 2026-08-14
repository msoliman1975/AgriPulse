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
// A runtime array with the type derived from it, rather than a bare union.
// Four other modules used to keep their own hardcoded copy of this list for
// their pickers, and all four were still on the original six — which is why
// `ndmi` was uncheckable in insights and both reports for a year after the
// backend started computing it. They now import this.
export const INDEX_CODES = [
  "ndvi",
  "ndwi",
  "evi",
  "savi",
  "ndre",
  "gndvi",
  "ndmi",
  "bsi",
  "msi",
] as const;

export type IndexCode = (typeof INDEX_CODES)[number];

// The THERMAL indices, from a different product (`landsat_c2_l2_st`,
// Landsat 8/9 surface temperature) with a disjoint band set. Kept in
// their own list rather than folded into INDEX_CODES above, because a
// farm can carry the optical product alone — most do — and offering
// these where no thermal scene exists yields a picker entry with
// nothing behind it.
//
// ⚠️ `lst` is degrees Celsius, the only index in either list with a
// UNIT. Its catalog bounds are a temperature range (0-60), not the
// [-1, 1] the normalized differences share, so anything that rescales
// or colour-ramps on that assumption is wrong for it. Read the unit
// from `getIndexCatalog()`, and format via `@/lib/indexFormat`.
//
// ⚠️ Thermal is 100 m native resampled to a 30 m grid — a FARM-scale
// signal. Do not present a block value at the same visual confidence
// as a 10 m optical index.
//
// Mirrors backend THERMAL_INDEX_CODES; the pairing is enforced by
// backend/tests/unit/shared/test_index_codes_frontend_parity.py.
export const THERMAL_INDEX_CODES = ["lst", "cwsi", "smi"] as const;

export type ThermalIndexCode = (typeof THERMAL_INDEX_CODES)[number];

/** Every index code either product can produce. */
export type AnyIndexCode = IndexCode | ThermalIndexCode;

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

// --- Catalog ---------------------------------------------------------------

/**
 * One row of `public.indices_catalog`, from `GET /v1/indices/catalog`.
 *
 * Mirrors backend/app/modules/indices/schemas.py::IndexCatalogEntry.
 *
 * Read this rather than hardcoding index metadata. A hardcoded copy is
 * how `msi`'s [0, 3] range and `ndmi`'s existence both went missing from
 * pickers that had drifted from the backend.
 */
export interface IndexCatalogEntry {
  id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  formula_text: string;
  // Decimal-as-string, like every other NUMERIC the API returns.
  value_min: string;
  value_max: string;
  /**
   * Display symbol, empty for the dimensionless majority.
   *
   * `lst` is degrees Celsius; everything else is a ratio. A formatter
   * that assumes one shape cannot be right for both — see
   * `@/lib/indexFormat`.
   */
  unit: string;
  physical_meaning: string | null;
  is_standard: boolean;
}

export async function getIndexCatalog(): Promise<IndexCatalogEntry[]> {
  const { data } = await apiClient.get<IndexCatalogEntry[]>("/v1/indices/catalog");
  return data;
}
