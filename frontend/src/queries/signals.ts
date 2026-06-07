import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ListObservationParams,
  type SignalAssignment,
  type SignalDefinition,
  type SignalDefinitionCreatePayload,
  type SignalDefinitionUpdatePayload,
  type SignalObservation,
  type SignalObservationCreatePayload,
  type SignalTemplate,
  type SignalTemplateCreatePayload,
  type SignalTemplateObservationCreatePayload,
  type SignalTemplateObservationCreateResponse,
  type SignalTemplateUpdatePayload,
  type SignalTemplateWithMembers,
  createSignalAssignment,
  createSignalDefinition,
  createSignalObservation,
  createSignalTemplate,
  createSignalTemplateObservation,
  deleteSignalAssignment,
  deleteSignalDefinition,
  deleteSignalObservation,
  deleteSignalTemplate,
  deleteSignalTemplateObservationGroup,
  getSignalTemplate,
  listSignalAssignments,
  listSignalDefinitions,
  listSignalObservations,
  listSignalTemplates,
  updateSignalDefinition,
  updateSignalTemplate,
} from "@/api/signals";

export function useSignalDefinitions(includeInactive = false) {
  return useQuery({
    queryKey: ["signal_definitions", { includeInactive }] as const,
    queryFn: () => listSignalDefinitions(includeInactive),
    staleTime: 60_000,
  });
}

export function useCreateSignalDefinition() {
  const qc = useQueryClient();
  return useMutation<SignalDefinition, Error, SignalDefinitionCreatePayload>({
    mutationFn: createSignalDefinition,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_definitions"] });
    },
  });
}

export function useUpdateSignalDefinition() {
  const qc = useQueryClient();
  return useMutation<
    SignalDefinition,
    Error,
    { id: string; payload: SignalDefinitionUpdatePayload }
  >({
    mutationFn: ({ id, payload }) => updateSignalDefinition(id, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_definitions"] });
    },
  });
}

export function useDeleteSignalDefinition() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: deleteSignalDefinition,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_definitions"] });
    },
  });
}

export function useSignalAssignments(definitionId: string | undefined) {
  return useQuery({
    queryKey: ["signal_assignments", definitionId] as const,
    queryFn: () => listSignalAssignments(definitionId!),
    enabled: Boolean(definitionId),
  });
}

export function useCreateSignalAssignment() {
  const qc = useQueryClient();
  return useMutation<
    SignalAssignment,
    Error,
    { definitionId: string; payload: { farm_id?: string | null; block_id?: string | null } }
  >({
    mutationFn: ({ definitionId, payload }) => createSignalAssignment(definitionId, payload),
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: ["signal_assignments", vars.definitionId] });
    },
  });
}

export function useDeleteSignalAssignment() {
  const qc = useQueryClient();
  return useMutation<void, Error, { assignmentId: string; definitionId: string }>({
    mutationFn: ({ assignmentId }) => deleteSignalAssignment(assignmentId),
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: ["signal_assignments", vars.definitionId] });
    },
  });
}

export function useSignalObservations(params: ListObservationParams) {
  return useQuery({
    queryKey: ["signal_observations", params] as const,
    queryFn: () => listSignalObservations(params),
    staleTime: 30_000,
  });
}

export function useCreateSignalObservation() {
  const qc = useQueryClient();
  return useMutation<
    SignalObservation,
    Error,
    { definitionId: string; payload: SignalObservationCreatePayload }
  >({
    mutationFn: ({ definitionId, payload }) => createSignalObservation(definitionId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_observations"] });
      void qc.invalidateQueries({ queryKey: ["labs", "map"] });
    },
  });
}

export function useDeleteSignalObservation() {
  const qc = useQueryClient();
  return useMutation<{ deleted: number }, Error, { observationId: string }>({
    mutationFn: ({ observationId }) => deleteSignalObservation(observationId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_observations"] });
      void qc.invalidateQueries({ queryKey: ["labs", "map"] });
    },
  });
}

export function useDeleteSignalTemplateObservationGroup() {
  const qc = useQueryClient();
  return useMutation<{ deleted: number }, Error, { templateObservationId: string }>({
    mutationFn: ({ templateObservationId }) =>
      deleteSignalTemplateObservationGroup(templateObservationId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_observations"] });
      void qc.invalidateQueries({ queryKey: ["labs", "map"] });
    },
  });
}

// ---- CS-9: signal templates -----------------------------------------------

export function useSignalTemplates(includeInactive = false) {
  return useQuery({
    queryKey: ["signal_templates", { includeInactive }] as const,
    queryFn: () => listSignalTemplates(includeInactive),
    staleTime: 60_000,
  });
}

export function useSignalTemplate(templateId: string | undefined) {
  return useQuery({
    queryKey: ["signal_template", templateId] as const,
    queryFn: () => getSignalTemplate(templateId!),
    enabled: Boolean(templateId),
    staleTime: 60_000,
  });
}

export function useCreateSignalTemplate() {
  const qc = useQueryClient();
  return useMutation<SignalTemplateWithMembers, Error, SignalTemplateCreatePayload>({
    mutationFn: createSignalTemplate,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_templates"] });
    },
  });
}

export function useUpdateSignalTemplate() {
  const qc = useQueryClient();
  return useMutation<
    SignalTemplateWithMembers,
    Error,
    { id: string; payload: SignalTemplateUpdatePayload }
  >({
    mutationFn: ({ id, payload }) => updateSignalTemplate(id, payload),
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: ["signal_templates"] });
      void qc.invalidateQueries({ queryKey: ["signal_template", vars.id] });
    },
  });
}

export function useDeleteSignalTemplate() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: deleteSignalTemplate,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_templates"] });
    },
  });
}

export function useCreateTemplateObservation() {
  const qc = useQueryClient();
  return useMutation<
    SignalTemplateObservationCreateResponse,
    Error,
    { templateId: string; payload: SignalTemplateObservationCreatePayload }
  >({
    mutationFn: ({ templateId, payload }) => createSignalTemplateObservation(templateId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signal_observations"] });
      void qc.invalidateQueries({ queryKey: ["labs", "map"] });
    },
  });
}

// Re-export SignalTemplate for callers that import from queries.
export type { SignalTemplate };
