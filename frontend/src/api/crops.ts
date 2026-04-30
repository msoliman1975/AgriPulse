import { apiClient } from "./client";

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
}

export interface CropVariety {
  id: string;
  crop_id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
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
