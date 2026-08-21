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

/**
 * What the item that raised a visit has become since.
 *
 * A visit is written once; the finding behind it is re-evaluated every
 * morning. `member_count` is how many grid cells it now covers — one visit for
 * nine zones instead of nine visits — and `day_streak` is how long it has been
 * true. Read live by the API rather than snapshotted, because a snapshot of a
 * moving number is a stale number.
 *
 * Defaults (`is_group` false, one occurrence) for a visit with no
 * decision-engine source: routine, ad-hoc and self-initiated ones.
 */
/** Which way the finding is moving between evaluation days. `unknown` means
 *  there is no yesterday to compare against — deliberately not `steady`. */
export type SpreadTrend = "unknown" | "steady" | "spreading" | "receding";

export interface VisitSource {
  is_group: boolean;
  member_count: number;
  previous_member_count: number;
  trend: SpreadTrend;
  occurrence_count: number;
  day_streak: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface Visit {
  id: string;
  farm_id: string;
  block_id: string;
  cell_id: string | null;
  origin: VisitOrigin;
  title: string;
  instruction: string | null;
  /** Why the engine raised this. Free-shaped JSON — render defensively. */
  reason_snapshot: Record<string, unknown> | null;
  severity: "info" | "warning" | "critical";
  priority: "low" | "medium" | "high";
  due_by: string | null;
  status: string;
  assigned_to: string | null;
  source: VisitSource;
  template_id: string | null;
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
  /** Filled in by the client from the block list — `/me/work` sends only the
   *  id, and a scout cannot walk to a UUID. */
  block_name?: string | null;
  /** Zone count, spread and streak. `/me/work` does not send these either, so
   *  the Tasks list joins them on from the visit list. Board work has none. */
  source?: VisitSource | null;
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

export function listVisits(
  farmId: string,
  params: { mine?: boolean; claimable?: boolean; status?: string[] } = {},
) {
  const q = new URLSearchParams({ farm_id: farmId });
  if (params.mine) q.set("mine", "true");
  if (params.claimable) q.set("claimable", "true");
  // Repeated `status=` params, which is what FastAPI reads as a list.
  for (const s of params.status ?? []) q.append("status", s);
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

/** The five shapes a reading can take. Mirrors `ValueKind` in
 *  backend/app/modules/signals/schemas.py — the server rejects any value that
 *  does not match the definition's kind, so this list must stay identical. */
export type ValueKind = "numeric" | "categorical" | "event" | "boolean" | "geopoint";

/**
 * A thing a scout can record against a block.
 *
 * **The field names here are the API's, exactly.** This interface used to
 * invent its own — `value_type` for `value_kind`, `allowed_values` for
 * `categorical_values` — and because both were declared optional, TypeScript
 * accepted them and every read returned `undefined`. The form then fell back
 * to a free-text box for every signal on the phone and posted every reading
 * into `value_categorical`, so the server rejected all twelve definitions in
 * production: the eight with a lookup list ("value_categorical must be one
 * of [...]"), the three numeric ones and `scout_photo`. Renaming a field here
 * without renaming it in the API breaks the app silently. There is no test
 * that can catch it, because the wrong name is legal TypeScript.
 *
 * `value_min` / `value_max` arrive as **strings** — they are Postgres
 * `numeric` columns, and Pydantic serialises `Decimal` to a JSON string to
 * avoid float rounding. Compare them with `Number()`, never with `<` directly.
 */
export interface SignalDefinition {
  id: string;
  code: string;
  name: string;
  description: string | null;
  value_kind: ValueKind;
  unit: string | null;
  /** The lookup list. Non-empty for every `categorical` definition — the
   *  server refuses to create one without it — and null for every other kind. */
  categorical_values: string[] | null;
  /** Inclusive bounds on a `numeric` reading. Decimal-as-string; see above. */
  value_min: string | null;
  value_max: string | null;
  attachment_allowed: boolean;
  is_active: boolean;
}

/**
 * Close a board activity.
 *
 * A PATCH with `state`, not a dedicated route: the same endpoint edits
 * metadata, and the two gate on different capabilities — `state` needs
 * `plan_activity.complete`, metadata needs `plan.manage`. Sending only
 * `state` keeps a scout on the side they hold.
 *
 * `state` is an ACTION VERB — `start` / `complete` / `skip` — not the status
 * it produces. This used to send `completed` / `skipped`, which are the
 * resulting statuses; the field is a Literal of the three verbs, so every
 * call was rejected and "Mark done" had never once worked. The argument here
 * is named `action` so the next reader cannot make the same swap.
 */
export function completeActivity(activityId: string, action: "complete" | "skip") {
  return request<{ id: string; status: string }>(`/activities/${activityId}`, {
    method: "PATCH",
    body: JSON.stringify({ state: action }),
  });
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

/** WGS84, matching the API's GeopointModel field names exactly. */
export interface Geopoint {
  latitude: number;
  longitude: number;
}

/**
 * Record one observation.
 *
 * `location_mode` is `entity` when there is no fix and **`free_point`** when
 * there is — never `point_in_entity`. That third mode is enforced by a
 * database ST_Within trigger, so a GPS fix a few metres outside the block
 * boundary rejects the write AFTER the scout has done the work, in a field,
 * with no way to correct it. `free_point` keeps the reading and the position
 * and cannot fail on drift; being inside the block is not a promise this app
 * is in a position to make.
 */
export function recordObservation(
  definitionId: string,
  body: {
    farm_id: string;
    block_id?: string | null;
    // All five value columns are declared, and the server accepts EXACTLY ONE
    // of them — the one matching the definition's `value_kind`. `value_event`
    // and `value_geopoint` were missing from this type while the caller was
    // already spreading them in; TypeScript does not excess-property-check a
    // spread, so the omission never surfaced as an error.
    value_numeric?: number | null;
    value_categorical?: string | null;
    value_event?: string | null;
    value_boolean?: boolean | null;
    value_geopoint?: Geopoint | null;
    notes?: string | null;
    attachment_s3_key?: string | null;
    location_mode?: "entity" | "free_point";
    location_point?: Geopoint | null;
  },
) {
  return request<{ id: string }>(`/signals/definitions/${definitionId}/observations`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface AttachmentUpload {
  attachment_s3_key: string;
  upload_url: string;
  upload_headers: Record<string, string>;
  expires_at: string;
}

/**
 * Ask for a presigned PUT to upload one photo to.
 *
 * Two steps, not one: the file goes straight to object storage rather than
 * through the API, so a 4 MB photo on a field connection never occupies an
 * API worker. The key comes back before the upload so the caller can put it
 * on the observation once the PUT lands.
 */
export function initAttachmentUpload(body: {
  signal_definition_id: string;
  farm_id: string;
  content_type: string;
  content_length: number;
  filename: string;
}) {
  return request<AttachmentUpload>(`/signals/observations:upload-init`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * PUT the bytes to object storage.
 *
 * Deliberately not `request()`: the presigned URL is absolute, carries its own
 * authorization in the query string, and must NOT receive our bearer token —
 * some S3-compatible backends reject a request that is signed twice.
 */
export async function uploadAttachment(upload: AttachmentUpload, file: Blob): Promise<void> {
  const resp = await fetch(upload.upload_url, {
    method: "PUT",
    headers: upload.upload_headers,
    body: file,
  });
  if (!resp.ok) throw new ApiError(resp.status, `upload failed (${resp.status})`);
}

/** One observation as the API returns it. */
export interface Observation {
  id: string;
  time: string;
  signal_code: string;
  block_id: string | null;
  value_numeric: number | null;
  value_categorical: string | null;
  notes: string | null;
  recorded_by: string;
  attachment_download_url: string | null;
}

/**
 * Recent observations on this farm.
 *
 * There is no `recorded_by` filter on the API, so the Records screen asks for
 * the farm's recent rows and keeps its own. That is honest about what the
 * endpoint can do; the alternative is a screen that silently shows other
 * people's readings as yours.
 */
export function listObservations(farmId: string, params: { since?: string; limit?: number } = {}) {
  const q = new URLSearchParams({ farm_id: farmId, limit: String(params.limit ?? 100) });
  if (params.since) q.set("since", params.since);
  return request<Observation[]>(`/signals/observations?${q}`);
}

/**
 * Log a round the scout chose to do.
 *
 * Opens straight into `in_progress` — there is nothing to accept, because
 * nobody assigned it. It closes through the same submit path as a dispatched
 * visit, so a self-started round and an assigned one end up the same shape in
 * the visit history.
 */
export function createSelfInitiatedVisit(
  farmId: string,
  body: { block_id: string; title?: string | null; template_id?: string | null },
) {
  return request<Visit>(`/scouting/visits?farm_id=${encodeURIComponent(farmId)}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** A block, as far as the phone needs to know about one. */
export interface Block {
  id: string;
  code: string;
  name: string | null;
  is_active: boolean;
}

/**
 * The farm's blocks, for naming a work item and for the block picker.
 *
 * One page of 200 covers every farm in production and the endpoint exists
 * precisely so a client does not fetch blocks one at a time.
 */
export async function listBlocks(farmId: string): Promise<Block[]> {
  const page = await request<{ items: Block[] }>(
    `/farms/${encodeURIComponent(farmId)}/blocks?limit=200`,
  );
  return page.items.filter((b) => b.is_active);
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

// ---- Field flags -----------------------------------------------------------
//
// The one thing a scout records that nobody asked for. Mirrors
// backend/app/modules/field_flags/schemas.py.

export type FlagSeverity = "info" | "warning" | "critical";
export type FlagStatus = "open" | "closed";
export type FlagCloseReason = "actioned" | "no_action_needed" | "duplicate";

export interface FlagComment {
  id: string;
  body: string;
  author_id: string;
  author_name: string | null;
  kind: "comment" | "close" | "reopen";
  created_at: string;
}

export interface FieldFlag {
  id: string;
  farm_id: string;
  block_id: string;
  block_name: string | null;
  note: string;
  severity: FlagSeverity;
  status: FlagStatus;
  pin_until: string;
  is_pinned: boolean;
  raised_by: string;
  close_reason: FlagCloseReason | null;
  comment_count: number;
  photos: { id: string; download_url: string | null }[];
  comments: FlagComment[];
  created_at: string;
}

export function listFieldFlags(farmId: string, params: { open_only?: boolean } = {}) {
  const q = new URLSearchParams();
  if (params.open_only) q.set("open_only", "true");
  return request<FieldFlag[]>(`/farms/${encodeURIComponent(farmId)}/field-flags?${q}`);
}

export function getFieldFlag(flagId: string) {
  return request<FieldFlag>(`/field-flags/${flagId}`);
}

/**
 * Raise a flag.
 *
 * A block is required — every flag belongs to one, so a finding beside a gate
 * is attached to the block it sits beside. `point` is optional and, like every
 * other position this app writes, is a plain fix rather than a claim to be
 * inside the block boundary.
 */
export function raiseFieldFlag(
  farmId: string,
  body: {
    block_id: string;
    note: string;
    severity: FlagSeverity;
    point?: Geopoint | null;
    accuracy_m?: number | null;
    attachment_s3_keys?: string[];
  },
) {
  return request<FieldFlag>(`/farms/${encodeURIComponent(farmId)}/field-flags`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function commentOnFlag(flagId: string, body: string) {
  return request<FieldFlag>(`/field-flags/${flagId}/comments`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

/** Re-opening needs a comment and restarts the pin on the supervisor's map. */
export function reopenFieldFlag(flagId: string, comment: string) {
  return request<FieldFlag>(`/field-flags/${flagId}:reopen`, {
    method: "POST",
    body: JSON.stringify({ comment }),
  });
}

/** Presigned PUT for one flag photo. Same two-step upload as a signal photo. */
export function initFlagPhotoUpload(body: {
  farm_id: string;
  content_type: string;
  content_length: number;
  filename: string;
}) {
  return request<AttachmentUpload>(`/field-flags:upload-init`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
