/**
 * The investor API, /api/v1/investor/*. Every route reads the caller's own
 * rows; the app never sends an investor id.
 */
import { Preferences } from "@capacitor/preferences";

import { validAccessToken } from "@/auth/session";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export interface Me {
  code: string;
  full_name: string;
  full_name_ar: string | null;
  preferred_language: "ar" | "en";
  company_name: string | null;
  /** Absent from apis before investor app v2 (PR 2). */
  status?: "not_invited" | "invited" | "active" | "suspended" | "archived";
  investor_type?: "person" | "company";
  email?: string;
  phone?: string | null;
}

export interface Geometry {
  type: string;
  coordinates: unknown;
}

/** One stage of the crop's season, dated for this season when it can be. */
export interface Stage {
  code: string;
  name_en: string | null;
  name_ar: string | null;
  expected_start: string | null;
  expected_end: string | null;
}

export type AcquiredBy = "purchase" | "transfer" | "inheritance" | "other";

export interface Holding {
  holding_id: string;
  code: string;
  name: string;
  name_ar: string | null;
  farm_name: string | null;
  farm_name_ar: string | null;
  block_code: string | null;
  block_name: string | null;
  block_name_ar: string | null;
  area_m2: string;
  tree_count: number | null;
  crop_name_en: string | null;
  crop_name_ar: string | null;
  variety_name_en: string | null;
  variety_name_ar: string | null;
  planting_date: string | null;
  /** 256 px and 64 px crop pictures (public URLs); absent from older apis. */
  crop_image_url?: string | null;
  crop_icon_url?: string | null;
  stage_code?: string | null;
  stage_name_en: string | null;
  stage_name_ar: string | null;
  stage_started_on: string | null;
  stage_expected_end: string | null;
  stages?: Stage[];
  expected_harvest_on?: string | null;
  current_season: string | null;
  start_date: string;
  end_date: string | null;
  period: "past" | "current" | "future";
  acquired_by?: AcquiredBy;
  contract_ref?: string | null;
  boundary: Geometry;
  block_boundary: Geometry;
}

export interface AppVersion {
  min_version: string;
  latest_version: string;
  download_url: string | null;
}

async function get<T>(path: string): Promise<T> {
  const token = await validAccessToken();
  if (!token) throw new ApiError(401, "signed out");
  const resp = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!resp.ok) {
    const problem = (await resp.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(resp.status, problem?.detail ?? `request failed (${resp.status})`);
  }
  return (await resp.json()) as T;
}

export const fetchMe = (): Promise<Me> => get<Me>("/investor/me");
export const fetchHoldings = (): Promise<Holding[]> => get<Holding[]>("/investor/holdings");
export const fetchAppVersion = (): Promise<AppVersion> => get<AppVersion>("/investor/app-version");

/** The newest clear Sentinel-2 photo over a holding's farm. */
export interface LatestPhoto {
  scene_datetime: string;
  /** XYZ template, `{z}/{x}/{y}` left in, for a 512 px raster source. */
  tile_url: string;
  /** [west, south, east, north] of the farm; absent from older apis. */
  bounds?: [number, number, number, number] | null;
}

/**
 * The photo, or null when there is none, the api predates the route, or the
 * phone is offline. The map works without it, so no failure is surfaced.
 */
export async function fetchLatestPhoto(holdingId: string): Promise<LatestPhoto | null> {
  try {
    const body = await get<{ photo: LatestPhoto | null }>(
      `/investor/holdings/${holdingId}/latest-photo`,
    );
    return body.photo ?? null;
  } catch {
    return null;
  }
}

/** A field photo of an activity: short-lived links. */
export interface ActivityPhoto {
  thumb_url: string;
  url: string;
  taken_at: string | null;
}

/** One activity on the holding's block this season (decision D4). */
export interface Activity {
  id: string;
  activity_type: string;
  title: string | null;
  title_ar: string | null;
  scheduled_date: string;
  status: "upcoming" | "in_progress" | "completed";
  completed_at: string | null;
  photos: ActivityPhoto[];
}

/** The newest field photo on the holding's block. */
export interface SitePhoto {
  url: string;
  taken_at: string | null;
}

