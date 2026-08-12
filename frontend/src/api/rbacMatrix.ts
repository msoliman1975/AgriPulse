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

/**
 * A runtime delta against the shipped YAML default.
 *
 * Only ever present when it *differs* from that default — the API deletes a
 * row that would agree — so "has an override" and "modified" are the same
 * thing and the UI never has to reconstruct the baseline.
 */
export interface RbacOverride {
  capability: string;
  granted: boolean;
  note: string | null;
  updated_at: string | null;
  updated_by: string | null;
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
  /** **Effective** grants — the YAML baseline merged with any override. */
  capabilities: string[];
  capability_count: number;
  active_count: number;
  stub_count: number;
  holders: RbacRoleHolders;
  overrides: RbacOverride[];
  /** PlatformAdmin. Its grants can never be edited — refused server-side. */
  immutable: boolean;
}

export interface RbacMatrix {
  generated_at: string;
  capabilities: RbacCapability[];
  roles: RbacRole[];
  capability_count: number;
  active_count: number;
  stub_count: number;
  /** Whether this caller holds `platform.manage_rbac`. */
  can_manage: boolean;
  /** Upper bound in seconds before a change reaches every API pod. */
  propagation_seconds: number;
}

export type RbacChangeAction = "grant" | "revoke" | "reset";

export interface RbacChange {
  id: number;
  role: string;
  capability: string;
  action: RbacChangeAction;
  previous_effective: boolean;
  new_effective: boolean;
  changed_by: string | null;
  changed_by_email: string | null;
  note: string | null;
  changed_at: string;
}

export interface RbacOverrideResult {
  role: string;
  capability: string;
  baseline: boolean;
  effective: boolean;
  overridden: boolean;
  action: RbacChangeAction;
  unchanged: boolean;
}

/** The whole role x capability matrix in one request. */
export async function getRbacMatrix(): Promise<RbacMatrix> {
  const { data } = await apiClient.get<RbacMatrix>("/v1/admin/rbac/matrix");
  return data;
}

function overridePath(role: string, capability: string): string {
  return `/v1/admin/rbac/roles/${encodeURIComponent(role)}/capabilities/${encodeURIComponent(
    capability,
  )}`;
}

/** Grant or revoke a capability on a role. Needs `platform.manage_rbac`. */
export async function setRbacOverride(args: {
  role: string;
  capability: string;
  granted: boolean;
  note?: string;
}): Promise<RbacOverrideResult> {
  const { data } = await apiClient.put<RbacOverrideResult>(
    overridePath(args.role, args.capability),
    { granted: args.granted, note: args.note ?? null },
  );
  return data;
}

/** Drop the override so the shipped default applies again. */
export async function resetRbacOverride(args: {
  role: string;
  capability: string;
  note?: string;
}): Promise<RbacOverrideResult> {
  const { data } = await apiClient.delete<RbacOverrideResult>(
    overridePath(args.role, args.capability),
    { params: args.note ? { note: args.note } : undefined },
  );
  return data;
}

/** The append-only change trail, newest first. */
export async function getRbacChanges(limit = 200): Promise<RbacChange[]> {
  const { data } = await apiClient.get<RbacChange[]>("/v1/admin/rbac/changes", {
    params: { limit },
  });
  return data;
}
