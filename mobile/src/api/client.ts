/**
 * API access for the scout app.
 *
 * Every scouting route is farm-scoped, so `farm_id` rides on each request —
 * the backend gates on it via `farm_id_param`, which is what lets a
 * farm-scoped-only user (a Scout holds no tenant role) reach anything at all.
 */

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

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await validAccessToken();
  if (!token) throw new ApiError(401, "signed out");
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      Authorization: `Bearer ${token}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!resp.ok) {
    // Problem Details from the API — `detail` is written to be shown to a
    // person, so surface it rather than inventing a generic message.
    const problem = (await resp.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(resp.status, problem?.detail ?? `request failed (${resp.status})`);
  }
  return resp.status === 204 ? (undefined as T) : ((await resp.json()) as T);
}

export type VisitOrigin =
  | "recommendation"
  | "alert"
  | "routine"
  | "ad_hoc"
  | "self_initiated";

export interface Visit {
  id: string;
  farm_id: string;
  block_id: string;
  cell_id: string | null;
  origin: VisitOrigin;
  title: string;
  instruction: string | null;
  severity: "info" | "warning" | "critical";
  priority: "low" | "medium" | "high";
  due_by: string | null;
  status: string;
  assigned_to: string | null;
}

export function listVisits(farmId: string, params: { mine?: boolean; claimable?: boolean } = {}) {
  const q = new URLSearchParams({ farm_id: farmId });
  if (params.mine) q.set("mine", "true");
  if (params.claimable) q.set("claimable", "true");
  return request<Visit[]>(`/scouting/visits?${q}`);
}

export function getVisit(visitId: string, farmId: string) {
  return request<Visit>(`/scouting/visits/${visitId}?farm_id=${farmId}`);
}

export function claimVisit(visitId: string, farmId: string) {
  return request<Visit>(`/scouting/visits/${visitId}:claim?farm_id=${farmId}`, { method: "POST" });
}

export function startVisit(visitId: string, farmId: string) {
  return request<Visit>(`/scouting/visits/${visitId}:start?farm_id=${farmId}`, { method: "POST" });
}

// `farm_id` rides along for the same reason every scouting call carries it: a
// Scout holds no tenant role, so the capability only resolves against a farm
// they are scoped to. Without it the backend 403s and — because a failed
// registration is deliberately non-fatal — the scout simply never gets pushed.
export function registerDevice(token: string, farmId: string) {
  return request<{ id: string }>(`/devices:register?farm_id=${farmId}`, {
    method: "POST",
    body: JSON.stringify({ token, platform: "android" }),
  });
}

/**
 * Stop pushing to this handset. Called on sign-out, before the session is
 * cleared — it needs the access token to authenticate, and the server scopes
 * the delete to the caller so a token seen in a log cannot silence someone
 * else's phone.
 *
 * Without this the device row keeps its previous owner until the next scout
 * signs in and re-registers. Handsets get passed along at shift change, and a
 * phone put back in a drawer keeps buzzing for a person who no longer holds it.
 */
export function revokeDevice(token: string) {
  return request<void>(`/devices/${encodeURIComponent(token)}`, { method: "DELETE" });
}
