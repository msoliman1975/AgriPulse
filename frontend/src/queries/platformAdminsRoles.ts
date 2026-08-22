import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  invitePlatformAdmin,
  listPlatformAdmins,
  removePlatformAdmin,
  setPlatformAdminAlertEmails,
  type AlertEmailsResponse,
  type InvitePlatformAdminPayload,
  type InvitePlatformAdminResponse,
  type PlatformAdminRow,
  type PlatformRole,
} from "@/api/platformAdminsRoles";

export function usePlatformAdmins() {
  return useQuery({
    queryKey: ["platform_admins_roles"] as const,
    queryFn: listPlatformAdmins,
    staleTime: 30_000,
  });
}

export function useInvitePlatformAdmin() {
  const qc = useQueryClient();
  return useMutation<InvitePlatformAdminResponse, Error, InvitePlatformAdminPayload>({
    mutationFn: invitePlatformAdmin,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins_roles"] });
    },
  });
}

export function useRemovePlatformAdmin() {
  const qc = useQueryClient();
  return useMutation<void, Error, { userId: string; role: PlatformRole }>({
    mutationFn: ({ userId, role }) => removePlatformAdmin(userId, role),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins_roles"] });
    },
  });
}

/**
 * Turn the platform-alert email digest on or off for one admin.
 *
 * No optimistic update. The checkbox decides who is paged when the
 * platform breaks, so it should read what the server stored rather than
 * what the click intended.
 */
export function useSetPlatformAdminAlertEmails() {
  const qc = useQueryClient();
  return useMutation<
    AlertEmailsResponse,
    Error,
    { userId: string; role: PlatformRole; enabled: boolean }
  >({
    mutationFn: ({ userId, role, enabled }) => setPlatformAdminAlertEmails(userId, role, enabled),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins_roles"] });
    },
  });
}

export type { PlatformAdminRow };
