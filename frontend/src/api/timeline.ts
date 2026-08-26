// The Farm Timeline read — every datapoint on a farm (or one block),
// already bucketed by UTC calendar day.
//
// One request rather than seven. The endpoint gathers flags, signal
// observations, completed activities, scouting visits, alerts,
// recommendations and (block scope only) phenology transitions, so the
// replay screen scrubs across a window without fanning out per kind.
import { apiClient } from "./client";

export const TIMELINE_EVENT_KINDS = [
  "stage",
  "signal",
  "activity",
  "visit",
  "flag",
  "alert",
  "recommendation",
] as const;

export type TimelineEventKind = (typeof TIMELINE_EVENT_KINDS)[number];

export interface TimelineEvent {
  kind: TimelineEventKind;
  /**
   * Unique within one response. Text rather than a UUID: a signal
   * observation's identity is `(time, id)`, and the caller only ever uses
   * this as a React key.
   */
  id: string;
  /** The instant, for ordering within a day. */
  at: string;
  /**
   * The UTC calendar day this belongs to, `YYYY-MM-DD`. Computed on the
   * server with an explicit `AT TIME ZONE 'UTC'`, so a browser in Cairo
   * and one in London put the same event on the same frame.
   */
  day: string;
  block_id: string | null;
  block_name: string | null;
  block_code: string | null;
  /**
   * The enum-ish value to translate: activity type, alert action, stage
   * code, signal definition code. Null when the source has none — the
   * caller falls back to the kind's own label.
   */
  code: string | null;
  /**
   * The row's own text. Only alerts and recommendations store both
   * languages; everything else is a tenant-authored string that exists in
   * one language and is shown unchanged in either locale.
   */
  title_en: string;
  title_ar: string | null;
  detail: string | null;
  /** Raw from the source table. Map it through `markerSeverity`. */
  severity: string | null;
  /**
   * GeoJSON Point, or null when the row is block-scoped rather than
   * located. A null point draws no mark — the block outline carries it,
   * which is honest about the fact that nobody recorded a coordinate.
   */
  point: { type: "Point"; coordinates: [number, number] } | null;
}

export interface TimelineDay {
  day: string;
  counts: Partial<Record<TimelineEventKind, number>>;
  total: number;
}

export interface TimelineResponse {
  farm_id: string;
  block_id: string | null;
  from: string;
  to: string;
  events: TimelineEvent[];
  /** Only days that HAVE events. Empty days are absent, not zero. */
  days: TimelineDay[];
  /**
   * Kinds the caller has no capability for. Named so the screen can say
   * "you cannot see alerts" instead of showing an empty lane, which reads
   * as "nothing happened".
   */
  omitted_kinds: TimelineEventKind[];
  /** A kind hit its row cap. The window is the fix, and the UI says so. */
  truncated: boolean;
}

export interface TimelineParams {
  /** Inclusive `YYYY-MM-DD`. */
  from: string;
  /** Inclusive `YYYY-MM-DD`. */
  to: string;
  /**
   * Narrow to one block. Phenology stages come back ONLY in this mode:
   * blocks on one farm run different plans, so a farm-wide stage would be
   * untrue about all but one of them.
   */
  blockId?: string | null;
}

export async function getFarmTimeline(
  farmId: string,
  params: TimelineParams,
): Promise<TimelineResponse> {
  const { data } = await apiClient.get<TimelineResponse>(`/v1/farms/${farmId}/timeline`, {
    params: {
      from: params.from,
      to: params.to,
      block_id: params.blockId ?? undefined,
    },
  });
  return data;
}
