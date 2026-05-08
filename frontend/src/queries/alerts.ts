import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type Alert,
  type AlertTransitionPayload,
  type ListAlertsParams,
  type RuleOverrideUpsertPayload,
  type TenantRule,
  type TenantRuleCreatePayload,
  type TenantRuleUpdatePayload,
  createTenantRule,
  deleteTenantRule,
  listAlerts,
  listDefaultRules,
  listRuleOverrides,
  listTenantRules,
  transitionAlert,
  updateTenantRule,
  upsertRuleOverride,
} from "@/api/alerts";

export function useAlerts(params: ListAlertsParams = {}) {
  return useQuery({
    queryKey: ["alerts", params] as const,
    queryFn: () => listAlerts(params),
  });
}

export function useTransitionAlert() {
  const qc = useQueryClient();
  return useMutation<Alert, Error, { alertId: string; payload: AlertTransitionPayload }>({
    mutationFn: ({ alertId, payload }) => transitionAlert(alertId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}

export function useDefaultRules() {
  return useQuery({
    queryKey: ["alert_rules", "defaults"] as const,
    queryFn: listDefaultRules,
    staleTime: 5 * 60_000,
  });
}

export function useRuleOverrides() {
  return useQuery({
    queryKey: ["alert_rules", "overrides"] as const,
    queryFn: listRuleOverrides,
  });
}

export function useUpsertRuleOverride() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { ruleCode: string; payload: RuleOverrideUpsertPayload }>({
    mutationFn: ({ ruleCode, payload }) => upsertRuleOverride(ruleCode, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alert_rules", "overrides"] });
    },
  });
}

export function useTenantRules() {
  return useQuery({
    queryKey: ["alert_rules", "tenant"] as const,
    queryFn: listTenantRules,
    staleTime: 30_000,
  });
}

export function useCreateTenantRule() {
  const qc = useQueryClient();
  return useMutation<TenantRule, Error, TenantRuleCreatePayload>({
    mutationFn: createTenantRule,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alert_rules", "tenant"] });
    },
  });
}

export function useUpdateTenantRule() {
  const qc = useQueryClient();
  return useMutation<
    TenantRule,
    Error,
    { code: string; payload: TenantRuleUpdatePayload }
  >({
    mutationFn: ({ code, payload }) => updateTenantRule(code, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alert_rules", "tenant"] });
    },
  });
}

export function useDeleteTenantRule() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: deleteTenantRule,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alert_rules", "tenant"] });
    },
  });
}
