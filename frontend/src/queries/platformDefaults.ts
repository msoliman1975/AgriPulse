import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listPlatformDefaults,
  updatePlatformDefault,
  type PlatformDefault,
} from "@/api/platformDefaults";

export function usePlatformDefaults() {
  return useQuery({
    queryKey: ["platform_defaults"] as const,
    queryFn: listPlatformDefaults,
    staleTime: 30_000,
  });
}

export function useUpdatePlatformDefault() {
  const qc = useQueryClient();
  return useMutation<PlatformDefault, Error, { key: string; value: unknown }>({
    mutationFn: ({ key, value }) => updatePlatformDefault(key, value),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_defaults"] });
    },
  });
}
