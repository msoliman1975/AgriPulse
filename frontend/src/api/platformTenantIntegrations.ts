import { apiClient } from "./client";
import type { ResolvedSetting } from "./integrations";

/** `email` + `webhook` were dropped with public migration 0048 — their
 *  keys were inert and the backend no longer accepts those categories.
 *  `recommendations` carries the decision-tree sweep cadence for this
 *  tenant (public migration 0080). */
export type Category = "weather" | "imagery" | "detection" | "recommendations";

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
