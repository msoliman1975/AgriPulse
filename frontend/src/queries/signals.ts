import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ListObservationParams,
  type SignalAssignment,
  type SignalDefinition,
  type SignalDefinitionCreatePayload,
  type SignalDefinitionUpdatePayload,
  type SignalObservation,
  type SignalObservationCreatePayload,
  createSignalAssignment,
  createSignalDefinition,
  createSignalObservation,
  deleteSignalAssignment,
  deleteSignalDefinition,
  listSignalAssignments,
  listSignalDefinitions,
  listSignalObservations,
  updateSignalDefinition,
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
    },
  });
}
