import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import {
  createCrop,
  createStrain,
  createVariety,
  listAdminCrops,
  listAdminStrains,
  listAdminVarieties,
  updateCrop,
  updateStrain,
  updateVariety,
  type CropCreatePayload,
  type CropUpdatePayload,
  type NodeUpdatePayload,
  type VarietyCreatePayload,
} from "@/api/cropCatalog";
import type { Crop, CropVariety, CropVarietyStrain } from "@/api/crops";

// All catalog queries share this prefix so a single mutation can
// invalidate every affected list (crops / varieties / strains) at once.
const ROOT = "cropCatalog";

export function useAdminCrops(includeInactive: boolean): UseQueryResult<Crop[]> {
  return useQuery({
    queryKey: [ROOT, "crops", includeInactive],
    queryFn: () => listAdminCrops(includeInactive),
    staleTime: 30_000,
  });
}

export function useAdminVarieties(
  cropId: string | null,
  includeInactive: boolean,
  enabled: boolean,
): UseQueryResult<CropVariety[]> {
  return useQuery({
    queryKey: [ROOT, "varieties", cropId, includeInactive],
    queryFn: () => listAdminVarieties(cropId as string, includeInactive),
    enabled: Boolean(cropId) && enabled,
    staleTime: 30_000,
  });
}

export function useAdminStrains(
  varietyId: string | null,
  includeInactive: boolean,
  enabled: boolean,
): UseQueryResult<CropVarietyStrain[]> {
  return useQuery({
    queryKey: [ROOT, "strains", varietyId, includeInactive],
    queryFn: () => listAdminStrains(varietyId as string, includeInactive),
    enabled: Boolean(varietyId) && enabled,
    staleTime: 30_000,
  });
}

function useInvalidateCatalog(): () => void {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: [ROOT] });
}

export function useCreateCrop(): UseMutationResult<Crop, Error, CropCreatePayload> {
  const invalidate = useInvalidateCatalog();
  return useMutation({ mutationFn: createCrop, onSuccess: invalidate });
}

export function useUpdateCrop(): UseMutationResult<
  Crop,
  Error,
  { cropId: string; patch: CropUpdatePayload }
> {
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: ({ cropId, patch }) => updateCrop(cropId, patch),
    onSuccess: invalidate,
  });
}

export function useCreateVariety(): UseMutationResult<
  CropVariety,
  Error,
  { cropId: string; payload: VarietyCreatePayload }
> {
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: ({ cropId, payload }) => createVariety(cropId, payload),
    onSuccess: invalidate,
  });
}

export function useUpdateVariety(): UseMutationResult<
  CropVariety,
  Error,
  { varietyId: string; patch: NodeUpdatePayload }
> {
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: ({ varietyId, patch }) => updateVariety(varietyId, patch),
    onSuccess: invalidate,
  });
}

export function useCreateStrain(): UseMutationResult<
  CropVarietyStrain,
  Error,
  { varietyId: string; payload: VarietyCreatePayload }
> {
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: ({ varietyId, payload }) => createStrain(varietyId, payload),
    onSuccess: invalidate,
  });
}

export function useUpdateStrain(): UseMutationResult<
  CropVarietyStrain,
  Error,
  { strainId: string; patch: NodeUpdatePayload }
> {
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: ({ strainId, patch }) => updateStrain(strainId, patch),
    onSuccess: invalidate,
  });
}
