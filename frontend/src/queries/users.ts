import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type TenantUser,
  type UserInvitePayload,
  type UserInviteResponse,
  type UserUpdatePayload,
  deleteTenantUser,
  inviteTenantUser,
  listTenantUsers,
  reactivateTenantUser,
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
  return useMutation<
    void,
    Error,
    { userId: string; payload: UserUpdatePayload }
  >({
    mutationFn: ({ userId, payload }) => updateTenantUser(userId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant_users"] });
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

export type { TenantUser };
