import { apiClient } from "./client";

export type BlockCropStatus = "planned" | "growing" | "harvesting" | "completed" | "aborted";

export interface BlockCropAssignment {
  id: string;
  block_id: string;
  crop_id: string;
  crop_variety_id: string | null;
  season_label: string;
  planting_date: string | null;
  expected_harvest_start: string | null;
  expected_harvest_end: string | null;
  actual_harvest_date: string | null;
  plant_density_per_ha: number | null;
  row_spacing_m: number | null;
  plant_spacing_m: number | null;
  growth_stage: string | null;
  growth_stage_updated_at: string | null;
  is_current: boolean;
  status: BlockCropStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface BlockCropAssignPayload {
  crop_id: string;
  crop_variety_id?: string | null;
  season_label: string;
  planting_date?: string | null;
  expected_harvest_start?: string | null;
  expected_harvest_end?: string | null;
  plant_density_per_ha?: number | null;
  row_spacing_m?: number | null;
  plant_spacing_m?: number | null;
  notes?: string | null;
  make_current?: boolean;
}

export async function assignBlockCrop(
  blockId: string,
  payload: BlockCropAssignPayload,
): Promise<BlockCropAssignment> {
  const { data } = await apiClient.post<BlockCropAssignment>(
    `/v1/blocks/${blockId}/crop-assignments`,
    payload,
  );
  return data;
}

export async function listBlockCrops(blockId: string): Promise<BlockCropAssignment[]> {
  const { data } = await apiClient.get<BlockCropAssignment[]>(
    `/v1/blocks/${blockId}/crop-assignments`,
  );
  return data;
}
