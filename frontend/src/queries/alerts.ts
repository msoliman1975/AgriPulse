import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type Alert,
  type AlertTransitionPayload,
  type ListAlertsParams,
  listAlerts,
  listDefaultRules,
  listRuleOverrides,
  transitionAlert,
  upsertRuleOverride,
  type RuleOverrideUpsertPayload,
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
