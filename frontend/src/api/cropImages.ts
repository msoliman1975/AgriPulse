// Crop image upload (backend /api/v1/admin/crops/{id}/image, build plan 3.1).
//
// Three steps: the API signs a PUT, the browser sends the file straight to
// storage, the API checks it and points the crop (or variety) at it. The
// light worker then writes the 64/128/256 px renditions the URLs name.

import { apiClient } from "./client";
import { uploadToPresignedUrl } from "@/lib/upload";

export type CropImageOwner = "crop" | "variety";

export const CROP_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const CROP_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

export interface CropImageUrls {
  crop_image_url: string | null;
  crop_icon_url: string | null;
}

interface UploadInit {
  s3_key: string;
  upload_url: string;
  upload_headers: Record<string, string>;
  expires_at: string;
}

function basePath(owner: CropImageOwner, id: string): string {
  return owner === "crop"
    ? `/v1/admin/crops/${encodeURIComponent(id)}/image`
    : `/v1/admin/crop-varieties/${encodeURIComponent(id)}/image`;
}

/** Why a file cannot be uploaded, as an i18n key, or null when it can. */
export function cropImageProblem(file: File): "imageType" | "imageSize" | null {
  if (!(CROP_IMAGE_TYPES as readonly string[]).includes(file.type)) return "imageType";
  if (file.size <= 0 || file.size > CROP_IMAGE_MAX_BYTES) return "imageSize";
  return null;
}

export async function uploadCropImage(
  owner: CropImageOwner,
  id: string,
  file: File,
): Promise<CropImageUrls> {
  const base = basePath(owner, id);
  const { data: init } = await apiClient.post<UploadInit>(`${base}/upload-init`, {
    content_type: file.type,
    size_bytes: file.size,
  });
  // The browser sets Content-Length itself; fetch refuses to send it by hand.
  const headers = Object.fromEntries(
    Object.entries(init.upload_headers).filter(([name]) => name.toLowerCase() !== "content-length"),
  );
  await uploadToPresignedUrl(file, init.upload_url, headers);
  const { data } = await apiClient.post<CropImageUrls>(`${base}/finalize`, {
    s3_key: init.s3_key,
  });
  return data;
}

export async function removeCropImage(owner: CropImageOwner, id: string): Promise<CropImageUrls> {
  const { data } = await apiClient.delete<CropImageUrls>(basePath(owner, id));
  return data;
}
