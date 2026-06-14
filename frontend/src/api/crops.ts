import { apiClient } from "./client";

// Exact depth a block assignment for this crop must specify.
export type ClassificationDepth = "crop_only" | "variety" | "variety_strain";

export interface Crop {
  id: string;
  code: string;
  name_en: string;
  name_ar: string;
  scientific_name: string | null;
  category: string;
  is_perennial: boolean;
  default_growing_season_days: number | null;
  relevant_indices: string[];
  classification_depth: ClassificationDepth;
}

export interface CropVariety {
  id: string;
  crop_id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  // Canonical hierarchical code "<crop>.<variety>".
  path: string;
}

export interface CropVarietyStrain {
  id: string;
  crop_variety_id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  // Canonical hierarchical code "<crop>.<variety>.<strain>".
  path: string;
}

export async function listCrops(category?: string): Promise<Crop[]> {
  const { data } = await apiClient.get<Crop[]>("/v1/crops", {
    params: category ? { category } : undefined,
  });
  return data;
}

export async function listCropVarieties(cropId: string): Promise<CropVariety[]> {
  const { data } = await apiClient.get<CropVariety[]>(`/v1/crops/${cropId}/varieties`);
  return data;
}

export async function listVarietyStrains(cropVarietyId: string): Promise<CropVarietyStrain[]> {
  const { data } = await apiClient.get<CropVarietyStrain[]>(
    `/v1/crop-varieties/${cropVarietyId}/strains`,
  );
  return data;
}
