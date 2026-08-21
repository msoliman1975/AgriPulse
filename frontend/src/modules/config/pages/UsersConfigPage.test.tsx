/**
 * The Team & roles screen must offer the same roles the platform defines.
 *
 * The bug this guards: the invite dropdown was a four-element literal in this
 * file while the platform recognised ten roles. Nothing compared the two, so
 * four of the eight assignable roles simply could not be granted, and the
 * screen gave no sign that anything was missing.
 *
 * The backend half of the guard is
 * `backend/tests/unit/test_rbac_assignable_roles_parity.py`, which checks the
 * mirror against the server. This file checks that the rendered control
 * actually uses the mirror.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CursorPage } from "@/api/pagination";
import type { TenantUser } from "@/api/users";
import { setupTestI18n } from "@/i18n/testing";

import { UsersConfigPage } from "./UsersConfigPage";

vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

const listTenantUsers = vi.fn();
const inviteTenantUser = vi.fn();
const assignTenantUserRole = vi.fn();

vi.mock("@/api/users", async () => {
  const actual = await vi.importActual<typeof import("@/api/users")>("@/api/users");
  return {
    ...actual,
    listTenantUsers: () => listTenantUsers(),
    inviteTenantUser: (payload: unknown) => inviteTenantUser(payload),
    assignTenantUserRole: (userId: string, payload: unknown) =>
      assignTenantUserRole(userId, payload),
  };
});

const listFarms = vi.fn();
vi.mock("@/api/farms", async () => {
  const actual = await vi.importActual<typeof import("@/api/farms")>("@/api/farms");
  return { ...actual, listFarms: () => listFarms() };
});

const FARM_A = "11111111-1111-1111-1111-111111111111";
const FARM_B = "22222222-2222-2222-2222-222222222222";

function farmPage(): CursorPage<{ id: string; code: string; name: string }> {
  return {
    items: [
      { id: FARM_A, code: "GF", name: "Green Farm" },
      { id: FARM_B, code: "BF", name: "Blue Farm" },
    ],
    next_cursor: null,
  };
}

function user(overrides: Partial<TenantUser> = {}): TenantUser {
  return {
    id: "user-1",
    email: "sara@example.com",
    identity_kind: "email",
    full_name: "Sara Ahmed",
    phone: null,
    avatar_url: null,
    status: "active",
    last_login_at: null,
    keycloak_subject: "kc-1",
    membership_id: "m-1",
    membership_status: "active",
    joined_at: null,
    tenant_roles: ["TenantAdmin"],
    farm_roles: [],
    preferences: null,
    ...overrides,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UsersConfigPage />
    </QueryClientProvider>,
  );
}

describe("UsersConfigPage roles", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listTenantUsers.mockReset().mockResolvedValue([user()]);
    listFarms.mockReset().mockResolvedValue(farmPage());
    inviteTenantUser.mockReset().mockResolvedValue({
      user_id: "u2",
      membership_id: "m2",
      keycloak_provisioning: "succeeded",
      keycloak_subject: "kc-2",
      keycloak_email_sent: true,
      temporary_password: null,
    });
    assignTenantUserRole.mockReset().mockResolvedValue({
      membership_id: "m-1",
      role: "Agronomist",
      role_tier: "farm",
      farm_ids: [FARM_A],
      revoked: { tenant_roles: ["TenantAdmin"], farm_roles: [] },
    });
  });

  it("offers every assignable role and no platform role", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Invite user" }));

    const select = await screen.findByLabelText("Role");
    const options = within(select)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual([
      "Tenant Owner",
      "Tenant Admin",
      "Billing Admin",
      "Farm Manager",
      "Agronomist",
      "Field Operator",
      "Scout",
      "Viewer",
    ]);
    // The whole point of the allow-list.
    expect(options.join(" ")).not.toMatch(/Platform/);
  });

  it("asks which farms once a farm-tier role is chosen", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Invite user" }));

    // A tenant-tier role applies everywhere, so there is nothing to pick.
    expect(screen.queryByRole("checkbox", { name: /Green Farm/ })).toBeNull();

    await userEvent.selectOptions(await screen.findByLabelText("Role"), "Agronomist");
    expect(await screen.findByRole("checkbox", { name: /Green Farm/ })).toBeTruthy();
  });

  it("will not send a farm-tier invite with no farms picked", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Invite user" }));
    await userEvent.selectOptions(await screen.findByLabelText("Role"), "Scout");

    const submit = screen.getByRole("button", { name: "Send invite" });
    expect(submit).toBeDisabled();
    // Because the server refuses the pair, and a disabled button with no
    // explanation is its own bug.
    expect(screen.getByText("Pick at least one farm for this role.")).toBeTruthy();
  });

  it("sends the farms it was given with a farm-tier invite", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Invite user" }));
    await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Full name"), "New Person");
    await userEvent.selectOptions(await screen.findByLabelText("Role"), "Agronomist");
    await userEvent.click(await screen.findByRole("checkbox", { name: /Green Farm/ }));
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));

    await waitFor(() => expect(inviteTenantUser).toHaveBeenCalled());
    expect(inviteTenantUser.mock.calls[0][0]).toMatchObject({
      email: "new@example.com",
      role: "Agronomist",
      farm_ids: [FARM_A],
    });
  });

  it("sends no farms with a tenant-tier invite", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Invite user" }));
    await userEvent.type(screen.getByLabelText("Email"), "boss@example.com");
    await userEvent.type(screen.getByLabelText("Full name"), "Boss");
    // Pick farms first, then switch tiers: the farms must be cleared, or the
    // server refuses the pair with a 422.
    await userEvent.selectOptions(await screen.findByLabelText("Role"), "Scout");
    await userEvent.click(await screen.findByRole("checkbox", { name: /Green Farm/ }));
    await userEvent.selectOptions(screen.getByLabelText("Role"), "TenantOwner");
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));

    await waitFor(() => expect(inviteTenantUser).toHaveBeenCalled());
    expect(inviteTenantUser.mock.calls[0][0]).toMatchObject({
      role: "TenantOwner",
      farm_ids: [],
    });
  });

  it("names the farm a farm-tier member holds a role on", async () => {
    listTenantUsers.mockResolvedValue([
      user({
        tenant_roles: [],
        farm_roles: [{ farm_id: FARM_B, role: "Scout" }],
      }),
    ]);
    renderPage();
    // Without this the roles column is empty and reads as "no access".
    expect(await screen.findByText("Scout · Blue Farm")).toBeTruthy();
  });

  it("changes an existing member's role", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const roleSelects = await screen.findAllByLabelText("Role");
    await userEvent.selectOptions(roleSelects[0], "Agronomist");
    await userEvent.click(await screen.findByRole("checkbox", { name: /Green Farm/ }));
    await userEvent.click(screen.getByRole("button", { name: "Change role" }));

    await waitFor(() => expect(assignTenantUserRole).toHaveBeenCalled());
    expect(assignTenantUserRole.mock.calls[0][0]).toBe("user-1");
    expect(assignTenantUserRole.mock.calls[0][1]).toMatchObject({
      role: "Agronomist",
      farm_ids: [FARM_A],
    });
  });

  it("does not offer to save a role that has not changed", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByRole("button", { name: "Change role" })).toBeDisabled();
  });
});
