/**
 * Crop documents (decision D29): manuals and guides attached to a crop path
 * and inherited downwards. Admin routes need platform.read / manage_crops;
 * block routes need crop_document.download on the block's farm.
 */

import { apiClient } from "./client";

export type CropDocumentKind = "manual" | "guide" | "standard" | "report" | "other";
export type CropDocumentLanguage = "en" | "ar" | "other";
export type CropDocumentDisposition = "inline" | "attachment";

export const CROP_DOCUMENT_KINDS: readonly CropDocumentKind[] = [
  "manual",
  "guide",
  "standard",
  "report",
  "other",
];
export const CROP_DOCUMENT_LANGUAGES: readonly CropDocumentLanguage[] = ["en", "ar", "other"];

/** Extensions the upload accepts; mirrors the backend's CONTENT_TYPES. */
export const CROP_DOCUMENT_ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv";
export const CROP_DOCUMENT_MAX_BYTES = 15 * 1024 * 1024;

export interface CropDocument {
  id: string;
  document_code: string;
  crop_path: string;
  title_en: string;
  title_ar: string;
  language: CropDocumentLanguage;
  kind: CropDocumentKind;
  edition: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  superseded_at: string | null;
  superseded_by: string | null;
  retired_at: string | null;
  created_at: string;
  updated_at: string;
  is_current: boolean;
}

export interface CropDocumentUploaded extends CropDocument {
  superseded_id: string | null;
}

export interface CropDocumentLink {
  url: string;
  expires_at: string;
  disposition: CropDocumentDisposition;
}

export interface BlockCropDocuments {
  block_id: string;
  crop_path: string | null;
  documents: CropDocument[];
}

export interface CropDocumentUploadInput {
  crop_path: string;
  document_code: string;
  title_en: string;
  title_ar: string;
  language: CropDocumentLanguage;
  kind: CropDocumentKind;
  edition: string;
  file: File;
}

export interface CropDocumentPatch {
  title_en?: string;
  title_ar?: string;
  language?: CropDocumentLanguage;
  kind?: CropDocumentKind;
  edition?: string;
  retired?: boolean;
}

export async function listAdminCropDocuments(cropPath: string): Promise<CropDocument[]> {
  const { data } = await apiClient.get<CropDocument[]>("/v1/admin/crop-documents", {
    params: { crop_path: cropPath },
  });
  return Array.isArray(data) ? data : [];
}

export async function uploadCropDocument(
  input: CropDocumentUploadInput,
): Promise<CropDocumentUploaded> {
  const fd = new FormData();
  fd.append("crop_path", input.crop_path);
  fd.append("document_code", input.document_code);
  fd.append("title_en", input.title_en);
  fd.append("title_ar", input.title_ar);
  fd.append("language", input.language);
  fd.append("kind", input.kind);
  fd.append("edition", input.edition);
  fd.append("file", input.file);
  const { data } = await apiClient.post<CropDocumentUploaded>("/v1/admin/crop-documents", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function updateCropDocument(
  documentId: string,
  patch: CropDocumentPatch,
): Promise<CropDocument> {
  const { data } = await apiClient.patch<CropDocument>(
    `/v1/admin/crop-documents/${encodeURIComponent(documentId)}`,
    patch,
  );
  return data;
}

export async function adminCropDocumentLink(
  documentId: string,
  disposition: CropDocumentDisposition,
): Promise<CropDocumentLink> {
  const { data } = await apiClient.get<CropDocumentLink>(
    `/v1/admin/crop-documents/${encodeURIComponent(documentId)}/link`,
    { params: { disposition } },
  );
  return data;
}

export async function listBlockCropDocuments(blockId: string): Promise<BlockCropDocuments> {
  const { data } = await apiClient.get<BlockCropDocuments>(
    `/v1/blocks/${encodeURIComponent(blockId)}/crop-documents`,
  );
  return { ...data, documents: data.documents ?? [] };
}

export async function blockCropDocumentLink(
  blockId: string,
  documentId: string,
  disposition: CropDocumentDisposition,
): Promise<CropDocumentLink> {
  const { data } = await apiClient.get<CropDocumentLink>(
    `/v1/blocks/${encodeURIComponent(blockId)}/crop-documents/${encodeURIComponent(documentId)}/link`,
    { params: { disposition } },
  );
  return data;
}

/**
 * Open a freshly minted link. The window is opened synchronously on the click
 * (so a popup blocker allows it) and pointed at the URL once it arrives; the
 * link is short-lived, so it is never fetched ahead of the click.
 */
export async function openCropDocumentLink(
  fetchLink: () => Promise<CropDocumentLink>,
): Promise<void> {
  const win = window.open("about:blank", "_blank");
  try {
    const link = await fetchLink();
    if (win) {
      win.opener = null;
      win.location.href = link.url;
    } else {
      window.location.assign(link.url);
    }
  } catch (err) {
    win?.close();
    throw err;
  }
}

/** "2.4 MB", "830 KB". */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}
