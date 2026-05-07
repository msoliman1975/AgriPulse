import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type IrrigationApplyPayload,
  type IrrigationSchedule,
  type ListIrrigationSchedulesParams,
  applyOrSkipIrrigation,
  generateIrrigationForBlock,
  listIrrigationSchedules,
} from "@/api/irrigation";

export function useIrrigationSchedules(
  farmId: string | undefined,
  params: ListIrrigationSchedulesParams = {},
) {
  return useQuery({
    queryKey: ["irrigation", "list", farmId, params] as const,
    queryFn: () => listIrrigationSchedules(farmId!, params),
    enabled: Boolean(farmId),
  });
}

export function useApplyOrSkipIrrigation() {
  const qc = useQueryClient();
  return useMutation<
    IrrigationSchedule,
    Error,
    { scheduleId: string; payload: IrrigationApplyPayload }
  >({
    mutationFn: ({ scheduleId, payload }) => applyOrSkipIrrigation(scheduleId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["irrigation"] });
    },
  });
}

export function useGenerateIrrigationForBlock() {
  const qc = useQueryClient();
  return useMutation<IrrigationSchedule | null, Error, { blockId: string; scheduledFor?: string }>({
    mutationFn: ({ blockId, scheduledFor }) => generateIrrigationForBlock(blockId, scheduledFor),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["irrigation"] });
    },
  });
}
