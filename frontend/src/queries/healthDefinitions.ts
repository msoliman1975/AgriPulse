import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import {
  getCropPathHealth,
  getPlatformHealthDefinition,
  listCropHealthDefinitions,
  putCropPathHealth,
  putPlatformHealthDefinition,
  type CropHealthDefinition,
  type CropPathHealth,
  type HealthBody,
  type PlatformHealthDefinition,
} from "@/api/healthDefinitions";
import { updatePlatformDefault } from "@/api/platformDefaults";

// One prefix for both tiers: a platform save changes what every crop path
// inherits, so it has to refresh the crop views too.
const ROOT = "healthDefinitions";

export function usePlatformHealthDefinition(): UseQueryResult<PlatformHealthDefinition> {
  return useQuery({ queryKey: [ROOT, "platform"], queryFn: getPlatformHealthDefinition });
}

export function useCropHealthDefinitions(): UseQueryResult<CropHealthDefinition[]> {
  return useQuery({ queryKey: [ROOT, "crops"], queryFn: listCropHealthDefinitions });
}

export function useCropPathHealth(cropPath: string): UseQueryResult<CropPathHealth> {
  return useQuery({
    queryKey: [ROOT, "crop", cropPath],
    queryFn: () => getCropPathHealth(cropPath),
  });
}

export function useSavePlatformHealthDefinition(): UseMutationResult<
  PlatformHealthDefinition,
  unknown,
  { definition: HealthBody; notes: string | null }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ definition, notes }) => putPlatformHealthDefinition(definition, notes),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [ROOT] }),
  });
}

/** The platform rollup rule is a platform default; saving it moves what
 *  every crop path inherits, so the health views refresh too. */
export function useSavePlatformRollup(): UseMutationResult<
  unknown,
  unknown,
  { key: string; value: unknown }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }) => updatePlatformDefault(key, value),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [ROOT] });
      void qc.invalidateQueries({ queryKey: ["platform_defaults"] });
    },
  });
}

export function useSaveCropPathHealth(
  cropPath: string,
): UseMutationResult<CropPathHealth, unknown, { definition: HealthBody; notes: string | null }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ definition, notes }) => putCropPathHealth(cropPath, definition, notes),
    // Every path below this one inherits from it, so refresh them all.
    onSuccess: () => void qc.invalidateQueries({ queryKey: [ROOT] }),
  });
}
