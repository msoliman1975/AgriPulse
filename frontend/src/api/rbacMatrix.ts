import { apiClient } from "@/api/client";

/** platform | tenant | farm — the JWT layer a capability or role belongs to. */
export type RbacTier = "platform" | "tenant" | "farm";

/** `active` = enforced by a route today. `stub` = reserved, currently inert. */
export type CapabilityStatus = "active" | "stub";

export interface RbacCapability {
  name: string;
  /** Noun before the dot, computed server-side. */
  resource: string;
  action: string;
  description: string;
  scope: RbacTier;
  status: CapabilityStatus;
}

export interface RbacRoleHolders {
  total: number;
  platform: number;
  tenant: number;
  farm: number;
}

export interface RbacRole {
  name: string;
  tier: RbacTier;
  description: string;
  /**
   * True only for PlatformAdmin. `capabilities` is already expanded to every
   * known name, so the UI filters uniformly; this flag drives the badge.
   */
  wildcard: boolean;
  capabilities: string[];
  capability_count: number;
  active_count: number;
  stub_count: number;
  holders: RbacRoleHolders;
}

export interface RbacMatrix {
  generated_at: string;
  capabilities: RbacCapability[];
  roles: RbacRole[];
  capability_count: number;
  active_count: number;
  stub_count: number;
}

/** The whole role x capability matrix in one request. */
export async function getRbacMatrix(): Promise<RbacMatrix> {
  const { data } = await apiClient.get<RbacMatrix>("/v1/admin/rbac/matrix");
  return data;
}
