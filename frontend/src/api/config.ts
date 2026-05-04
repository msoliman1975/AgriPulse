import { apiClient } from "./client";

// Mirrors backend/app/modules/imagery/schemas.py::ConfigResponse.

export interface ImageryConfigEntry {
  product_id: string;
  product_code: string;
  product_name: string;
  bands: string[];
  supported_indices: string[];
}

export interface ConfigResponse {
  tile_server_base_url: string;
  s3_bucket: string;
  cloud_cover_visualization_max_pct: number;
  cloud_cover_aggregation_max_pct: number;
  products: ImageryConfigEntry[];
}

export async function getConfig(): Promise<ConfigResponse> {
  const { data } = await apiClient.get<ConfigResponse>("/v1/config");
  return data;
}
