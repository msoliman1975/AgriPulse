import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type TenantUser,
  type UserRoleAssignPayload,
  type UserRoleAssignResponse,
  type UserInvitePayload,
  type UserInviteResponse,
  type UserResendInviteResponse,
  type UserUpdatePayload,
  assignTenantUserRole,
  deleteTenantUser,
  inviteTenantUser,
  listTenantUsers,
  reactivateTenantUser,
  resendTenantUserInvite,
  suspendTenantUser,
  updateTenantUser,
} from "@/api/users";

export function useTenantUsers() {
  return useQuery({
    queryKey: ["tenant_users", "list"] as const,
    queryFn: listTenantUsers,
    staleTime: 30_000,
  });
}

export function useInviteTenantUser() {
  const qc = useQueryClient();
  return useMutation<UserInviteResponse, Error, UserInvitePayload>({
    mutationFn: inviteTenantUser,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant_users"] });
    },
  });
}

export function useUpdateTenantUser() {
  const qc = useQueryClient();
  return useMutation<void, Error, { userId: string; payload: UserUpdatePayload }>({
    mutationFn: ({ userId, payload }) => updateTenantUser(userId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant_users"] });
    },
  });
}

export function useAssignTenantUserRole() {
  const qc = useQueryClient();
  return useMutation<
    UserRoleAssignResponse,
    Error,
    { userId: string; payload: UserRoleAssignPayload }
  >({
    mutationFn: ({ userId, payload }) => assignTenantUserRole(userId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant_users"] });
      // A farm-tier grant writes farm_scopes, which is what the farm
      // members list reads. Without this the member appears in Team & roles
      // and is missing from the farm they were just given.
      void qc.invalidateQueries({ queryKey: ["farm_members"] });
    },
  });
}

export function useSuspendTenantUser() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: suspendTenantUser,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant_users"] });
    },
  });
}

export function useReactivateTenantUser() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: reactivateTenantUser,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant_users"] });
    },
  });
}

export function useDeleteTenantUser() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: deleteTenantUser,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant_users"] });
    },
  });
}

export function useResendTenantUserInvite() {
  const qc = useQueryClient();
  return useMutation<UserResendInviteResponse, Error, string>({
    mutationFn: resendTenantUserInvite,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant_users"] });
    },
  });
}

export type { TenantUser };
