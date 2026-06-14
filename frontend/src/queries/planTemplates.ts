import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  archivePlanTemplate,
  createPlanTemplate,
  deletePlanTemplate,
  getPlanTemplate,
  listPlanTemplates,
  publishPlanTemplate,
  resolveTemplatePhenology,
  updatePlanTemplate,
  type PlanTemplateDetail,
  type PlanTemplateWriteRequest,
  type TemplateStatus,
} from "@/api/planTemplates";

const ROOT = ["plan_templates"] as const;

export function usePlanTemplates(status?: TemplateStatus) {
  return useQuery({
    queryKey: [...ROOT, "list", status ?? "all"] as const,
    queryFn: () => listPlanTemplates(status),
    staleTime: 30_000,
  });
}

export function usePlanTemplate(id: string | null) {
  return useQuery({
    queryKey: [...ROOT, "detail", id] as const,
    queryFn: () => getPlanTemplate(id as string),
    enabled: !!id,
  });
}

export function useTemplatePhenology(cropPath: string | null) {
  return useQuery({
    queryKey: [...ROOT, "phenology", cropPath] as const,
    queryFn: () => resolveTemplatePhenology(cropPath as string),
    enabled: !!cropPath,
    staleTime: 60_000,
  });
}

export function useCreatePlanTemplate() {
  const qc = useQueryClient();
  return useMutation<PlanTemplateDetail, Error, PlanTemplateWriteRequest>({
    mutationFn: (body) => createPlanTemplate(body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ROOT }),
  });
}

export function useUpdatePlanTemplate(id: string) {
  const qc = useQueryClient();
  return useMutation<PlanTemplateDetail, Error, PlanTemplateWriteRequest>({
    mutationFn: (body) => updatePlanTemplate(id, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ROOT }),
  });
}

export function usePublishPlanTemplate() {
  const qc = useQueryClient();
  return useMutation<PlanTemplateDetail, Error, string>({
    mutationFn: (id) => publishPlanTemplate(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ROOT }),
  });
}

export function useArchivePlanTemplate() {
  const qc = useQueryClient();
  return useMutation<PlanTemplateDetail, Error, string>({
    mutationFn: (id) => archivePlanTemplate(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ROOT }),
  });
}

export function useDeletePlanTemplate() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) => deletePlanTemplate(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ROOT }),
  });
}
