// Mirrors backend/app/modules/field_flags/schemas.py — keep in lock-step.
//
// A field flag is the one observation surface that is not an answer to a
// question somebody already posed: a scout saw something nobody asked about.

import { apiClient } from "./client";

export type FlagSeverity = "info" | "warning" | "critical";
export type FlagStatus = "open" | "closed";
export type FlagCloseReason = "actioned" | "no_action_needed" | "duplicate";
export type FlagCommentKind = "comment" | "close" | "reopen";

export interface FlagPhoto {
  id: string;
  attachment_s3_key: string;
  download_url: string | null;
  created_at: string;
}

export interface FlagComment {
  id: string;
  body: string;
  author_id: string;
  author_name: string | null;
  kind: FlagCommentKind;
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
  /** GeoJSON Point. Null when the scout recorded no position — the map falls
   *  back to the block centroid rather than dropping the flag. */
  point: { type: "Point"; coordinates: [number, number] } | null;
  accuracy_m: number | null;
  pin_until: string;
  /** Derived server-side. Unpinned is NOT closed: an expired pin still has an
   *  open thread and still belongs in the panel. */
  is_pinned: boolean;
  raised_by: string;
  raised_by_name: string | null;
  closed_at: string | null;
  closed_by: string | null;
  closed_by_name: string | null;
  close_reason: FlagCloseReason | null;
  comment_count: number;
  photos: FlagPhoto[];
  comments: FlagComment[];
  created_at: string;
  updated_at: string;
}

export interface ListFlagParams {
  /** Only flags still open. */
  open_only?: boolean;
  /** Only flags whose pin lifetime has not run out — what the map layer asks
   *  for. The panel asks without it. */
  pinned_only?: boolean;
}

export async function listFieldFlags(
  farmId: string,
  params: ListFlagParams = {},
): Promise<FieldFlag[]> {
  const { data } = await apiClient.get<FieldFlag[]>(`/v1/farms/${farmId}/field-flags`, { params });
  return data;
}

export async function getFieldFlag(flagId: string): Promise<FieldFlag> {
  const { data } = await apiClient.get<FieldFlag>(`/v1/field-flags/${flagId}`);
  return data;
}

export async function commentOnFlag(flagId: string, body: string): Promise<FieldFlag> {
  const { data } = await apiClient.post<FieldFlag>(`/v1/field-flags/${flagId}/comments`, { body });
  return data;
}

/** Closing needs a reason AND a comment. A flag closed silently reads to the
 *  scout as being ignored, and that is how people stop flagging things. */
export async function closeFlag(
  flagId: string,
  payload: { reason: FlagCloseReason; comment: string },
): Promise<FieldFlag> {
  const { data } = await apiClient.post<FieldFlag>(`/v1/field-flags/${flagId}:close`, payload);
  return data;
}

/** Re-opening restarts the pin lifetime — otherwise a flag re-opened after its
 *  period ended would be open work with no pin on the map. */
export async function reopenFlag(flagId: string, comment: string): Promise<FieldFlag> {
  const { data } = await apiClient.post<FieldFlag>(`/v1/field-flags/${flagId}:reopen`, { comment });
  return data;
}
