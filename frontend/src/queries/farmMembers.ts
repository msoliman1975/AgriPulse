import { useQuery } from "@tanstack/react-query";

import { listFarmMembers } from "@/api/farmMembers";

/** Members assignable on this farm. Membership rosters change rarely, so this
 *  is cached long enough that opening the dispatch dialog is instant. */
export function useFarmMembers(farmId: string | null) {
  return useQuery({
    queryKey: ["farm_members", farmId] as const,
    queryFn: () => listFarmMembers(farmId as string),
    enabled: farmId !== null,
    staleTime: 5 * 60_000,
  });
}
