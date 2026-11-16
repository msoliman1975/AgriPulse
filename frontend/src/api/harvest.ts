// Harvest picks on a block (backend /api/v1/blocks/{id}/harvest-lots, build plan 3.5).

import { apiClient } from "./client";

export interface HarvestLot {
  id: string;
  farm_id: string;
  block_id: string;
  block_crop_id: string | null;
  season_label: string;
  pick_no: number;
  label: string | null;
  label_ar: string | null;
  harvested_on: string;
  /** Decimals arrive as strings (JSON has no decimal type). */
  weight_kg: string;
  price_per_kg: string | null;
  /** The tenant's default currency when the pick was recorded. */
  currency: string;
  /** weight x price, 2 places; null until a price is known. */
  revenue: string | null;
  notes_internal: string | null;
  created_at: string;
  updated_at: string;
}

export interface HarvestLotPayload {
  harvested_on?: string;
  weight_kg?: string;
  price_per_kg?: string | null;
  pick_no?: number;
  label?: string | null;
  label_ar?: string | null;
  notes_internal?: string | null;
}

export async function listHarvestLots(blockId: string): Promise<HarvestLot[]> {
  const { data } = await apiClient.get<HarvestLot[]>(`/v1/blocks/${blockId}/harvest-lots`);
  return data;
}

export async function createHarvestLot(
  blockId: string,
  payload: HarvestLotPayload,
): Promise<HarvestLot> {
  const { data } = await apiClient.post<HarvestLot>(`/v1/blocks/${blockId}/harvest-lots`, payload);
  return data;
}

export async function updateHarvestLot(
  lotId: string,
  payload: HarvestLotPayload,
): Promise<HarvestLot> {
  const { data } = await apiClient.patch<HarvestLot>(`/v1/harvest-lots/${lotId}`, payload);
  return data;
}

export async function deleteHarvestLot(lotId: string): Promise<void> {
  await apiClient.delete(`/v1/harvest-lots/${lotId}`);
}
