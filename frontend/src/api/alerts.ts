// Mirrors backend/app/modules/alerts/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export type AlertSeverity = "info" | "warning" | "critical";
export type AlertStatus = "open" | "acknowledged" | "resolved" | "snoozed";

export interface Alert {
  id: string;
  block_id: string;
  rule_code: string;
  severity: AlertSeverity;
  status: AlertStatus;
  diagnosis_en: string | null;
  diagnosis_ar: string | null;
  prescription_en: string | null;
  prescription_ar: string | null;
  prescription_activity_id: string | null;
  signal_snapshot: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  snoozed_until: string | null;
}

export interface DefaultRule {
  code: string;
  name_en: string;
  name_ar: string | null;
  description_en: string | null;
  description_ar: string | null;
  severity: AlertSeverity;
  status: "active" | "draft" | "retired";
  applies_to_crop_categories: string[];
  conditions: Record<string, unknown>;
  actions: Record<string, unknown>;
  version: number;
}

export interface RuleOverride {
  id: string;
  rule_code: string;
  modified_conditions: Record<string, unknown> | null;
  modified_actions: Record<string, unknown> | null;
  modified_severity: AlertSeverity | null;
  is_disabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ListAlertsParams {
  block_id?: string;
  status?: AlertStatus;
  severity?: AlertSeverity;
  limit?: number;
}

export async function listAlerts(params: ListAlertsParams = {}): Promise<Alert[]> {
  const { data } = await apiClient.get<Alert[]>("/v1/alerts", { params });
  return data;
}

export interface AlertTransitionPayload {
  acknowledge?: boolean;
  resolve?: boolean;
  snooze_until?: string | null;
  notes?: string | null;
}

export async function transitionAlert(
  alertId: string,
  payload: AlertTransitionPayload,
): Promise<Alert> {
  const { data } = await apiClient.patch<Alert>(`/v1/alerts/${alertId}`, payload);
  return data;
}

export async function listDefaultRules(): Promise<DefaultRule[]> {
  const { data } = await apiClient.get<DefaultRule[]>("/v1/rules/defaults");
  return data;
}

export async function listRuleOverrides(): Promise<RuleOverride[]> {
  const { data } = await apiClient.get<RuleOverride[]>("/v1/rules/overrides");
  return data;
}

export interface RuleOverrideUpsertPayload {
  modified_conditions?: Record<string, unknown> | null;
  modified_actions?: Record<string, unknown> | null;
  modified_severity?: AlertSeverity | null;
  is_disabled?: boolean;
}

export async function upsertRuleOverride(
  ruleCode: string,
  payload: RuleOverrideUpsertPayload,
): Promise<RuleOverride> {
  const { data } = await apiClient.put<RuleOverride>(`/v1/rules/overrides/${ruleCode}`, payload);
  return data;
}

export async function evaluateBlock(
  blockId: string,
): Promise<{ block_id: string; alerts_opened: number; rules_evaluated: number }> {
  const { data } = await apiClient.post<{
    block_id: string;
    alerts_opened: number;
    rules_evaluated: number;
    rules_skipped_disabled: number;
  }>(`/v1/blocks/${blockId}/alerts:evaluate`);
  return data;
}

// --- Tenant-authored rules ------------------------------------------------

export interface TenantRule {
  id: string;
  code: string;
  name_en: string;
  name_ar: string | null;
  description_en: string | null;
  description_ar: string | null;
  severity: AlertSeverity;
  status: "active" | "draft" | "retired";
  applies_to_crop_categories: string[];
  conditions: Record<string, unknown>;
  actions: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface TenantRuleCreatePayload {
  code: string;
  name_en: string;
  name_ar?: string | null;
  description_en?: string | null;
  description_ar?: string | null;
  severity?: AlertSeverity;
  applies_to_crop_categories?: string[];
  conditions: Record<string, unknown>;
  actions: Record<string, unknown>;
}

export interface TenantRuleUpdatePayload {
  name_en?: string;
  name_ar?: string | null;
  description_en?: string | null;
  description_ar?: string | null;
  severity?: AlertSeverity;
  status?: "active" | "draft" | "retired";
  applies_to_crop_categories?: string[];
  conditions?: Record<string, unknown>;
  actions?: Record<string, unknown>;
}

export async function listTenantRules(): Promise<TenantRule[]> {
  const { data } = await apiClient.get<TenantRule[]>("/v1/rules/tenant");
  return data;
}

export async function createTenantRule(payload: TenantRuleCreatePayload): Promise<TenantRule> {
  const { data } = await apiClient.post<TenantRule>("/v1/rules/tenant", payload);
  return data;
}

export async function updateTenantRule(
  code: string,
  payload: TenantRuleUpdatePayload,
): Promise<TenantRule> {
  const { data } = await apiClient.patch<TenantRule>(`/v1/rules/tenant/${code}`, payload);
  return data;
}

export async function deleteTenantRule(code: string): Promise<void> {
  await apiClient.delete(`/v1/rules/tenant/${code}`);
}
