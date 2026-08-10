import { describe, expect, it } from "vitest";

import type { FarmMember } from "@/api/farmMembers";
import type { TenantUser } from "@/api/users";
import { buildAssigneeOptions } from "@/modules/actionCenter/lib/assigneeOptions";

const user = (over: Partial<TenantUser>): TenantUser =>
  ({
    id: "u",
    email: "u@x.test",
    full_name: "User",
    phone: null,
    avatar_url: null,
    status: "active",
    last_login_at: null,
    keycloak_subject: null,
    membership_id: "m",
    membership_status: "active",
    joined_at: null,
    tenant_roles: [],
    ...over,
  }) as TenantUser;

const member = (over: Partial<FarmMember>): FarmMember => ({
  id: "fs",
  membership_id: "m",
  farm_id: "f",
  role: "Scout",
  granted_at: "2026-01-01T00:00:00Z",
  revoked_at: null,
  ...over,
});

describe("buildAssigneeOptions", () => {
  it("lists tenant users, not just farm members", () => {
    // The shipped bug: a farm with no farm_scopes rows produced an empty
    // dropdown even though assigning a block owner worked fine.
    const opts = buildAssigneeOptions(
      [user({ membership_id: "m1", full_name: "Ahmed Hassan" })],
      [],
      "",
    );
    expect(opts.map((o) => o.membershipId)).toEqual(["m1"]);
    expect(opts[0].name).toBe("Ahmed Hassan");
  });

  it("annotates a person with their role on this farm", () => {
    const opts = buildAssigneeOptions(
      [user({ membership_id: "m1", full_name: "Mona" })],
      [member({ membership_id: "m1", role: "Agronomist" })],
      "",
    );
    expect(opts[0].role).toBe("Agronomist");
  });

  it("leaves the role null for someone with no farm scope", () => {
    // They are still dispatchable — the block-edit form would happily make
    // them a block's responsible member.
    const opts = buildAssigneeOptions([user({ membership_id: "m9", full_name: "Karim" })], [], "");
    expect(opts[0].role).toBeNull();
  });

  it("ignores a revoked farm membership when annotating", () => {
    const opts = buildAssigneeOptions(
      [user({ membership_id: "m1", full_name: "Mona" })],
      [member({ membership_id: "m1", role: "Scout", revoked_at: "2026-02-01T00:00:00Z" })],
      "",
    );
    expect(opts[0].role).toBeNull();
  });

  it("guarantees the current default is selectable even if absent from the roster", () => {
    // Otherwise the select holds a value with no matching option and renders
    // blank — indistinguishable from "nothing is selected".
    const opts = buildAssigneeOptions([user({ membership_id: "m1" })], [], "m-missing");
    expect(opts.map((o) => o.membershipId)).toContain("m-missing");
  });

  it("does not inject an option when there is no default", () => {
    const opts = buildAssigneeOptions([user({ membership_id: "m1" })], [], "");
    expect(opts).toHaveLength(1);
  });

  it("does not duplicate the default when it is already present", () => {
    const opts = buildAssigneeOptions([user({ membership_id: "m1", full_name: "A" })], [], "m1");
    expect(opts.filter((o) => o.membershipId === "m1")).toHaveLength(1);
  });

  it("falls back through name to email to id", () => {
    const opts = buildAssigneeOptions(
      [
        user({ membership_id: "m1", full_name: "", email: "scout@farm.test" }),
        user({ membership_id: "m2-longidhere", full_name: "", email: "" }),
      ],
      [],
      "",
    );
    const byId = new Map(opts.map((o) => [o.membershipId, o.name]));
    expect(byId.get("m1")).toBe("scout@farm.test");
    expect(byId.get("m2-longidhere")).toBe("m2-longi");
  });

  it("sorts by name so the list is scannable", () => {
    const opts = buildAssigneeOptions(
      [
        user({ membership_id: "m1", full_name: "Youssef" }),
        user({ membership_id: "m2", full_name: "Ahmed" }),
      ],
      [],
      "",
    );
    expect(opts.map((o) => o.name)).toEqual(["Ahmed", "Youssef"]);
  });
});
