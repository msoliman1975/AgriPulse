import { apiClient } from "./client";

export type ValueSchema = "string" | "number" | "boolean" | "object" | "array";

export interface PlatformDefault {
  key: string;
  value: unknown;
  value_schema: ValueSchema;
  description: string | null;
  category: string;
  updated_at: string;
  updated_by: string | null;
}

export async function listPlatformDefaults(): Promise<PlatformDefault[]> {
  const { data } = await apiClient.get<PlatformDefault[]>("/v1/admin/defaults");
  return data;
}

export async function updatePlatformDefault(key: string, value: unknown): Promise<PlatformDefault> {
  const { data } = await apiClient.put<PlatformDefault>(
    `/v1/admin/defaults/${encodeURIComponent(key)}`,
    { value },
  );
  return data;
}