export const fetchActivities = (holdingId: string): Promise<Activity[]> =>
  get<Activity[]>(`/investor/holdings/${holdingId}/activities`);

export async function fetchSitePhoto(holdingId: string): Promise<SitePhoto | null> {
  const body = await get<{ photo: SitePhoto | null }>(`/investor/holdings/${holdingId}/site-photo`);
  return body.photo ?? null;
}

/** One pick, already scaled to the holding (D1). Decimals arrive as strings. */
export interface HarvestPick {
  pick_no: number;
  label: string | null;
  label_ar: string | null;
  harvested_on: string;
  weight_kg: string;
  price_per_kg: string | null;
  /** Gross: weight x price, no costs (D2). */
  revenue: string | null;
}

export interface Harvest {
  holding_id: string;
  season: string | null;
  /** Seasons with picks inside the ownership, newest first. */
  seasons: string[];
  currency: string | null;
  picks: HarvestPick[];
  total_weight_kg: string;
  total_revenue: string | null;
  average_price_per_kg: string | null;
}

/** The holding's harvest for a season; the newest when season is null. */
export const fetchHarvest = (holdingId: string, season: string | null): Promise<Harvest> =>
  get<Harvest>(
    `/investor/holdings/${holdingId}/harvest${season ? `?season=${encodeURIComponent(season)}` : ""}`,
  );

// ---- The last answers, kept for opening with no network --------------------

const CALL_CACHE_PREFIX = "agripulse.investor.call.";

export interface Cached<T> {
  data: T;
  /** Epoch ms of the fetch. */
  savedAt: number;
  /** True when the network failed and this is the stored copy. */
  offline: boolean;
}

/**
 * One call with the same offline rule as /me and /holdings: a fresh answer
 * is stored; on a network failure the stored one comes back, marked
 * offline. An HTTP error (404, 403) is not a network failure and is thrown.
 */
export async function cachedCall<T>(key: string, fetcher: () => Promise<T>): Promise<Cached<T>> {
  try {
    const data = await fetcher();
    const savedAt = Date.now();
    await Preferences.set({
      key: CALL_CACHE_PREFIX + key,
      value: JSON.stringify({ data, savedAt }),
    });
    return { data, savedAt, offline: false };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const { value } = await Preferences.get({ key: CALL_CACHE_PREFIX + key });
    if (!value) throw err;
    const stored = JSON.parse(value) as { data: T; savedAt: number };
    return { ...stored, offline: true };
  }
}

/** Drop every stored call (sign-out). */
export async function clearCalls(): Promise<void> {
  const { keys } = await Preferences.keys();
  await Promise.all(
    keys.filter((k) => k.startsWith(CALL_CACHE_PREFIX)).map((key) => Preferences.remove({ key })),
  );
}

const CACHE_KEY = "agripulse.investor.cache";

export interface Snapshot {
  me: Me;
  holdings: Holding[];
  /** Epoch ms of the fetch. */
  savedAt: number;
}

export async function readSnapshot(): Promise<Snapshot | null> {
  const { value } = await Preferences.get({ key: CACHE_KEY });
  return value ? (JSON.parse(value) as Snapshot) : null;
}

export async function writeSnapshot(s: Snapshot | null): Promise<void> {
  if (s) await Preferences.set({ key: CACHE_KEY, value: JSON.stringify(s) });
  else await Preferences.remove({ key: CACHE_KEY });
}

/** Fetch both lists; on a network failure fall back to the snapshot. */
export async function loadSnapshot(): Promise<{ data: Snapshot; offline: boolean }> {
  try {
    const [me, holdings] = await Promise.all([fetchMe(), fetchHoldings()]);
    const data = { me, holdings, savedAt: Date.now() };
    await writeSnapshot(data);
    return { data, offline: false };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const cached = await readSnapshot();
    if (!cached) throw err;
    return { data: cached, offline: true };
  }
}

/** a.b.c compared as numbers. -1, 0 or 1. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((x) => Number.parseInt(x, 10) || 0);
  const pb = b.split(".").map((x) => Number.parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}
