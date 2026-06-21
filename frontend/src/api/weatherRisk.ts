import { apiClient } from "./client";

// Mirrors backend/app/modules/weather/schemas.py (weather-risk surface,
// PR-R2). Per-block disease/pest risk scores: `score` is an integer 0-100
// (not a Decimal string), `level` its low|moderate|high banding.

export type RiskLevel = "low" | "moderate" | "high";

// The mango V1 pathogen/pest codes (weather.risk registry).
export const WEATHER_RISK_CODES = ["powdery_mildew", "anthracnose", "fruit_fly"] as const;
export type WeatherRiskCode = (typeof WEATHER_RISK_CODES)[number];

// --- Per-farm summary (latest score per block per pathogen) ----------------

export interface WeatherRiskSummaryEntry {
  block_id: string;
  risk_code: string;
  date: string;
  score: number;
  level: RiskLevel;
}

export interface WeatherRiskSummaryResponse {
  farm_id: string;
  as_of: string;
  risks: WeatherRiskSummaryEntry[];
}

export async function getWeatherRiskSummary(farmId: string): Promise<WeatherRiskSummaryResponse> {
  const { data } = await apiClient.get<WeatherRiskSummaryResponse>(
    `/v1/farms/${farmId}/weather-risk/summary`,
  );
  return data;
}

// --- Per-block daily timeseries for one pathogen ---------------------------

export interface WeatherRiskPoint {
  date: string;
  risk_code: string;
  score: number;
  level: RiskLevel;
  // The favourable-condition accumulation that produced the score (the "why").
  inputs: Record<string, string>;
}

export interface WeatherRiskTimeseriesResponse {
  farm_id: string;
  block_id: string;
  risk_code: string;
  points: WeatherRiskPoint[];
}

export interface GetWeatherRiskTimeseriesParams {
  /** Inclusive lower bound, YYYY-MM-DD. */
  from?: string;
  /** Exclusive upper bound, YYYY-MM-DD. */
  to?: string;
}

export async function getWeatherRiskTimeseries(
  farmId: string,
  blockId: string,
  riskCode: string,
  params: GetWeatherRiskTimeseriesParams = {},
): Promise<WeatherRiskTimeseriesResponse> {
  const { data } = await apiClient.get<WeatherRiskTimeseriesResponse>(
    `/v1/farms/${farmId}/blocks/${blockId}/weather-risk/${riskCode}/timeseries`,
    { params: { from: params.from ?? undefined, to: params.to ?? undefined } },
  );
  return data;
}

// --- Helpers ---------------------------------------------------------------

const _LEVEL_RANK: Record<RiskLevel, number> = { low: 0, moderate: 1, high: 2 };

/** Reduce the summary to the worst risk level per block (for the map fill). */
export function worstLevelPerBlock(
  risks: readonly WeatherRiskSummaryEntry[],
): Map<string, RiskLevel> {
  const worst = new Map<string, RiskLevel>();
  for (const r of risks) {
    const cur = worst.get(r.block_id);
    if (cur === undefined || _LEVEL_RANK[r.level] > _LEVEL_RANK[cur]) {
      worst.set(r.block_id, r.level);
    }
  }
  return worst;
}
