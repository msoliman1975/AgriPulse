import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  assignFirstOwner,
  inviteTenantAdmin,
  listTenantAdmins,
  removeTenantAdmin,
  transferTenantOwnership,
  type AssignOwnerPayload,
  type AssignOwnerResponse,
  type InviteAdminPayload,
  type InviteAdminResponse,
  type TenantAdminRow,
} from "@/api/platformAdmins";

export function useTenantAdmins(tenantId: string | undefined) {
  return useQuery({
    queryKey: ["platform_admins", tenantId] as const,
    queryFn: () => listTenantAdmins(tenantId!),
    enabled: Boolean(tenantId),
  });
}

export function useInviteTenantAdmin(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<InviteAdminResponse, Error, InviteAdminPayload>({
    mutationFn: (payload) => inviteTenantAdmin(tenantId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins", tenantId] });
    },
  });
}

export function useRemoveTenantAdmin(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (userId) => removeTenantAdmin(tenantId, userId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins", tenantId] });
    },
  });
}

export function useTransferOwnership(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { newOwnerUserId: string; fromUserId: string }
  >({
    mutationFn: ({ newOwnerUserId, fromUserId }) =>
      transferTenantOwnership(tenantId, newOwnerUserId, fromUserId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins", tenantId] });
    },
  });
}

export function useAssignFirstOwner(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<AssignOwnerResponse, Error, AssignOwnerPayload>({
    mutationFn: (payload) => assignFirstOwner(tenantId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform_admins", tenantId] });
    },
  });
}

export type { AssignOwnerPayload, AssignOwnerResponse, TenantAdminRow };
