// Composition layer for the map-first prototype.
//
// Summary load uses the dedicated /v1/farms/:id/blocks/summary endpoint.
// Detail load (panel content) still fans out across per-block endpoints
// because the panel is opened on click and the latency is hidden by the
// react-query loading state.

import type { Feature, FeatureCollection, Polygon } from "geojson";

import { getBlock, listBlocks, type Block, type BlockDetail } from "@/api/blocks";
import { getBlocksSummary } from "@/api/blocksSummary";
import { listBlockCrops, type BlockCropAssignment } from "@/api/cropAssignments";
import { listCrops, listCropVarieties, type Crop, type CropVariety } from "@/api/crops";
import { getFarm, type FarmDetail } from "@/api/farms";
import { getTimeseries, type IndexCode as ApiIndexCode } from "@/api/indices";
import { listAlerts } from "@/api/alerts";
import {
  listBlockHealth,
  type BlockIntegrationHealth,
} from "@/api/integrationsHealth";
import { listIrrigationSchedules, type IrrigationSchedule } from "@/api/irrigation";
import { listCalendar, listPlans, type Plan } from "@/api/plans";
import { listRecommendations, type Recommendation } from "@/api/recommendations";
import { listSignalObservations, type SignalObservation } from "@/api/signals";
import { getForecast, type ForecastResponse } from "@/api/weather";

import { classifyHealth, mapAlertSeverity } from "./health";
import type {
  IndexCode,
  IndexSeries,
  UnitAlert,
  UnitDetail,
  UnitFeatureProps,
  UnitSummary,
} from "./types";

