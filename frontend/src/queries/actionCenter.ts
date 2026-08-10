import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ActionItemListResponse,
  type DispatchPayload,
  type DispatchResponse,
  type ListActionItemsParams,
  dispatchActionItems,
  listActionItems,
} from "@/api/actionCenter";

export function useActionItems(params: ListActionItemsParams | null) {
  return useQuery<ActionItemListResponse>({
    queryKey: ["action_items", params] as const,
    queryFn: () => listActionItems(params as ListActionItemsParams),
    enabled: params !== null,
  });
}

export function useDispatchActionItems() {
  const qc = useQueryClient();
  return useMutation<DispatchResponse, Error, { farmId: string; payload: DispatchPayload }>({
    mutationFn: ({ farmId, payload }) => dispatchActionItems(farmId, payload),
    onSuccess: () => {
      // A dispatch writes a board activity and moves the item between tabs, so
      // both queues are stale — invalidating only this screen would leave the
      // board showing a plan that no longer matches.
      void qc.invalidateQueries({ queryKey: ["action_items"] });
      void qc.invalidateQueries({ queryKey: ["recommendations"] });
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      void qc.invalidateQueries({ queryKey: ["board"] });
    },
  });
}
