// Platform crop-catalog authoring API (mirrors backend /api/v1/admin/crops…).
// Codes are immutable; paths auto-derive server-side; "delete" is a soft
// retire via { is_active: false } on the update endpoints.

import { apiClient } from "./client";
import type { ClassificationDepth, Crop, CropVariety, CropVarietyStrain } from "./crops";

export interface CropCreatePayload {
  code: string;
  name_en: string;
  name_ar: string;
  category: string;
  is_perennial?: boolean;
  scientific_name?: string | null;
  classification_depth?: ClassificationDepth;
  default_growing_season_days?: number | null;
}

export interface CropUpdatePayload {
  name_en?: string;
  name_ar?: string;
  category?: string;
  is_perennial?: boolean;
  scientific_name?: string | null;
  classification_depth?: ClassificationDepth;
  default_growing_season_days?: number | null;
  is_active?: boolean;
}

export interface VarietyCreatePayload {
  code: string;
  name_en: string;
  name_ar?: string | null;
}

export interface NodeUpdatePayload {
  name_en?: string;
  name_ar?: string | null;
  is_active?: boolean;
}

// ---- Crops ----------------------------------------------------------------

export async function listAdminCrops(includeInactive = false): Promise<Crop[]> {
  const { data } = await apiClient.get<Crop[]>("/v1/admin/crops", {
    params: { include_inactive: includeInactive },
  });
  return data;
}

export async function createCrop(payload: CropCreatePayload): Promise<Crop> {
  const { data } = await apiClient.post<Crop>("/v1/admin/crops", payload);
  return data;
}

export async function updateCrop(cropId: string, payload: CropUpdatePayload): Promise<Crop> {
  const { data } = await apiClient.patch<Crop>(`/v1/admin/crops/${cropId}`, payload);
  return data;
}

// ---- Varieties ------------------------------------------------------------

export async function listAdminVarieties(
  cropId: string,
  includeInactive = false,
): Promise<CropVariety[]> {
  const { data } = await apiClient.get<CropVariety[]>(`/v1/admin/crops/${cropId}/varieties`, {
    params: { include_inactive: includeInactive },
  });
  return data;
}

export async function createVariety(
  cropId: string,
  payload: VarietyCreatePayload,
): Promise<CropVariety> {
  const { data } = await apiClient.post<CropVariety>(
    `/v1/admin/crops/${cropId}/varieties`,
    payload,
  );
  return data;
}

export async function updateVariety(
  varietyId: string,
  payload: NodeUpdatePayload,
): Promise<CropVariety> {
  const { data } = await apiClient.patch<CropVariety>(
    `/v1/admin/crop-varieties/${varietyId}`,
    payload,
  );
  return data;
}

// ---- Strains --------------------------------------------------------------

export async function listAdminStrains(
  varietyId: string,
  includeInactive = false,
): Promise<CropVarietyStrain[]> {
  const { data } = await apiClient.get<CropVarietyStrain[]>(
    `/v1/admin/crop-varieties/${varietyId}/strains`,
    { params: { include_inactive: includeInactive } },
  );
  return data;
}

export async function createStrain(
  varietyId: string,
  payload: VarietyCreatePayload,
): Promise<CropVarietyStrain> {
  const { data } = await apiClient.post<CropVarietyStrain>(
    `/v1/admin/crop-varieties/${varietyId}/strains`,
    payload,
  );
  return data;
}

export async function updateStrain(
  strainId: string,
  payload: NodeUpdatePayload,
): Promise<CropVarietyStrain> {
  const { data } = await apiClient.patch<CropVarietyStrain>(
    `/v1/admin/crop-variety-strains/${strainId}`,
    payload,
  );
  return data;
}
