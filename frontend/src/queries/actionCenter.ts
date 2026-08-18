import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type ActionItemListResponse,
  type ActionItemMembersResponse,
  type DispatchPayload,
  type DispatchResponse,
  type ListActionItemsParams,
  dispatchActionItems,
  listActionItemMembers,
  listActionItems,
} from "@/api/actionCenter";

export function useActionItems(params: ListActionItemsParams | null) {
  return useQuery<ActionItemListResponse>({
    queryKey: ["action_items", params] as const,
    queryFn: () => listActionItems(params as ListActionItemsParams),
    enabled: params !== null,
  });
}

/**
 * The cells behind one aggregated item.
 *
 * Fetched only when a row is actually expanded: a farm-wide queue can hold
 * hundreds of groups, and eagerly loading every membership would trade the
 * request-per-row this feature exists to remove for a different one.
 */
export function useActionItemMembers(farmId: string | null, itemId: string | null) {
  return useQuery<ActionItemMembersResponse>({
    queryKey: ["action_item_members", farmId, itemId] as const,
    queryFn: () => listActionItemMembers(farmId as string, itemId as string),
    enabled: farmId !== null && itemId !== null,
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
      void qc.invalidateQueries({ queryKey: ["action_item_members"] });
      void qc.invalidateQueries({ queryKey: ["recommendations"] });
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      void qc.invalidateQueries({ queryKey: ["board"] });
    },
  });
}
