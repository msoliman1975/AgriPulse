import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ListRecommendationsParams,
  type Recommendation,
  type RecommendationTransitionPayload,
  listDecisionTrees,
  listRecommendations,
  transitionRecommendation,
} from "@/api/recommendations";

export function useRecommendations(params: ListRecommendationsParams = {}) {
  return useQuery({
    queryKey: ["recommendations", params] as const,
    queryFn: () => listRecommendations(params),
  });
}

export function useTransitionRecommendation() {
  const qc = useQueryClient();
  return useMutation<
    Recommendation,
    Error,
    { recommendationId: string; payload: RecommendationTransitionPayload }
  >({
    mutationFn: ({ recommendationId, payload }) =>
      transitionRecommendation(recommendationId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["recommendations"] });
    },
  });
}

export function useDecisionTrees() {
  return useQuery({
    queryKey: ["decision_trees"] as const,
    queryFn: listDecisionTrees,
    staleTime: 5 * 60_000,
  });
}
