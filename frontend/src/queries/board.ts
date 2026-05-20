import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  bulkCreateActivities,
  createFlatActivity,
  getBoard,
  type BoardResponse,
  type BulkActivityCreatePayload,
  type FlatActivityCreatePayload,
} from "@/api/plans";
import { attachResource, detachResource } from "@/api/resources";

export function boardQueryKey(
  farmId: string | null,
  weekStart: string,
  weeks: number,
) {
  return ["board", farmId, weekStart, weeks] as const;
}

export function useBoard(
  farmId: string | null,
  weekStart: string,
  weeks = 8,
) {
  return useQuery<BoardResponse>({
    queryKey: boardQueryKey(farmId, weekStart, weeks),
    queryFn: () => getBoard(farmId as string, weekStart, weeks),
    enabled: !!farmId,
    staleTime: 15_000,
  });
}

export function useCreateFlatActivity(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: FlatActivityCreatePayload) =>
      createFlatActivity(farmId as string, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["board", farmId] });
    },
  });
}

export function useBulkCreateActivities(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: BulkActivityCreatePayload) =>
      bulkCreateActivities(farmId as string, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["board", farmId] });
    },
  });
}

export function useAttachResource(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      activityId,
      resourceId,
    }: {
      activityId: string;
      resourceId: string;
    }) => attachResource(activityId, resourceId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["board", farmId] });
    },
  });
}

export function useDetachResource(farmId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      activityId,
      resourceId,
    }: {
      activityId: string;
      resourceId: string;
    }) => detachResource(activityId, resourceId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["board", farmId] });
    },
  });
}
