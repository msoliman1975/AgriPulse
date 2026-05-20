import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  scheduleRecommendation,
  type ScheduleRecommendationPayload,
} from "@/api/recommendations";

export function useScheduleRecommendation(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      recommendationId,
      payload,
    }: {
      recommendationId: string;
      payload: ScheduleRecommendationPayload;
    }) => scheduleRecommendation(recommendationId, payload),
    onSuccess: () => {
      // Both the open-rec list and the board grid need to refresh.
      void qc.invalidateQueries({
        queryKey: ["recommendations", "open", farmId],
      });
      void qc.invalidateQueries({ queryKey: ["board", farmId] });
    },
  });
}
