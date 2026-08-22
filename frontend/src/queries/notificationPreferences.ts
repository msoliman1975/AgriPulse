import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchMyNotificationPreferences,
  patchMyNotificationPreferences,
  type MyNotificationPreferences,
  type NotificationPreferencesPatch,
} from "@/api/notificationPreferences";

export const MY_NOTIFICATION_PREFERENCES_KEY = ["me", "notification-preferences"] as const;

export function useMyNotificationPreferences() {
  return useQuery<MyNotificationPreferences>({
    queryKey: MY_NOTIFICATION_PREFERENCES_KEY,
    queryFn: fetchMyNotificationPreferences,
    // These change only when the person changes them here, and the mutation
    // writes the fresh server state straight into the cache. Long is right.
    staleTime: 5 * 60_000,
  });
}

export function useUpdateMyNotificationPreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: NotificationPreferencesPatch) => patchMyNotificationPreferences(patch),
    onSuccess: (fresh) => {
      // The PATCH returns the whole recomputed state, including availability,
      // so seed the cache from the response rather than invalidating. Turning
      // a channel on can change what the server says is deliverable, and a
      // refetch would show the old answer for a moment.
      qc.setQueryData(MY_NOTIFICATION_PREFERENCES_KEY, fresh);
      // The bell reads `notification_channels` through /me, so that copy is
      // now stale.
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
