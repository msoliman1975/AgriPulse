import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import {
  createCropAttribute,
  listAdminCropAttributes,
  updateCropAttribute,
  type CropAttributeDefinitionCreate,
  type CropAttributeDefinitionUpdate,
} from "@/api/cropCatalog";
import type { CropAttributeDefinition } from "@/api/crops";

// Shared prefix so one mutation can invalidate every affected list at once,
// matching the cropCatalog queries next door.
const ROOT = "cropAttributeDefinitions";

export function useAdminCropAttributes(
  cropId: string | null,
  includeInactive: boolean,
): UseQueryResult<CropAttributeDefinition[]> {
  return useQuery({
    queryKey: [ROOT, cropId, includeInactive],
    queryFn: () => listAdminCropAttributes(cropId as string, includeInactive),
    enabled: Boolean(cropId),
    staleTime: 30_000,
  });
}

export function useCreateCropAttribute(
  cropId: string,
): UseMutationResult<CropAttributeDefinition, unknown, CropAttributeDefinitionCreate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CropAttributeDefinitionCreate) => createCropAttribute(cropId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [ROOT] });
    },
  });
}

export function useUpdateCropAttribute(): UseMutationResult<
  CropAttributeDefinition,
  unknown,
  { definitionId: string; payload: CropAttributeDefinitionUpdate }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      definitionId,
      payload,
    }: {
      definitionId: string;
      payload: CropAttributeDefinitionUpdate;
    }) => updateCropAttribute(definitionId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [ROOT] });
    },
  });
}
