import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type AdminTenant,
  type AdminTenantList,
  type AdminTenantMeta,
  type AdminTenantSidecar,
  type CreateAdminTenantPayload,
  type CreateAdminTenantResponse,
  type ListAdminTenantsParams,
  type PurgeAdminTenantPayload,
  cancelDeleteAdminTenant,
  createAdminTenant,
  getAdminTenant,
  getAdminTenantMeta,
  getAdminTenantSidecar,
  listAdminTenants,
  purgeAdminTenant,
  reactivateAdminTenant,
  requestDeleteAdminTenant,
  retryProvisioningAdminTenant,
  suspendAdminTenant,
} from "@/api/adminTenants";

export const ADMIN_TENANTS_KEY = "admin-tenants" as const;

export function useAdminTenantList(params: ListAdminTenantsParams = {}) {
  return useQuery<AdminTenantList>({
    queryKey: [ADMIN_TENANTS_KEY, "list", params] as const,
    queryFn: () => listAdminTenants(params),
    // Pagination + filtering shouldn't blank the table while a new page
    // loads — keep the previous page visible until the next one resolves.
    placeholderData: keepPreviousData,
  });
}

export function useAdminTenant(tenantId: string | undefined) {
  return useQuery<AdminTenant>({
    queryKey: [ADMIN_TENANTS_KEY, "detail", tenantId] as const,
    queryFn: () => getAdminTenant(tenantId as string),
    enabled: Boolean(tenantId),
  });
}

export function useAdminTenantSidecar(tenantId: string | undefined, auditLimit = 20) {
  return useQuery<AdminTenantSidecar>({
    queryKey: [ADMIN_TENANTS_KEY, "sidecar", tenantId, auditLimit] as const,
    queryFn: () => getAdminTenantSidecar(tenantId as string, auditLimit),
    enabled: Boolean(tenantId),
  });
}

export function useAdminTenantMeta() {
  return useQuery<AdminTenantMeta>({
    queryKey: [ADMIN_TENANTS_KEY, "meta"] as const,
    queryFn: getAdminTenantMeta,
    // Pickers are static enough to cache aggressively.
    staleTime: 5 * 60_000,
  });
}

export function useCreateAdminTenant() {
  const qc = useQueryClient();
  return useMutation<CreateAdminTenantResponse, Error, CreateAdminTenantPayload>({
    mutationFn: createAdminTenant,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [ADMIN_TENANTS_KEY, "list"] });
    },
  });
}

// Lifecycle mutations all share the same cache-bust shape: invalidate
// list + this tenant's detail + sidecar so banners and the audit list
// re-render with the new state.
function makeLifecycleInvalidator(qc: ReturnType<typeof useQueryClient>) {
  return (tenantId: string): void => {
    void qc.invalidateQueries({ queryKey: [ADMIN_TENANTS_KEY, "list"] });
    void qc.invalidateQueries({
      queryKey: [ADMIN_TENANTS_KEY, "detail", tenantId],
    });
    void qc.invalidateQueries({
      queryKey: [ADMIN_TENANTS_KEY, "sidecar", tenantId],
    });
  };
}

export function useSuspendAdminTenant(tenantId: string) {
  const qc = useQueryClient();
  const bust = makeLifecycleInvalidator(qc);
  return useMutation<AdminTenant, Error, { reason: string | null }>({
    mutationFn: ({ reason }) => suspendAdminTenant(tenantId, reason),
    onSuccess: () => bust(tenantId),
  });
}

export function useReactivateAdminTenant(tenantId: string) {
  const qc = useQueryClient();
  const bust = makeLifecycleInvalidator(qc);
  return useMutation<AdminTenant, Error, void>({
    mutationFn: () => reactivateAdminTenant(tenantId),
    onSuccess: () => bust(tenantId),
  });
}

export function useRequestDeleteAdminTenant(tenantId: string) {
  const qc = useQueryClient();
  const bust = makeLifecycleInvalidator(qc);
  return useMutation<AdminTenant, Error, { reason: string | null }>({
    mutationFn: ({ reason }) => requestDeleteAdminTenant(tenantId, reason),
    onSuccess: () => bust(tenantId),
  });
}

export function useCancelDeleteAdminTenant(tenantId: string) {
  const qc = useQueryClient();
  const bust = makeLifecycleInvalidator(qc);
  return useMutation<AdminTenant, Error, void>({
    mutationFn: () => cancelDeleteAdminTenant(tenantId),
    onSuccess: () => bust(tenantId),
  });
}

export function usePurgeAdminTenant(tenantId: string) {
  const qc = useQueryClient();
  return useMutation<void, Error, PurgeAdminTenantPayload>({
    mutationFn: (payload) => purgeAdminTenant(tenantId, payload),
    onSuccess: () => {
      // Tenant is gone — drop the per-tenant caches and refetch the list.
      void qc.invalidateQueries({ queryKey: [ADMIN_TENANTS_KEY, "list"] });
      qc.removeQueries({ queryKey: [ADMIN_TENANTS_KEY, "detail", tenantId] });
      qc.removeQueries({ queryKey: [ADMIN_TENANTS_KEY, "sidecar", tenantId] });
    },
  });
}

export function useRetryProvisioningAdminTenant(tenantId: string) {
  const qc = useQueryClient();
  const bust = makeLifecycleInvalidator(qc);
  return useMutation<AdminTenant, Error, void>({
    mutationFn: () => retryProvisioningAdminTenant(tenantId),
    onSuccess: () => bust(tenantId),
  });
}
