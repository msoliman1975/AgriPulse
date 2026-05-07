import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ActivityCreatePayload,
  type ActivityUpdatePayload,
  type Plan,
  type PlanActivity,
  type PlanCreatePayload,
  archivePlan,
  createActivity,
  createPlan,
  getPlan,
  listActivities,
  listCalendar,
  listPlans,
  updateActivity,
  updatePlan,
  type PlanUpdatePayload,
} from "@/api/plans";

export function usePlans(
  farmId: string | undefined,
  options: { season_year?: number; include_archived?: boolean } = {},
) {
  return useQuery({
    queryKey: ["plans", "list", farmId, options] as const,
    queryFn: () => listPlans(farmId!, options),
    enabled: Boolean(farmId),
  });
}

export function usePlan(planId: string | undefined) {
  return useQuery({
    queryKey: ["plans", "detail", planId] as const,
    queryFn: () => getPlan(planId!),
    enabled: Boolean(planId),
  });
}

export function useActivities(planId: string | undefined) {
  return useQuery({
    queryKey: ["plans", "activities", planId] as const,
    queryFn: () => listActivities(planId!),
    enabled: Boolean(planId),
  });
}

export function useCalendar(
  farmId: string | undefined,
  fromDate: string | undefined,
  toDate: string | undefined,
) {
  return useQuery({
    queryKey: ["plans", "calendar", farmId, fromDate, toDate] as const,
    queryFn: () => listCalendar(farmId!, fromDate!, toDate!),
    enabled: Boolean(farmId && fromDate && toDate),
  });
}

export function useCreatePlan() {
  const qc = useQueryClient();
  return useMutation<Plan, Error, { farmId: string; payload: PlanCreatePayload }>({
    mutationFn: ({ farmId, payload }) => createPlan(farmId, payload),
    onSuccess: (plan) => {
      void qc.invalidateQueries({ queryKey: ["plans", "list", plan.farm_id] });
    },
  });
}

export function useUpdatePlan() {
  const qc = useQueryClient();
  return useMutation<Plan, Error, { planId: string; payload: PlanUpdatePayload }>({
    mutationFn: ({ planId, payload }) => updatePlan(planId, payload),
    onSuccess: (plan) => {
      void qc.invalidateQueries({ queryKey: ["plans", "detail", plan.id] });
      void qc.invalidateQueries({ queryKey: ["plans", "list", plan.farm_id] });
    },
  });
}

export function useArchivePlan() {
  const qc = useQueryClient();
  return useMutation<void, Error, { planId: string; farmId: string }>({
    mutationFn: ({ planId }) => archivePlan(planId),
    onSuccess: (_, { farmId }) => {
      void qc.invalidateQueries({ queryKey: ["plans", "list", farmId] });
    },
  });
}

export function useCreateActivity() {
  const qc = useQueryClient();
  return useMutation<PlanActivity, Error, { planId: string; payload: ActivityCreatePayload }>({
    mutationFn: ({ planId, payload }) => createActivity(planId, payload),
    onSuccess: (activity) => {
      void qc.invalidateQueries({ queryKey: ["plans", "activities", activity.plan_id] });
      void qc.invalidateQueries({ queryKey: ["plans", "calendar"] });
    },
  });
}

export function useUpdateActivity() {
  const qc = useQueryClient();
  return useMutation<PlanActivity, Error, { activityId: string; payload: ActivityUpdatePayload }>({
    mutationFn: ({ activityId, payload }) => updateActivity(activityId, payload),
    onSuccess: (activity) => {
      void qc.invalidateQueries({ queryKey: ["plans", "activities", activity.plan_id] });
      void qc.invalidateQueries({ queryKey: ["plans", "calendar"] });
    },
  });
}
