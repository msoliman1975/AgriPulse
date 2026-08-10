import type { FarmMember } from "@/api/farmMembers";
import type { TenantUser } from "@/api/users";

export interface AssigneeOption {
  membershipId: string;
  /** This person's role ON THIS FARM, when they have one. Annotation only. */
  role: string | null;
  name: string;
}

/**
 * People who can be dispatched to.
 *
 * Sourced from the **tenant user list**, matching how the block-edit form picks
 * a block's responsible member. Sourcing this from farm membership instead —
 * which is what shipped — meant the two lists could disagree in two ways that
 * both looked like "the dropdown is broken":
 *
 *  - a block owner who was not also a farm member had no matching option, so
 *    the select held a value nothing rendered, and
 *  - a farm with no `farm_scopes` rows produced an empty list even though
 *    assigning a block owner worked perfectly well.
 *
 * `ensureId` is the current default; it is appended when the roster does not
 * contain it, so the selected value always has an option to render — including
 * when the user list failed to load entirely.
 */
export function buildAssigneeOptions(
  users: readonly TenantUser[],
  members: readonly FarmMember[],
  ensureId: string,
): AssigneeOption[] {
  const roleByMembership = new Map(
    members.filter((m) => m.revoked_at === null).map((m) => [m.membership_id, m.role as string]),
  );

  const list: AssigneeOption[] = users.map((u) => ({
    membershipId: u.membership_id,
    role: roleByMembership.get(u.membership_id) ?? null,
    // name → email → short id. A blank option cannot be told from its
    // neighbours and reads as a broken list.
    name: u.full_name || u.email || u.membership_id.slice(0, 8),
  }));

  if (ensureId !== "" && !list.some((o) => o.membershipId === ensureId)) {
    list.push({ membershipId: ensureId, role: null, name: ensureId.slice(0, 8) });
  }

  return list.sort((a, b) => a.name.localeCompare(b.name));
}
