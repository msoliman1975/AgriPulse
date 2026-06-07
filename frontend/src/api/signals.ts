// Mirrors backend/app/modules/signals/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export type ValueKind = "numeric" | "categorical" | "event" | "boolean" | "geopoint";

// CS-1 D3 / CS-9. Non-numeric kinds are coerced to `latest` server-side.
export type Aggregation = "latest" | "mean" | "median" | "max" | "min";

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
  aggregation: Aggregation;
  aggregation_window_days: number | null;
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
  aggregation?: Aggregation;
  aggregation_window_days?: number | null;
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
  aggregation?: Aggregation;
  aggregation_window_days?: number | null;
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

export type LocationMode = "entity" | "point_in_entity" | "free_point";

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
  // CS-5 surface — defaults preserve old shape for FE consumers that
  // haven't been updated. `entity` mode has no location_point.
  location_mode?: LocationMode;
  location_point?: Geopoint | null;
  template_observation_id?: string | null;
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
  // CS-10. Defaults to `entity` server-side when omitted, preserving the
  // pre-CS-10 single-shot behavior. `location_point` is required by the
  // backend for non-`entity` modes (point_in_entity is ST_Within-validated).
  location_mode?: LocationMode;
  location_point?: Geopoint | null;
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
  // CS-5: lets the FE hydrate every sibling of a template submission
  // in one query (the submit response returns this id).
  template_observation_id?: string;
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

export async function deleteSignalDefinition(id: string, force = false): Promise<void> {
  await apiClient.delete(`/v1/signals/definitions/${id}`, { params: { force } });
}

// CS-13 references + conflict-aware archive.
export interface SignalReference {
  id: string;
  code: string;
  name: string;
  kind: "decision_tree" | "signal_template";
}

export interface SignalReferences {
  decision_trees: SignalReference[];
  templates: SignalReference[];
}

export async function getSignalDefinitionReferences(id: string): Promise<SignalReferences> {
  const { data } = await apiClient.get<SignalReferences>(
    `/v1/signals/definitions/${id}/references`,
  );
  return data;
}

export async function getSignalTemplateReferences(id: string): Promise<SignalReferences> {
  const { data } = await apiClient.get<SignalReferences>(
    `/v1/signals/templates/${id}/references`,
  );
  return data;
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

// CS-11 delete (capability: signal.delete_observation). Hard-delete; the
// audit log preserves the row. Both return { deleted: <rows removed> }.
export async function deleteSignalObservation(
  observationId: string,
): Promise<{ deleted: number }> {
  const { data } = await apiClient.delete<{ deleted: number }>(
    `/v1/signals/observations/${observationId}`,
  );
  return data;
}

export async function deleteSignalTemplateObservationGroup(
  templateObservationId: string,
): Promise<{ deleted: number }> {
  const { data } = await apiClient.delete<{ deleted: number }>("/v1/signals/observations", {
    params: { template_observation_id: templateObservationId },
  });
  return data;
}

// CS-7 CSV import. Multipart upload — the backend's UploadFile reads
// the whole body, so we pass a real File via FormData (axios sets the
// boundary). Errors come back as a 422 with extras.errors = [...] or
// a 413 with extras.size_bytes/limit_bytes; both are surfaced through
// the standard apiClient error interceptor.
export interface CsvImportSuccess {
  rows_imported: number;
}

export interface CsvImportRowError {
  row_number: number;
  field: string | null;
  message: string;
}

export async function importSignalObservationsCsv(
  farmId: string,
  file: File,
  bulkMode = false,
): Promise<CsvImportSuccess> {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await apiClient.post<CsvImportSuccess>("/v1/signals/csv-import", fd, {
    params: { farm_id: farmId, bulk_mode: bulkMode },
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

// ---- CS-9: signal templates -----------------------------------------------
// The backend has shipped templates since CS-1 D1; this PR adds the FE client.

export interface SignalTemplate {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SignalTemplateMember {
  signal_definition_id: string;
  position: number;
  is_required: boolean;
}

export interface SignalTemplateWithMembers {
  template: SignalTemplate;
  members: SignalTemplateMember[];
}

export interface SignalTemplateCreatePayload {
  code: string;
  name: string;
  description?: string | null;
  members: SignalTemplateMember[];
}

export interface SignalTemplateUpdatePayload {
  name?: string;
  description?: string | null;
  is_active?: boolean;
  members?: SignalTemplateMember[];
}

export interface SignalTemplateObservationMemberSubmission {
  signal_definition_id: string;
  value_numeric?: string | null;
  value_categorical?: string | null;
  value_event?: string | null;
  value_boolean?: boolean | null;
  value_geopoint?: Geopoint | null;
  attachment_s3_key?: string | null;
  notes?: string | null;
}

export interface SignalTemplateObservationCreatePayload {
  farm_id: string;
  block_id?: string | null;
  observed_at?: string | null;
  location_mode?: LocationMode;
  location_point?: Geopoint | null;
  members: SignalTemplateObservationMemberSubmission[];
}

export interface SignalTemplateObservationCreateResponse {
  template_observation_id: string;
  template_id: string;
  farm_id: string;
  block_id: string | null;
  observed_at: string;
  observation_count: number;
}

export async function listSignalTemplates(includeInactive = false): Promise<SignalTemplate[]> {
  const { data } = await apiClient.get<SignalTemplate[]>("/v1/signals/templates", {
    params: { include_inactive: includeInactive },
  });
  return data;
}

export async function getSignalTemplate(id: string): Promise<SignalTemplateWithMembers> {
  const { data } = await apiClient.get<SignalTemplateWithMembers>(`/v1/signals/templates/${id}`);
  return data;
}

export async function createSignalTemplate(
  payload: SignalTemplateCreatePayload,
): Promise<SignalTemplateWithMembers> {
  const { data } = await apiClient.post<SignalTemplateWithMembers>(
    "/v1/signals/templates",
    payload,
  );
  return data;
}

export async function updateSignalTemplate(
  id: string,
  payload: SignalTemplateUpdatePayload,
): Promise<SignalTemplateWithMembers> {
  const { data } = await apiClient.patch<SignalTemplateWithMembers>(
    `/v1/signals/templates/${id}`,
    payload,
  );
  return data;
}

export async function deleteSignalTemplate(id: string, force = false): Promise<void> {
  await apiClient.delete(`/v1/signals/templates/${id}`, { params: { force } });
}

export async function createSignalTemplateObservation(
  templateId: string,
  payload: SignalTemplateObservationCreatePayload,
): Promise<SignalTemplateObservationCreateResponse> {
  const { data } = await apiClient.post<SignalTemplateObservationCreateResponse>(
    `/v1/signals/templates/${templateId}/observations`,
    payload,
  );
  return data;
}
