import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  invitePlatformAdmin,
  listPlatformAdmins,
  removePlatformAdmin,
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
  return useMutation<
    InvitePlatformAdminResponse,
    Error,
    InvitePlatformAdminPayload
  >({
    mutationFn: invitePlatformAdmin,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins_roles"] });
    },
  });
}

export function useRemovePlatformAdmin() {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { userId: string; role: PlatformRole }
  >({
    mutationFn: ({ userId, role }) => removePlatformAdmin(userId, role),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins_roles"] });
    },
  });
}

export type { PlatformAdminRow };
