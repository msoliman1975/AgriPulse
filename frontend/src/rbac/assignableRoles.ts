/**
 * Which roles a tenant administrator may hand out, and how each is granted.
 *
 * Mirrors `backend/app/shared/rbac/check.py` (`TENANT_TIER_ROLES`,
 * `FARM_TIER_ROLES`, `assignment_tier`). The backend builds those from its
 * role enums; this file restates them, so
 * `backend/tests/unit/test_rbac_assignable_roles_parity.py` fails the build
 * if the two ever disagree.
 *
 * Restating rather than fetching is the same trade the capability mirror in
 * `capabilities.ts` makes: the invite form has to render its dropdown before
 * any request completes. The parity test is what makes the trade safe —
 * without it, a role added on the server would simply never appear in the
 * picker, with no error anywhere.
 *
 * PlatformAdmin and PlatformSupport are absent on purpose. They are not
 * assignable from inside a tenant, and the server refuses them with a 422
 * regardless of what is sent.
 */

import type { FarmRole, TenantRole } from "./capabilities";

/** Granted tenant-wide, through `public.tenant_role_assignments`. */
export const TENANT_TIER_ROLES: readonly TenantRole[] = [
  "TenantOwner",
  "TenantAdmin",
  "BillingAdmin",
];

/**
 * Granted one farm at a time, through `public.farm_scopes`.
 *
 * `Viewer` belongs here even though the tenant CHECK constraint accepts it.
 * A tenant-wide Viewer grants nothing: the JWT claim is parsed against the
 * tenant-role enum, which has no Viewer member, so the value is dropped and
 * the member ends up with no capabilities at all.
 */
export const FARM_TIER_ROLES: readonly FarmRole[] = [
  "FarmManager",
  "Agronomist",
  "FieldOperator",
  "Scout",
  "Viewer",
];

export type AssignableRole = TenantRole | FarmRole;

/** Every assignable role, in authority order — tenant tier first. */
export const ASSIGNABLE_ROLES: readonly AssignableRole[] = [
  ...TENANT_TIER_ROLES,
  ...FARM_TIER_ROLES,
];

export type RoleTier = "tenant" | "farm";

/** Which tier grants `role`, and therefore whether it needs farms named. */
export function roleTier(role: string): RoleTier | null {
  if ((TENANT_TIER_ROLES as readonly string[]).includes(role)) return "tenant";
  if ((FARM_TIER_ROLES as readonly string[]).includes(role)) return "farm";
  return null;
}

/** True when picking `role` must be accompanied by at least one farm. */
export function needsFarms(role: string): boolean {
  return roleTier(role) === "farm";
}
