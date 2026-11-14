import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createSavedPlan,
  deleteSavedPlan,
  getAuthoringManual,
  getFarmManual,
  getManualChanges,
  getPublishImpact,
  getSavedPlan,
  listManualCatalog,
  listSavedPlans,
  previewSavedPlan,
  updateSavedPlan,
  type AllocationWriteRequest,
} from "@/api/agriOperation";

const ROOT = ["agri_operation"] as const;

export function useManualCatalog(farmId: string | null) {
  return useQuery({
    queryKey: [...ROOT, "catalog", farmId] as const,
    queryFn: () => listManualCatalog(farmId as string),
    enabled: !!farmId,
    staleTime: 60_000,
  });
}

export function useFarmManual(farmId: string | null, templateId: string | null) {
  return useQuery({
    queryKey: [...ROOT, "manual", farmId, templateId] as const,
    queryFn: () => getFarmManual(farmId as string, templateId as string),
    enabled: !!farmId && !!templateId,
    staleTime: 60_000,
  });
}

export function useAuthoringManual(templateId: string | null) {
  return useQuery({
    queryKey: [...ROOT, "authoring", templateId] as const,
    queryFn: () => getAuthoringManual(templateId as string),
    enabled: !!templateId,
  });
}

export function usePublishImpact(templateId: string | null, enabled = true) {
  return useQuery({
    queryKey: [...ROOT, "publish_impact", templateId] as const,
    queryFn: () => getPublishImpact(templateId as string),
    enabled: !!templateId && enabled,
  });
}

export function useSavedPlans(farmId: string | null) {
  return useQuery({
    queryKey: [...ROOT, "saved", farmId] as const,
    queryFn: () => listSavedPlans(farmId as string),
    enabled: !!farmId,
  });
}

export function useSavedPlan(farmId: string | null, id: string | null) {
  return useQuery({
    queryKey: [...ROOT, "saved", farmId, id] as const,
    queryFn: () => getSavedPlan(farmId as string, id as string),
    enabled: !!farmId && !!id,
  });
}

export function useManualChanges(farmId: string | null, id: string | null, enabled = true) {
  return useQuery({
    queryKey: [...ROOT, "manual_changes", farmId, id] as const,
    queryFn: () => getManualChanges(farmId as string, id as string),
    enabled: !!farmId && !!id && enabled,
  });
}

export function usePreviewSavedPlan(farmId: string | null, body: AllocationWriteRequest | null) {
  return useQuery({
    queryKey: [...ROOT, "preview", farmId, body] as const,
    queryFn: () => previewSavedPlan(farmId as string, body as AllocationWriteRequest),
    enabled: !!farmId && !!body && body.blocks.length > 0,
  });
}

export function useSaveSavedPlan(farmId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string | null; body: AllocationWriteRequest }) =>
      id ? updateSavedPlan(farmId, id, body) : createSavedPlan(farmId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...ROOT, "saved", farmId] });
      // The board reads plan activities; a save rewrites them.
      void qc.invalidateQueries({ queryKey: ["board"] });
      void qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
}

export function useDeleteSavedPlan(farmId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteSavedPlan(farmId, id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...ROOT, "saved", farmId] });
      void qc.invalidateQueries({ queryKey: ["board"] });
      void qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
}
