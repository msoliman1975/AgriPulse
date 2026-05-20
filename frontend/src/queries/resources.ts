import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createResource,
  listResources,
  updateResource,
  type Resource,
  type ResourceCreatePayload,
  type ResourceKind,
  type ResourceUpdatePayload,
} from "@/api/resources";

export function useResources(
  farmId: string | null,
  options: { kind?: ResourceKind; include_archived?: boolean } = {},
) {
  return useQuery<Resource[]>({
    queryKey: [
      "resources",
      farmId,
      options.kind ?? "any",
      options.include_archived ? "with-archived" : "active",
    ],
    queryFn: () => listResources(farmId as string, options),
    enabled: !!farmId,
    staleTime: 30_000,
  });
}

export function useCreateResource(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ResourceCreatePayload) =>
      createResource(farmId as string, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["resources", farmId] });
    },
  });
}

export function useUpdateResource(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      resourceId,
      payload,
    }: {
      resourceId: string;
      payload: ResourceUpdatePayload;
    }) => updateResource(resourceId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["resources", farmId] });
    },
  });
}
