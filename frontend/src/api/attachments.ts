import { apiClient } from "./client";

// Mirrors backend/app/modules/farms/schemas.py — keep in lock-step.

export type AttachmentKind = "photo" | "deed" | "soil_test_report" | "map" | "other";

export interface AttachmentUploadInitRequest {
  kind: AttachmentKind;
  original_filename: string;
  content_type: string;
  size_bytes: number;
}

export interface AttachmentUploadInitResponse {
  attachment_id: string;
  s3_key: string;
  upload_url: string;
  upload_headers: Record<string, string>;
  expires_at: string;
}

export interface AttachmentFinalizeRequest {
  attachment_id: string;
  s3_key: string;
  kind: AttachmentKind;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  caption?: string | null;
  taken_at?: string | null;
  geo_point?: GeoJSON.Point | null;
}

export interface Attachment {
  id: string;
  owner_kind: "farm" | "block";
  owner_id: string;
  kind: AttachmentKind;
  s3_key: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  caption: string | null;
  taken_at: string | null;
  geo_point: GeoJSON.Point | null;
  download_url: string;
  download_url_expires_at: string;
  created_at: string;
  updated_at: string;
}

// ---- Farm attachments -----------------------------------------------------

export async function initFarmAttachment(
  farmId: string,
  payload: AttachmentUploadInitRequest,
): Promise<AttachmentUploadInitResponse> {
  const { data } = await apiClient.post<AttachmentUploadInitResponse>(
    `/v1/farms/${farmId}/attachments:init`,
    payload,
  );
  return data;
}

export async function finalizeFarmAttachment(
  farmId: string,
  payload: AttachmentFinalizeRequest,
): Promise<Attachment> {
  const { data } = await apiClient.post<Attachment>(`/v1/farms/${farmId}/attachments`, payload);
  return data;
}

export async function listFarmAttachments(farmId: string): Promise<Attachment[]> {
  const { data } = await apiClient.get<Attachment[]>(`/v1/farms/${farmId}/attachments`);
  return data;
}

export async function deleteFarmAttachment(attachmentId: string): Promise<void> {
  await apiClient.delete(`/v1/farms/attachments/${attachmentId}`);
}

// ---- Block attachments ----------------------------------------------------

export async function initBlockAttachment(
  blockId: string,
  payload: AttachmentUploadInitRequest,
): Promise<AttachmentUploadInitResponse> {
  const { data } = await apiClient.post<AttachmentUploadInitResponse>(
    `/v1/blocks/${blockId}/attachments:init`,
    payload,
  );
  return data;
}

export async function finalizeBlockAttachment(
  blockId: string,
  payload: AttachmentFinalizeRequest,
): Promise<Attachment> {
  const { data } = await apiClient.post<Attachment>(`/v1/blocks/${blockId}/attachments`, payload);
  return data;
}

export async function listBlockAttachments(blockId: string): Promise<Attachment[]> {
  const { data } = await apiClient.get<Attachment[]>(`/v1/blocks/${blockId}/attachments`);
  return data;
}

export async function deleteBlockAttachment(attachmentId: string): Promise<void> {
  await apiClient.delete(`/v1/blocks/attachments/${attachmentId}`);
}
