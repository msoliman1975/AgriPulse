// Mirrors backend/app/modules/farms/config_router.py — keep in lock-step.
// Gated by the FARM_CONFIG_TEMPLATE_ENABLED flag on the backend; the
// UI surfaces these routes only behind the Defaults tab.

import { apiClient } from "./client";

export interface ImageryTemplateRow {
  product_id: string;
  cadence_hours: number;
  cloud_cover_max_pct: number | null;
  is_active: boolean;
}

export interface WeatherTemplateRow {
  provider_code: string;
  cadence_hours: number;
  is_active: boolean;
}

export interface SubscriptionsTemplate {
  imagery: ImageryTemplateRow[];
  weather: WeatherTemplateRow[];
}

export interface BlockDiff {
  block_id: string;
  will_add: Record<string, unknown>[];
  will_update: Record<string, unknown>[];
  will_deactivate: Record<string, unknown>[];
  matches: boolean;
}

export interface ApplyPreview {
  imagery: BlockDiff[];
  weather: BlockDiff[];
  total_blocks: number;
  matched_blocks: number;
}

export interface ApplyCounts {
  blocks_touched: number;
  imagery_added: number;
  imagery_updated: number;
  imagery_deactivated: number;
  weather_added: number;
  weather_updated: number;
  weather_deactivated: number;
}

export async function getSubscriptionsTemplate(
  farmId: string,
): Promise<SubscriptionsTemplate> {
  const { data } = await apiClient.get<SubscriptionsTemplate>(
    `/v1/farms/${farmId}/config/subscriptions/template`,
  );
  return data;
}

export async function replaceSubscriptionsTemplate(
  farmId: string,
  body: SubscriptionsTemplate,
): Promise<SubscriptionsTemplate> {
  const { data } = await apiClient.put<SubscriptionsTemplate>(
    `/v1/farms/${farmId}/config/subscriptions/template`,
    body,
  );
  return data;
}

export async function previewApplySubscriptions(
  farmId: string,
  blockIds: string[] | null = null,
): Promise<ApplyPreview> {
  const { data } = await apiClient.post<ApplyPreview>(
    `/v1/farms/${farmId}/config/subscriptions/apply-preview`,
    { block_ids: blockIds },
  );
  return data;
}

export async function applySubscriptions(
  farmId: string,
  blockIds: string[],
): Promise<ApplyCounts> {
  const { data } = await apiClient.post<ApplyCounts>(
    `/v1/farms/${farmId}/config/subscriptions/apply`,
    { block_ids: blockIds },
  );
  return data;
}

// ---------- PR-3: locks ---------------------------------------------------

export type LockCategory = "subscriptions" | "irrigation" | "org";

export interface LockState {
  subscriptions: boolean;
  irrigation: boolean;
  org: boolean;
}

export async function getLocks(farmId: string): Promise<LockState> {
  const { data } = await apiClient.get<LockState>(`/v1/farms/${farmId}/config/locks`);
  return data;
}

export async function lockCategory(
  farmId: string,
  category: LockCategory,
  forceOverwrite: boolean,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post<Record<string, unknown>>(
    `/v1/farms/${farmId}/config/${category}/lock`,
    { force_overwrite: forceOverwrite },
  );
  return data;
}

export async function unlockCategory(
  farmId: string,
  category: LockCategory,
): Promise<void> {
  await apiClient.post(`/v1/farms/${farmId}/config/${category}/unlock`);
}

// ---------- PR-3: irrigation template ------------------------------------

export interface IrrigationTemplate {
  irrigation_system: string | null;
  irrigation_source: string | null;
  flow_rate_m3_per_hour: number | null;
}

export interface SimpleBlockDiff {
  block_id: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  matches: boolean;
}

export interface SimpleApplyPreview {
  blocks: SimpleBlockDiff[];
  total_blocks: number;
  matched_blocks: number;
}

export interface SimpleApplyCounts {
  blocks_touched: number;
  total_blocks: number;
}

export async function getIrrigationTemplate(
  farmId: string,
): Promise<IrrigationTemplate> {
  const { data } = await apiClient.get<IrrigationTemplate>(
    `/v1/farms/${farmId}/config/irrigation/template`,
  );
  return data;
}

export async function putIrrigationTemplate(
  farmId: string,
  body: IrrigationTemplate,
): Promise<IrrigationTemplate> {
  const { data } = await apiClient.put<IrrigationTemplate>(
    `/v1/farms/${farmId}/config/irrigation/template`,
    body,
  );
  return data;
}

export async function previewApplyIrrigation(
  farmId: string,
  blockIds: string[] | null = null,
): Promise<SimpleApplyPreview> {
  const { data } = await apiClient.post<SimpleApplyPreview>(
    `/v1/farms/${farmId}/config/irrigation/apply-preview`,
    { block_ids: blockIds },
  );
  return data;
}

export async function applyIrrigation(
  farmId: string,
  blockIds: string[] | null,
): Promise<SimpleApplyCounts> {
  const { data } = await apiClient.post<SimpleApplyCounts>(
    `/v1/farms/${farmId}/config/irrigation/apply`,
    { block_ids: blockIds },
  );
  return data;
}

// ---------- PR-3: org template ------------------------------------------

export interface OrgTemplate {
  default_tags: string[];
}

export async function getOrgTemplate(farmId: string): Promise<OrgTemplate> {
  const { data } = await apiClient.get<OrgTemplate>(
    `/v1/farms/${farmId}/config/org/template`,
  );
  return data;
}

export async function putOrgTemplate(
  farmId: string,
  body: OrgTemplate,
): Promise<OrgTemplate> {
  const { data } = await apiClient.put<OrgTemplate>(
    `/v1/farms/${farmId}/config/org/template`,
    body,
  );
  return data;
}

export async function previewApplyOrg(
  farmId: string,
  blockIds: string[] | null = null,
): Promise<SimpleApplyPreview> {
  const { data } = await apiClient.post<SimpleApplyPreview>(
    `/v1/farms/${farmId}/config/org/apply-preview`,
    { block_ids: blockIds },
  );
  return data;
}

export async function applyOrg(
  farmId: string,
  blockIds: string[] | null,
): Promise<SimpleApplyCounts> {
  const { data } = await apiClient.post<SimpleApplyCounts>(
    `/v1/farms/${farmId}/config/org/apply`,
    { block_ids: blockIds },
  );
  return data;
}
