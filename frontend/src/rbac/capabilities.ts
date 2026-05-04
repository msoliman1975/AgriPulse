// Mirrors backend `app/shared/rbac/role_capabilities.yaml` for the
// capabilities the frontend gates UI on. Adding a new gated capability
// here without adding it to the backend is a no-op (backend will deny).

export type Capability =
  | "farm.read"
  | "farm.create"
  | "farm.update"
  | "farm.delete"
  | "farm.member.read"
  | "role.assign_farm"
  | "block.read"
  | "block.create"
  | "block.update_geometry"
  | "block.update_metadata"
  | "block.delete"
  | "crop_assignment.create"
  | "crop_assignment.update"
  | "crop_assignment.delete"
  | "farm.attachment.read"
  | "farm.attachment.write"
  | "block.attachment.read"
  | "block.attachment.write"
  | "imagery.read"
  | "imagery.refresh"
  | "imagery.subscription.manage"
  | "index.read"
  | "index.compute_custom";

export type PlatformRole = "PlatformAdmin" | "PlatformSupport";
export type TenantRole = "TenantOwner" | "TenantAdmin" | "BillingAdmin";
export type FarmRole = "FarmManager" | "Agronomist" | "FieldOperator" | "Scout" | "Viewer";

// Subset of role → capabilities relevant for the farms UI. Mirrors the
// yaml — kept narrow to what the UI actually checks. Wildcard handled
// in the resolver.
export const ROLE_CAPABILITIES: Record<string, ReadonlySet<Capability | "*">> = {
  PlatformAdmin: new Set<Capability | "*">(["*"]),
  PlatformSupport: new Set<Capability>([
    "farm.read",
    "farm.member.read",
    "block.read",
    "imagery.read",
    "index.read",
  ]),
  TenantOwner: tenantWideCaps(),
  TenantAdmin: tenantWideCaps(),
  FarmManager: new Set<Capability>([
    "role.assign_farm",
    "farm.read",
    "farm.update",
    "farm.member.read",
    "farm.attachment.read",
    "farm.attachment.write",
    "block.read",
    "block.create",
    "block.update_geometry",
    "block.update_metadata",
    "block.delete",
    "block.attachment.read",
    "block.attachment.write",
    "crop_assignment.create",
    "crop_assignment.update",
    "crop_assignment.delete",
    "imagery.read",
    "imagery.refresh",
    "imagery.subscription.manage",
    "index.read",
    "index.compute_custom",
  ]),
  Agronomist: new Set<Capability>([
    "farm.read",
    "farm.attachment.read",
    "block.read",
    "block.attachment.read",
    "crop_assignment.update",
    "imagery.read",
    "imagery.refresh",
    "index.read",
    "index.compute_custom",
  ]),
  FieldOperator: new Set<Capability>([
    "farm.read",
    "farm.attachment.read",
    "farm.attachment.write",
    "block.read",
    "block.attachment.read",
    "block.attachment.write",
    "imagery.read",
    "index.read",
  ]),
  Scout: new Set<Capability>([
    "farm.read",
    "farm.attachment.read",
    "block.read",
    "block.attachment.read",
    "imagery.read",
    "index.read",
  ]),
  Viewer: new Set<Capability>([
    "farm.read",
    "farm.attachment.read",
    "block.read",
    "block.attachment.read",
    "imagery.read",
    "index.read",
  ]),
};

function tenantWideCaps(): ReadonlySet<Capability> {
  return new Set<Capability>([
    "role.assign_farm",
    "farm.read",
    "farm.create",
    "farm.update",
    "farm.delete",
    "farm.member.read",
    "farm.attachment.read",
    "farm.attachment.write",
    "block.read",
    "block.create",
    "block.update_geometry",
    "block.update_metadata",
    "block.delete",
    "block.attachment.read",
    "block.attachment.write",
    "crop_assignment.create",
    "crop_assignment.update",
    "crop_assignment.delete",
    "imagery.read",
    "imagery.refresh",
    "imagery.subscription.manage",
    "index.read",
    "index.compute_custom",
  ]);
}

export function roleGrants(role: string, cap: Capability): boolean {
  const set = ROLE_CAPABILITIES[role];
  if (!set) return false;
  if (set.has("*")) return true;
  return set.has(cap);
}
