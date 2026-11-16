import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createHarvestLot,
  deleteHarvestLot,
  listHarvestLots,
  updateHarvestLot,
  type HarvestLot,
  type HarvestLotPayload,
} from "@/api/harvest";

const key = (blockId: string) => ["harvest", "block", blockId] as const;

export function useHarvestLots(blockId: string) {
  return useQuery({ queryKey: key(blockId), queryFn: () => listHarvestLots(blockId) });
}

export function useSaveHarvestLot(blockId: string) {
  const qc = useQueryClient();
  return useMutation<HarvestLot, Error, { lotId: string | null; payload: HarvestLotPayload }>({
    mutationFn: ({ lotId, payload }) =>
      lotId ? updateHarvestLot(lotId, payload) : createHarvestLot(blockId, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: key(blockId) }),
  });
}

export function useDeleteHarvestLot(blockId: string) {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (lotId) => deleteHarvestLot(lotId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: key(blockId) }),
  });
}