function num(s: string | null | undefined): number | null {
  if (s == null || s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function trend(series: { time: string; value: number | null }[]): number | null {
  // Last point - point at most 7d before. Skip nulls.
  const valid = series.filter((p) => p.value != null);
  if (valid.length < 2) return null;
  const last = valid[valid.length - 1]!;
  const lastTime = new Date(last.time).getTime();
  const cutoff = lastTime - 7 * 24 * 3600 * 1000;
  const prior = [...valid].reverse().find((p) => new Date(p.time).getTime() <= cutoff);
  const base = prior ?? valid[0]!;
  return (last.value as number) - (base.value as number);
}

function asoIndexSeries(points: { time: string; mean: string | null }[]): IndexSeries {
  const series_30d = points.map((p) => ({ time: p.time, value: num(p.mean) }));
  const valid = series_30d.filter((p) => p.value != null);
  const current = valid.length > 0 ? (valid[valid.length - 1]!.value as number) : null;
  return { current, trend_7d_delta: trend(series_30d), series_30d };
}

function isoNDays(n: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - n * 24 * 3600 * 1000);
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

function blockShortName(b: Block): string {
  return b.name?.trim() || b.code;
}

function specUnitType(b: Block): "block" | "pivot" | "pivot_section" {
  if (b.unit_type === "pivot_sector") return "pivot_section";
  return b.unit_type;
}

// ----- summary load --------------------------------------------------------

export interface MapSummary {
  farm: FarmDetail;
  blocks: Block[];
  geojson: FeatureCollection<Polygon, UnitFeatureProps>;
  summaries: Record<string, UnitSummary>;
  // Active season plan for the farm (status === "active"), if any.
  activePlan: Plan | null;
  // Per-block integration health indexed by block_id. Empty map if the
  // health endpoint is unavailable.
  blockHealth: Record<string, BlockIntegrationHealth>;
}

export async function loadMapSummary(farmId: string): Promise<MapSummary> {
  // Parallel summary fan-out. Farm + blocks + summary + (best-effort)
  // active plan + (best-effort) block health.
  const [farm, blocksPage, summaryResp, plans, healthRows] = await Promise.all([
    getFarm(farmId),
    listBlocks(farmId, { limit: 200 }),
    getBlocksSummary(farmId),
    safePlans(farmId),
    safeBlockHealth(farmId),
  ]);
  const blocks = blocksPage.items;
  const activePlan = plans.find((p) => p.status === "active") ?? null;
  const blockHealth: Record<string, BlockIntegrationHealth> = {};
  for (const h of healthRows) blockHealth[h.block_id] = h;

  const summaryByBlock = new Map(summaryResp.units.map((u) => [u.id, u]));

  // Per-block boundary fetch — N parallel calls, the only fan-out left.
  const details = await Promise.all(blocks.map((b) => getBlock(b.id)));
  const detailById = new Map<string, BlockDetail>(details.map((d) => [d.id, d]));

  const summaries: Record<string, UnitSummary> = {};
  const features: Feature<Polygon, UnitFeatureProps>[] = [];

  // Identify pivots that have sectors → mark them as logical groups.
  const pivotChildren = new Map<string, string[]>();
  for (const b of blocks) {
    if (b.unit_type === "pivot_sector" && b.parent_unit_id) {
      const arr = pivotChildren.get(b.parent_unit_id) ?? [];
      arr.push(b.id);
      pivotChildren.set(b.parent_unit_id, arr);
    }
  }

  for (const b of blocks) {
    const detail = detailById.get(b.id);
    if (!detail) continue;
    const isLogicalPivot =
      b.unit_type === "pivot" && (pivotChildren.get(b.id)?.length ?? 0) > 0;

    const apiSummary = summaryByBlock.get(b.id);
    const summary: UnitSummary = {
      id: b.id,
      health: isLogicalPivot ? "unknown" : (apiSummary?.health ?? "unknown"),
      has_alert: !isLogicalPivot && (apiSummary?.alert_count ?? 0) > 0,
      alert_severity: isLogicalPivot ? null : (apiSummary?.alert_severity ?? null),
      alert_count: isLogicalPivot ? 0 : (apiSummary?.alert_count ?? 0),
      ndvi_current: apiSummary?.ndvi_current ?? null,
      ndre_current: apiSummary?.ndre_current ?? null,
      ndwi_current: apiSummary?.ndwi_current ?? null,
    };
    if (!isLogicalPivot) summaries[b.id] = summary;

    const today = new Date().toISOString().slice(0, 10);
    const isFuture = Boolean(b.active_from && b.active_from > today);
    features.push({
      type: "Feature",
      id: b.id,
      geometry: detail.boundary,
      properties: {
        id: b.id,
        type: isLogicalPivot ? "pivot_logical_group" : specUnitType(b),
        parent_pivot_id: b.parent_unit_id,
        is_logical_pivot: isLogicalPivot,
        name: blockShortName(b),
        health: summary.health,
        has_alert: summary.has_alert,
        alert_severity: summary.alert_severity ?? "none",
        is_future: isFuture,
      },
    });
  }

  return {
    farm,
    blocks,
    geojson: { type: "FeatureCollection", features },
    summaries,
    activePlan,
    blockHealth,
  };
}

// ----- detail load ---------------------------------------------------------

const detailCache = new Map<string, { at: number; value: UnitDetail }>();
const DETAIL_TTL_MS = 30_000;

export async function loadUnitDetail(args: {
  farmId: string;
  blockId: string;
  blocksById: Map<string, Block>;
  activePlan?: Plan | null;
  blockHealth?: BlockIntegrationHealth | null;
}): Promise<UnitDetail> {
  const cached = detailCache.get(args.blockId);
  if (cached && Date.now() - cached.at < DETAIL_TTL_MS) return cached.value;

  const block = args.blocksById.get(args.blockId);
  if (!block) throw new Error(`Block ${args.blockId} not in farm`);

  const { from, to } = isoNDays(30);
  const sinceObs = new Date(Date.now() - 30 * 86_400_000).toISOString();

  const [
    blockDetail,
    indicesNdvi,
    indicesNdre,
    indicesNdwi,
    blockAlerts,
    irrigation,
    recs,
    weather,
    calendar,
    cropAssignments,
    signalObs,
  ] = await Promise.all([
    getBlock(args.blockId),
    safeTimeseries(args.blockId, "ndvi", from, to),
    safeTimeseries(args.blockId, "ndre", from, to),
    safeTimeseries(args.blockId, "ndwi", from, to),
    listAlerts({ block_id: args.blockId, status: "open", limit: 50 }),
    safeIrrigation(args.farmId, args.blockId),
    safeRecommendations(args.blockId),
    safeForecast(args.blockId),
    safeCalendar(args.farmId, from, to),
    safeBlockCrops(args.blockId),
    safeSignalObs(args.blockId, sinceObs),
  ]);

  const indexBundle: Record<IndexCode, IndexSeries> = {
    ndvi: asoIndexSeries(indicesNdvi),
    ndre: asoIndexSeries(indicesNdre),
    ndwi: asoIndexSeries(indicesNdwi),
  };

  const ndviCur = indexBundle.ndvi.current;
  const worstAlert = blockAlerts.reduce<UnitAlert | null>((acc, a) => {
    const sev = mapAlertSeverity(a.severity);
    if (!sev) return acc;
    const ua: UnitAlert = {
      id: a.id,
      severity: sev,
      code: a.rule_code,
      message: a.diagnosis_en ?? a.prescription_en ?? a.rule_code,
      raised_at: a.created_at,
    };
    if (sev === "critical") return ua;
    if (sev === "watch" && (!acc || acc.severity !== "critical")) return ua;
    return acc;
  }, null);

  const sortedSchedules = irrigation
    .filter((s) => s.block_id === args.blockId)
    .sort((a, b) => a.scheduled_for.localeCompare(b.scheduled_for));
  const today = new Date().toISOString().slice(0, 10);
  const last = [...sortedSchedules]
    .reverse()
    .find((s) => s.status === "applied");
  const next = sortedSchedules.find(
    (s) => s.status === "pending" && s.scheduled_for >= today,
  );

  const todayStr = new Date().toISOString().slice(0, 10);
  const next7dCutoff = new Date(Date.now() + 7 * 86_400_000)
    .toISOString()
    .slice(0, 10);
  const acts = (calendar?.activities ?? [])
    .filter((a) => a.block_id === args.blockId)
    .sort((a, b) => a.scheduled_date.localeCompare(b.scheduled_date))
    .slice(0, 12)
    .map((a) => ({
      date: a.scheduled_date,
      label:
        a.activity_type.charAt(0).toUpperCase() +
        a.activity_type.slice(1).replace(/_/g, " "),
      phase:
        a.scheduled_date >= todayStr && a.scheduled_date <= next7dCutoff
          ? ("next7d" as const)
          : ("later" as const),
    }));

  const weatherDays = (weather?.days ?? [])
    .slice(0, 3)
    .map((d, i) => ({
      day: i === 0 ? "Today" : new Date(d.date).toLocaleDateString("en-US", { weekday: "short" }),
      temp_c_max: num(d.high_c),
    }));

  const currentCrop = cropAssignments.find((c) => c.is_current) ?? null;
  const cropAssignmentSummary = await resolveCropAssignment(currentCrop);
  const signals = condenseSignals(signalObs);

  const detail: UnitDetail = {
    id: block.id,
    name: blockShortName(block),
    type: specUnitType(block),
    parent_pivot_id: block.parent_unit_id,
    crop: null, // backend has crop_assignments — out of prototype scope
    area_ha: block.area_m2 / 10_000,
    health: classifyHealth({
      worstAlertSeverity: worstAlert?.severity ?? null,
      ndviCurrent: ndviCur,
    }),
    last_updated: blockDetail.updated_at,
    alerts: blockAlerts
      .map((a) => {
        const sev = mapAlertSeverity(a.severity);
        if (!sev) return null;
        return {
          id: a.id,
          severity: sev,
          code: a.rule_code,
          message: a.diagnosis_en ?? a.prescription_en ?? a.rule_code,
          raised_at: a.created_at,
        };
      })
      .filter((x): x is UnitAlert => x !== null),
    indices: indexBundle,
    irrigation: {
      last: last
        ? {
            date: last.scheduled_for,
            volume_mm: Number(last.applied_volume_mm ?? last.recommended_mm) || 0,
          }
        : null,
      next: next
        ? {
            date: next.scheduled_for,
            volume_mm: Number(next.recommended_mm) || 0,
            is_emergency: next.scheduled_for === today,
          }
        : null,
      soil_moisture_pct: num(next?.soil_moisture_pct ?? last?.soil_moisture_pct ?? null),
      soil_status: classifySoil(num(next?.soil_moisture_pct ?? last?.soil_moisture_pct ?? null)),
    },
    recommendations: recs.map((r) => r.text_en).slice(0, 5),
    activities: acts,
    weather_3d: weatherDays,
    plan: args.activePlan
      ? {
          season_label: args.activePlan.season_label,
          season_year: args.activePlan.season_year,
          name: args.activePlan.name,
          status: args.activePlan.status,
        }
      : null,
    crop_assignment: cropAssignmentSummary,
    signals,
    integration: args.blockHealth
      ? {
          weather: {
            active_subs: args.blockHealth.weather_active_subs,
            last_sync_at: args.blockHealth.weather_last_sync_at,
            last_failed_at: args.blockHealth.weather_last_failed_at,
            failed_24h: args.blockHealth.weather_failed_24h,
            running_count: args.blockHealth.weather_running_count,
            overdue_count: args.blockHealth.weather_overdue_count,
          },
          imagery: {
            active_subs: args.blockHealth.imagery_active_subs,
            last_sync_at: args.blockHealth.imagery_last_sync_at,
            last_failed_at: null,
            failed_24h: args.blockHealth.imagery_failed_24h,
            running_count: args.blockHealth.imagery_running_count,
            overdue_count: args.blockHealth.imagery_overdue_count,
          },
        }
      : null,
  };

  detailCache.set(args.blockId, { at: Date.now(), value: detail });
  return detail;
}

function classifySoil(pct: number | null): "optimal" | "low" | "critical" | "unknown" {
  if (pct == null) return "unknown";
  if (pct < 15) return "critical";
  if (pct < 25) return "low";
  return "optimal";
}

async function safeTimeseries(
  blockId: string,
  code: ApiIndexCode,
  from: string,
  to: string,
) {
  try {
    const ts = await getTimeseries(blockId, code, { granularity: "daily", from, to });
    return ts.points;
  } catch {
    return [];
  }
}
async function safeIrrigation(farmId: string, blockId: string): Promise<IrrigationSchedule[]> {
  try {
    return await listIrrigationSchedules(farmId, {});
  } catch {
    return [];
  }
}
async function safeRecommendations(blockId: string): Promise<Recommendation[]> {
  try {
    return await listRecommendations({ block_id: blockId, state: "open", limit: 10 });
  } catch {
    return [];
  }
}
async function safeForecast(blockId: string): Promise<ForecastResponse | null> {
  try {
    return await getForecast(blockId, { horizon_days: 3 });
  } catch {
    return null;
  }
}
async function safeCalendar(farmId: string, from: string, to: string) {
  try {
    return await listCalendar(farmId, from, to);
  } catch {
    return null;
  }
}
async function safePlans(farmId: string): Promise<Plan[]> {
  try {
    return await listPlans(farmId, {});
  } catch {
    return [];
  }
}
async function safeBlockHealth(farmId: string): Promise<BlockIntegrationHealth[]> {
  try {
    return await listBlockHealth(farmId);
  } catch {
    return [];
  }
}
async function safeBlockCrops(blockId: string): Promise<BlockCropAssignment[]> {
  try {
    return await listBlockCrops(blockId);
  } catch {
    return [];
  }
}
async function safeSignalObs(
  blockId: string,
  since: string,
): Promise<SignalObservation[]> {
  try {
    return await listSignalObservations({ block_id: blockId, since, limit: 50 });
  } catch {
    return [];
  }
}

// Tiny in-memory crop name cache so repeated block selections don't refetch
// the same /v1/crops rows.
const cropCache = new Map<string, Crop>();
const varietyCache = new Map<string, CropVariety>();

async function resolveCropAssignment(
  c: BlockCropAssignment | null,
): Promise<UnitDetail["crop_assignment"]> {
  if (!c) return null;
  let cropName = "—";
  let varietyName: string | null = null;
  const cached = cropCache.get(c.crop_id);
  if (cached) cropName = cached.name_en;
  else {
    try {
      const crops = await listCrops();
      for (const crop of crops) cropCache.set(crop.id, crop);
      cropName = cropCache.get(c.crop_id)?.name_en ?? "—";
    } catch {
      // fall through with placeholder
    }
  }
  if (c.crop_variety_id) {
    const v = varietyCache.get(c.crop_variety_id);
    if (v) varietyName = v.name_en;
    else {
      try {
        const vs = await listCropVarieties(c.crop_id);
        for (const variety of vs) varietyCache.set(variety.id, variety);
        varietyName = varietyCache.get(c.crop_variety_id)?.name_en ?? null;
      } catch {
        varietyName = null;
      }
    }
  }
  return {
    crop_name: cropName,
    variety_name: varietyName,
    season_label: c.season_label,
    planting_date: c.planting_date,
    growth_stage: c.growth_stage,
    status: c.status,
  };
}

function condenseSignals(obs: SignalObservation[]): UnitDetail["signals"] {
  // Keep only the most recent observation per signal_code.
  const byCode = new Map<string, SignalObservation>();
  for (const o of obs) {
    const prev = byCode.get(o.signal_code);
    if (!prev || o.time > prev.time) byCode.set(o.signal_code, o);
  }
  return Array.from(byCode.values())
    .sort((a, b) => b.time.localeCompare(a.time))
    .slice(0, 8)
    .map((o) => ({
      code: o.signal_code,
      value: formatSignalValue(o),
      unit: null,
      recorded_at: o.time,
    }));
}

function formatSignalValue(o: SignalObservation): string {
  if (o.value_numeric != null) return o.value_numeric;
  if (o.value_categorical != null) return o.value_categorical;
  if (o.value_event != null) return o.value_event;
  if (o.value_boolean != null) return o.value_boolean ? "yes" : "no";
  if (o.value_geopoint != null) {
    return `${o.value_geopoint.latitude.toFixed(4)}, ${o.value_geopoint.longitude.toFixed(4)}`;
  }
  return "—";
}

export function clearDetailCache(): void {
  detailCache.clear();
}
