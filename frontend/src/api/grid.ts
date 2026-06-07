import { apiClient } from "./client";

import type { IndexCode } from "./indices";

// Mirrors backend/app/modules/grid/schemas.py — keep in lock-step.

export interface GridConfigResponse {
  id: string;
  block_id: string;
  product_id: string;
  cell_size_m: string;
  utm_srid: number;
  retired_at: string | null;
  created_at: string;
  updated_at: string;
  cell_count: number;
}

export interface CellSizePreviewResponse {
  cell_size_m: string;
  native_pixel_m: string;
  pixels_per_cell: number;
  estimated_cells: number;
  block_area_m2: string;
  valid: boolean;
  error: string | null;
}

export interface GridCellWithValue {
  cell_id: string;
  row_idx: number;
  col_idx: number;
  area_m2: string;
  centroid_lon: number;
  centroid_lat: number;
  geometry: GeoJSON.Polygon;
  mean: string | null;
  valid_pixel_pct: string | null;
  time: string | null;
}

export interface GridCellsResponse {
  block_id: string;
  product_id: string;
  index_code: string;
  cells: GridCellWithValue[];
  at: string | null;
}

export interface GridWorstCell {
  cell_id: string;
  row_idx: number;
  col_idx: number;
  centroid_lon: number;
  centroid_lat: number;
  mean: string | null;
  valid_pixel_pct: string | null;
  time: string | null;
  // Pivot-relative location — null for square (non-pivot) blocks.
  ring: number | null;
  sector_label: string | null;
}

export interface GridWorstCellsResponse {
  block_id: string;
  product_id: string;
  index_code: string;
  cells: GridWorstCell[];
  at: string | null;
}

export interface GridCellHistoryPoint {
  time: string;
  mean: string | null;
  min: string | null;
  max: string | null;
  std_dev: string | null;
  valid_pixel_pct: string | null;
}

export interface GridCellHistoryResponse {
  cell_id: string;
  index_code: string;
  product_id: string;
  points: GridCellHistoryPoint[];
}

export async function getGridConfig(
  blockId: string,
  productId: string,
): Promise<GridConfigResponse | null> {
  try {
    const { data } = await apiClient.get<GridConfigResponse>(
      `/v1/blocks/${blockId}/grid-configs/${productId}`,
    );
    return data;
  } catch (err: unknown) {
    // 404 = no active config — surface as null so the caller can render
    // an empty form instead of branching on error types.
    if (typeof err === "object" && err !== null && "response" in err) {
      const resp = (err as { response?: { status?: number } }).response;
      if (resp?.status === 404) return null;
    }
    throw err;
  }
}

export async function putGridConfig(
  blockId: string,
  productId: string,
  cellSizeM: number,
): Promise<GridConfigResponse> {
  const { data } = await apiClient.put<GridConfigResponse>(
    `/v1/blocks/${blockId}/grid-configs/${productId}`,
    { cell_size_m: cellSizeM },
  );
  return data;
}

export async function previewCellSize(
  blockId: string,
  productId: string,
  cellSizeM: number,
): Promise<CellSizePreviewResponse> {
  const { data } = await apiClient.post<CellSizePreviewResponse>(
    `/v1/blocks/${blockId}/grid-configs/${productId}/preview`,
    { cell_size_m: cellSizeM },
  );
  return data;
}

export async function getGridCells(
  blockId: string,
  productId: string,
  indexCode: IndexCode,
  at?: string,
): Promise<GridCellsResponse> {
  const { data } = await apiClient.get<GridCellsResponse>(
    `/v1/blocks/${blockId}/grid-cells`,
    {
      params: {
        product_id: productId,
        index: indexCode,
        at: at ?? undefined,
      },
    },
  );
  return data;
}

export async function getWorstGridCells(
  blockId: string,
  productId: string,
  indexCode: IndexCode,
  limit = 10,
  at?: string,
): Promise<GridWorstCellsResponse> {
  const { data } = await apiClient.get<GridWorstCellsResponse>(
    `/v1/blocks/${blockId}/grid-cells/worst`,
    {
      params: {
        product_id: productId,
        index: indexCode,
        limit,
        at: at ?? undefined,
      },
    },
  );
  return data;
}

export async function getGridCellHistory(
  cellId: string,
  productId: string,
  indexCode: IndexCode,
): Promise<GridCellHistoryResponse> {
  const { data } = await apiClient.get<GridCellHistoryResponse>(
    `/v1/grid-cells/${cellId}/history`,
    {
      params: { product_id: productId, index: indexCode },
    },
  );
  return data;
}
