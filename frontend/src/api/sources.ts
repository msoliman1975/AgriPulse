/**
 * Sources library (decision D27).
 *
 * Reads are open to every signed-in user; writes need platform.manage_crops.
 */

import { apiClient } from "./client";

export type SourceKind =
  | "article"
  | "book"
  | "report"
  | "web"
  | "standard"
  | "thesis"
  | "dataset"
  | "internal"
  | "other";

export const SOURCE_KINDS: readonly SourceKind[] = [
  "article",
  "book",
  "report",
  "web",
  "standard",
  "thesis",
  "dataset",
  "internal",
  "other",
];

export type Confidence = "high" | "medium" | "low" | "expert_inference";

export const CONFIDENCES: readonly Confidence[] = ["high", "medium", "low", "expert_inference"];

export type SourceEntityType =
  | "finding"
  | "decision_tree"
  | "tree_parameter"
  | "signal"
  | "plan_template_activity"
  | "reference_value"
  | "input"
  | "crop_attribute";

export interface SourceAlias {
  document_code: string;
  document_title?: string | null;
  ref_number: number;
}

export interface Source {
  id: string;
  kind: SourceKind;
  citation: string;
  title: string | null;
  authors: string | null;
  year: number | null;
  publisher: string | null;
  doi: string | null;
  url: string | null;
  language: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  link_count: number;
  aliases: SourceAlias[];
}

export interface SourceLink {
  id: string;
  source_id: string;
  entity_type: SourceEntityType;
  entity_key: string;
  detail: string;
  confidence: Confidence;
  note: string | null;
  created_at: string;
  citation: string;
  url: string | null;
  doi: string | null;
  year: number | null;
  kind: SourceKind;
}

export interface SourceDetail extends Source {
  links: SourceLink[];
}

export interface SourceDocument {
  document_code: string;
  document_title: string | null;
  entries: number;
}

export interface SourceFields {
  citation?: string;
  kind?: SourceKind;
  title?: string | null;
  authors?: string | null;
  year?: number | null;
  publisher?: string | null;
  doi?: string | null;
  url?: string | null;
  language?: string | null;
  notes?: string | null;
  is_active?: boolean;
}

export async function listSources(params: {
  q?: string;
  document?: string;
  includeInactive?: boolean;
}): Promise<Source[]> {
  const { data } = await apiClient.get<Source[]>("/v1/sources", {
    params: {
      q: params.q || undefined,
      document: params.document || undefined,
      include_inactive: params.includeInactive || undefined,
      limit: 500,
    },
  });
  return Array.isArray(data) ? data : [];
}

export async function listSourceDocuments(): Promise<SourceDocument[]> {
  const { data } = await apiClient.get<SourceDocument[]>("/v1/sources/documents");
  return Array.isArray(data) ? data : [];
}

export async function getSource(id: string): Promise<SourceDetail> {
  const { data } = await apiClient.get<SourceDetail>(`/v1/sources/${id}`);
  return { ...data, links: data.links ?? [], aliases: data.aliases ?? [] };
}

export async function listSourceLinks(
  entityType: SourceEntityType,
  entityKey: string,
): Promise<SourceLink[]> {
  const { data } = await apiClient.get<SourceLink[]>("/v1/sources/links", {
    params: { entity_type: entityType, entity_key: entityKey },
  });
  return Array.isArray(data) ? data : [];
}

export async function createSource(
  fields: SourceFields & { citation: string },
): Promise<SourceDetail> {
  const { data } = await apiClient.post<SourceDetail>("/v1/admin/sources", fields);
  return data;
}

export async function updateSource(id: string, fields: SourceFields): Promise<SourceDetail> {
  const { data } = await apiClient.patch<SourceDetail>(`/v1/admin/sources/${id}`, fields);
  return data;
}

export async function linkSource(
  id: string,
  link: {
    entity_type: SourceEntityType;
    entity_key: string;
    detail?: string;
    confidence: Confidence;
    note?: string | null;
  },
): Promise<SourceLink> {
  const { data } = await apiClient.post<SourceLink>(`/v1/admin/sources/${id}/links`, link);
  return data;
}

export async function unlinkSource(linkId: string): Promise<void> {
  await apiClient.delete(`/v1/admin/source-links/${linkId}`);
}
