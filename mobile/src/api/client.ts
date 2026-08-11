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

/**
 * An authenticated GET for callers outside this module. Exported rather than
 * letting them build their own fetch, so token refresh, the 401 handling and
 * Problem Details parsing stay in one place.
 */
export function authedGet<T>(path: string): Promise<T> {
  return request<T>(path);
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

/** One item of work, whatever surface assigned it. Mirrors WorkItemResponse. */
export interface WorkItem {
  kind: "scouting_visit" | "plan_activity";
  id: string;
  farm_id: string;
  block_id: string | null;
  title: string;
  detail: string | null;
  status: string;
  category: string | null;
  severity: "info" | "warning" | "critical" | null;
  priority: "low" | "medium" | "high" | null;
  due_at: string | null;
  /** The form the supervisor asked for. Null means the whole catalogue. */
  template_id: string | null;
}

/**
 * Everything assigned to this scout, merged server-side.
 *
 * `listVisits` only ever saw `scouting_visits`. Board work — the natural way a
 * supervisor schedules a crew — is keyed on a membership, not a user, so it
 * was structurally invisible here: the scout saw an empty list while their
 * name sat on the activities.
 */
export function listMyWork(farmId: string) {
  return request<WorkItem[]>(`/me/work?farm_id=${encodeURIComponent(farmId)}`);
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

export function acceptVisit(visitId: string, farmId: string) {
  return request<Visit>(`/scouting/visits/${visitId}:accept?farm_id=${farmId}`, { method: "POST" });
}

export type VisitOutcome = "resolved" | "inconclusive" | "blocked";

/**
 * Close a visit.
 *
 * `observation_group_id` names observations the client has ALREADY written
 * through the signals API. Capture and closure are two calls on purpose: a
 * failed submit must never destroy readings a scout has already taken, which
 * on a field connection is the likely failure.
 *
 * `idempotency_key` makes a retry safe — the same key replays rather than
 * double-closing.
 */
export function submitVisit(
  visitId: string,
  farmId: string,
  body: {
    outcome: VisitOutcome;
    summary_note?: string | null;
    observation_group_id?: string | null;
    idempotency_key?: string;
  },
) {
  return request<Visit>(`/scouting/visits/${visitId}:submit?farm_id=${farmId}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** A thing a scout can record against a block. */
export interface SignalDefinition {
  id: string;
  code: string;
  name: string;
  value_type: "numeric" | "categorical" | "event" | "boolean" | "geopoint" | null;
  unit?: string | null;
  allowed_values?: string[] | null;
  attachment_allowed?: boolean | null;
}

export interface TemplateMember {
  signal_definition_id: string;
  position: number;
  is_required: boolean;
}

/**
 * A named form: which signals to record on this visit, in order, and which
 * are required. This is how a supervisor says "record these three things"
 * rather than "go and look" — the whole catalogue is a dozen definitions and
 * asking a scout to find the right ones is how the wrong ones get recorded.
 */
export function getSignalTemplate(templateId: string) {
  return request<{ template: { id: string; name: string }; members: TemplateMember[] }>(
    `/signals/templates/${templateId}`,
  );
}

export function listSignalDefinitions(farmId: string) {
  return request<SignalDefinition[]>(
    `/signals/definitions?farm_id=${encodeURIComponent(farmId)}`,
  );
}

/**
 * Record one observation.
 *
 * `location_mode` stays at the default `entity`: `point_in_entity` is enforced
 * by a database ST_Within trigger, so GPS drift at a block edge would reject
 * the write AFTER the scout did the work. Attaching the reading to the block
 * is honest and always succeeds.
 */
export function recordObservation(
  definitionId: string,
  body: {
    farm_id: string;
    block_id?: string | null;
    value_numeric?: number | null;
    value_categorical?: string | null;
    value_boolean?: boolean | null;
    notes?: string | null;
  },
) {
  return request<{ id: string }>(`/signals/definitions/${definitionId}/observations`, {
    method: "POST",
    body: JSON.stringify(body),
  });
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
