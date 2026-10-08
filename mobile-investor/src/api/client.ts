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
}

export interface Geometry {
  type: string;
  coordinates: unknown;
}

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
  stage_name_en: string | null;
  stage_name_ar: string | null;
  stage_started_on: string | null;
  stage_expected_end: string | null;
  current_season: string | null;
  start_date: string;
  end_date: string | null;
  period: "past" | "current" | "future";
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

// ---- The last answers, kept for opening with no network --------------------

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
