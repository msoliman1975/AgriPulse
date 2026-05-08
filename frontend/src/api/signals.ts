// Mirrors backend/app/modules/signals/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export type ValueKind = "numeric" | "categorical" | "event" | "boolean" | "geopoint";

export interface SignalDefinition {
  id: string;
  code: string;
  name: string;
  description: string | null;
  value_kind: ValueKind;
  unit: string | null;
  categorical_values: string[] | null;
  // Pydantic Decimal serialises as string.
  value_min: string | null;
  value_max: string | null;
  attachment_allowed: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SignalDefinitionCreatePayload {
  code: string;
  name: string;
  description?: string | null;
  value_kind: ValueKind;
  unit?: string | null;
  categorical_values?: string[] | null;
  value_min?: string | null;
  value_max?: string | null;
  attachment_allowed?: boolean;
}

export interface SignalDefinitionUpdatePayload {
  name?: string;
  description?: string | null;
  unit?: string | null;
  categorical_values?: string[] | null;
  value_min?: string | null;
  value_max?: string | null;
  attachment_allowed?: boolean;
  is_active?: boolean;
}

export interface SignalAssignment {
  id: string;
  signal_definition_id: string;
  farm_id: string | null;
  block_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Geopoint {
  latitude: number;
  longitude: number;
}

export interface SignalObservation {
  id: string;
  time: string;
  signal_definition_id: string;
  signal_code: string;
  farm_id: string;
  block_id: string | null;
  value_numeric: string | null;
  value_categorical: string | null;
  value_event: string | null;
  value_boolean: boolean | null;
  value_geopoint: Geopoint | null;
  attachment_s3_key: string | null;
  attachment_download_url: string | null;
  notes: string | null;
  recorded_by: string;
  inserted_at: string;
}

export interface SignalObservationCreatePayload {
  time?: string | null;
  farm_id: string;
  block_id?: string | null;
  value_numeric?: string | null;
  value_categorical?: string | null;
  value_event?: string | null;
  value_boolean?: boolean | null;
  value_geopoint?: Geopoint | null;
  attachment_s3_key?: string | null;
  notes?: string | null;
}

export interface SignalAttachmentInitPayload {
  signal_definition_id: string;
  farm_id: string;
  content_type: string;
  content_length: number;
  filename: string;
}

export interface SignalAttachmentInitResponse {
  attachment_s3_key: string;
  upload_url: string;
  upload_headers: Record<string, string>;
  expires_at: string;
}

export interface ListObservationParams {
  signal_definition_id?: string;
  farm_id?: string;
  block_id?: string;
  since?: string;
  until?: string;
  limit?: number;
}

export async function listSignalDefinitions(includeInactive = false): Promise<SignalDefinition[]> {
  const { data } = await apiClient.get<SignalDefinition[]>("/v1/signals/definitions", {
    params: { include_inactive: includeInactive },
  });
  return data;
}

export async function createSignalDefinition(
  payload: SignalDefinitionCreatePayload,
): Promise<SignalDefinition> {
  const { data } = await apiClient.post<SignalDefinition>("/v1/signals/definitions", payload);
  return data;
}

export async function updateSignalDefinition(
  id: string,
  payload: SignalDefinitionUpdatePayload,
): Promise<SignalDefinition> {
  const { data } = await apiClient.patch<SignalDefinition>(
    `/v1/signals/definitions/${id}`,
    payload,
  );
  return data;
}

export async function deleteSignalDefinition(id: string): Promise<void> {
  await apiClient.delete(`/v1/signals/definitions/${id}`);
}

export async function listSignalAssignments(definitionId: string): Promise<SignalAssignment[]> {
  const { data } = await apiClient.get<SignalAssignment[]>(
    `/v1/signals/definitions/${definitionId}/assignments`,
  );
  return data;
}

export async function createSignalAssignment(
  definitionId: string,
  payload: { farm_id?: string | null; block_id?: string | null },
): Promise<SignalAssignment> {
  const { data } = await apiClient.post<SignalAssignment>(
    `/v1/signals/definitions/${definitionId}/assignments`,
    payload,
  );
  return data;
}

export async function deleteSignalAssignment(assignmentId: string): Promise<void> {
  await apiClient.delete(`/v1/signals/assignments/${assignmentId}`);
}

export async function initSignalAttachment(
  payload: SignalAttachmentInitPayload,
): Promise<SignalAttachmentInitResponse> {
  const { data } = await apiClient.post<SignalAttachmentInitResponse>(
    "/v1/signals/observations:upload-init",
    payload,
  );
  return data;
}

export async function uploadAttachmentToS3(
  init: SignalAttachmentInitResponse,
  file: File,
): Promise<void> {
  const res = await fetch(init.upload_url, {
    method: "PUT",
    headers: init.upload_headers,
    body: file,
  });
  if (!res.ok) {
    throw new Error(`S3 upload failed (${res.status}): ${await res.text()}`);
  }
}

export async function createSignalObservation(
  definitionId: string,
  payload: SignalObservationCreatePayload,
): Promise<SignalObservation> {
  const { data } = await apiClient.post<SignalObservation>(
    `/v1/signals/definitions/${definitionId}/observations`,
    payload,
  );
  return data;
}

export async function listSignalObservations(
  params: ListObservationParams = {},
): Promise<SignalObservation[]> {
  const { data } = await apiClient.get<SignalObservation[]>("/v1/signals/observations", {
    params,
  });
  return data;
}
