import { apiClient } from "./client";
import type { ResolvedSetting } from "./integrations";

export type Category = "weather" | "imagery" | "email" | "webhook";

export interface TenantSettingsBag {
  settings: ResolvedSetting[];
}

const base = (tenantId: string, category: Category): string =>
  `/v1/admin/tenants/${tenantId}/integrations/${category}`;

export async function readTenantIntegration(
  tenantId: string,
  category: Category,
): Promise<TenantSettingsBag> {
  const { data } = await apiClient.get<TenantSettingsBag>(base(tenantId, category));
  return data;
}

export async function writeTenantIntegration(
  tenantId: string,
  category: Category,
  key: string,
  value: unknown,
): Promise<ResolvedSetting> {
  const { data } = await apiClient.put<ResolvedSetting>(
    base(tenantId, category),
    { value },
    { params: { key } },
  );
  return data;
}

export async function clearTenantIntegration(
  tenantId: string,
  category: Category,
  key: string,
): Promise<ResolvedSetting> {
  const { data } = await apiClient.delete<ResolvedSetting>(base(tenantId, category), {
    params: { key },
  });
  return data;
}
