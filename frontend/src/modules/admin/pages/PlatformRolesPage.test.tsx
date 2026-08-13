import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RbacMatrix } from "@/api/rbacMatrix";
import { setupTestI18n } from "@/i18n/testing";

import { PlatformRolesPage } from "./PlatformRolesPage";

const matrix: RbacMatrix = {
  generated_at: "2026-08-11T00:00:00Z",
  capability_count: 4,
  active_count: 3,
  stub_count: 1,
  // Read-only by default, so every Phase 1 assertion below still describes the
  // view a user without `platform.manage_rbac` gets. The editing tests build
  // their own matrix rather than flipping this.
  can_manage: false,
  propagation_seconds: 30,
  capabilities: [
    {
      name: "farm.read",
      resource: "farm",
      action: "read",
      description: "View farm metadata.",
      scope: "farm",
      status: "active",
    },
    {
      name: "farm.delete",
      resource: "farm",
      action: "delete",
      description: "Soft-archive a farm.",
      scope: "farm",
      status: "active",
    },
    {
      name: "subscription.manage",
      resource: "subscription",
      action: "manage",
      description: "Change plan or payment method.",
      scope: "tenant",
      status: "active",
    },
    {
      name: "analytics.export",
      resource: "analytics",
      action: "export",
      description: "Export analytics extracts.",
      scope: "tenant",
      status: "stub",
    },
  ],
  roles: [
    {
      name: "PlatformAdmin",
      tier: "platform",
      description: "AgriPulse staff with full cross-tenant control.",
      wildcard: true,
      capabilities: ["farm.read", "farm.delete", "subscription.manage", "analytics.export"],
      capability_count: 4,
      active_count: 3,
      stub_count: 1,
      holders: { total: 2, platform: 2, tenant: 0, farm: 0 },
      overrides: [],
      immutable: true,
    },
    {
      name: "BillingAdmin",
      tier: "tenant",
      description: "Subscription and billing only.",
      wildcard: false,
      capabilities: ["subscription.manage"],
      capability_count: 1,
      active_count: 1,
      stub_count: 0,
      holders: { total: 7, platform: 0, tenant: 7, farm: 0 },
      overrides: [],
      immutable: false,
    },
    {
      name: "Viewer",
      tier: "farm",
      description: "Read-only view of an assigned farm.",
      wildcard: false,
      capabilities: ["farm.read"],
      capability_count: 1,
      active_count: 1,
      stub_count: 0,
      holders: { total: 3, platform: 0, tenant: 1, farm: 2 },
      overrides: [],
      immutable: false,
    },
  ],
};

const getRbacMatrix = vi.fn(() => Promise.resolve(matrix));
const setRbacOverride = vi.fn();
const resetRbacOverride = vi.fn();
const getRbacChanges = vi.fn();

vi.mock("@/api/rbacMatrix", async () => {
  const actual = await vi.importActual<typeof import("@/api/rbacMatrix")>("@/api/rbacMatrix");
  return {
    ...actual,
    getRbacMatrix: () => getRbacMatrix(),
    setRbacOverride: (args: unknown) => setRbacOverride(args),
    resetRbacOverride: (args: unknown) => resetRbacOverride(args),
    getRbacChanges: () => getRbacChanges(),
  };
});

function renderPage(url = "/platform/roles") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      {/* DataTable calls useNavigate for row links, so a Router is required. */}
      <MemoryRouter initialEntries={[url]}>
        <PlatformRolesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * The page stacks two tables: roles on top, that role's permissions below.
 * Waits for real content — DataTable keeps its header mounted while loading,
 * so simply finding two tables would match the skeleton.
 */
async function bothTables(): Promise<HTMLElement[]> {
  await screen.findByText("PlatformAdmin");
  return waitFor(() => {
    const found = screen.getAllByRole("table");
    expect(found).toHaveLength(2);
    return found;
  });
}
const rolesTable = () => screen.getAllByRole("table")[0];
const permsTable = () => screen.getAllByRole("table")[1];

describe("PlatformRolesPage", () => {
  beforeEach(async () => {
    getRbacMatrix.mockClear();
    await setupTestI18n("en");
  });

  it("lists every role with its tier and holder count in one compact table", async () => {
    renderPage();
    await bothTables();
    const roleRow = within(rolesTable()).getByText("BillingAdmin").closest("tr") as HTMLElement;
    // Tier is rendered through i18n, so it reads "Tenant", not the raw value.
    expect(within(roleRow).getByText("Tenant")).toBeInTheDocument();
    // 1 permission, 1 enforced, 0 pending, 7 people.
    expect(within(roleRow).getByText("7")).toBeInTheDocument();
  });

  it("marks the wildcard role rather than printing a bare count", async () => {
    renderPage();
    await bothTables();
    expect(within(rolesTable()).getByText("All permissions")).toBeInTheDocument();
  });

  it("puts the totals in the subtitle instead of a row of KPI tiles", async () => {
    renderPage();
    await bothTables();
    expect(
      screen.getByText(/3 roles · 4 permissions · 3 enforced · 1 not yet enforced/),
    ).toBeInTheDocument();
  });

  it("does not land on PlatformAdmin, the one role that can never be edited", async () => {
    // Reported from prod: the page opened on PlatformAdmin (first row — platform
    // tier, most permissions) which is wildcard and immutable, so every toggle
    // and Reset was suppressed and runtime editing looked as though it had
    // never shipped. Default to the first *editable* role instead.
    renderPage();
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");
    // header + BillingAdmin's single granted capability
    expect(within(permsTable()).getAllByRole("row")).toHaveLength(2);
    expect(within(permsTable()).queryByText("farm.delete")).not.toBeInTheDocument();
  });

  it("still honours an explicit PlatformAdmin selection from the URL", async () => {
    renderPage("/platform/roles?role=PlatformAdmin");
    await bothTables();
    await within(permsTable()).findByText("farm.read");
    expect(within(permsTable()).getAllByRole("row")).toHaveLength(5);
  });

  it("selects a role from the URL so a view can be handed over", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    await bothTables();
    await waitFor(() => {
      expect(within(permsTable()).getAllByRole("row")).toHaveLength(2);
    });
    expect(within(permsTable()).getByText("subscription.manage")).toBeInTheDocument();
    expect(within(permsTable()).queryByText("farm.delete")).not.toBeInTheDocument();
  });

  it("narrows the permission table to the role that was clicked", async () => {
    renderPage();
    const user = userEvent.setup();
    await bothTables();
    await user.click(within(rolesTable()).getByRole("link", { name: /BillingAdmin/ }));

    await waitFor(() => {
      expect(within(permsTable()).getAllByRole("row")).toHaveLength(2);
    });
    expect(within(permsTable()).getByText("subscription.manage")).toBeInTheDocument();
  });

  it("flags a permission that no route enforces yet", async () => {
    // Pinned to PlatformAdmin: it is the only role holding the stub capability,
    // and the page deliberately no longer *defaults* to it.
    renderPage("/platform/roles?role=PlatformAdmin");
    await bothTables();
    await within(permsTable()).findByText("analytics.export");
    expect(within(permsTable()).getByText("Pending")).toBeInTheDocument();
  });

  it("offers scope, resource and status as three separate dropdowns", async () => {
    renderPage();
    await bothTables();
    // Exact names: the column-header hint buttons are also called "Scope" and
    // "Status", but their accessible name carries the explanation too.
    expect(screen.getByRole("button", { name: "Scope" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resource" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Status" })).toBeInTheDocument();
    // One combined "Filters" button would hide which axis a value belongs to.
    expect(screen.queryByRole("button", { name: "Filters" })).not.toBeInTheDocument();
  });

  it("filters the table from a single axis dropdown", async () => {
    // PlatformAdmin grants everything, which is what makes the filter's effect
    // measurable; the default role deliberately grants only one capability.
    renderPage("/platform/roles?role=PlatformAdmin");
    const user = userEvent.setup();
    await bothTables();
    await within(permsTable()).findByText("farm.read");

    await user.click(screen.getByRole("button", { name: "Status" }));
    await user.click(await screen.findByLabelText("Pending"));

    await waitFor(() => {
      expect(within(permsTable()).getAllByRole("row")).toHaveLength(2);
    });
    expect(within(permsTable()).getByText("analytics.export")).toBeInTheDocument();
  });

  it("explains the terms of art in the column headers", async () => {
    renderPage();
    await bothTables();
    // Scope is documentation-only, which nobody would guess from the word.
    expect(
      within(permsTable()).getByText(/resolver enforces the role mapping/),
    ).toBeInTheDocument();
    expect(
      within(permsTable()).getByText(/reserved for a module that has not shipped/),
    ).toBeInTheDocument();
    expect(
      within(permsTable()).getByText(/a user with only this role passes the check/),
    ).toBeInTheDocument();
  });

  it("shows which roles grant a permission in the by-permission view", async () => {
    renderPage();
    const user = userEvent.setup();
    await bothTables();
    await user.click(screen.getByRole("radio", { name: "By permission" }));

    await within(permsTable()).findByText("analytics.export");
    expect(within(permsTable()).getAllByRole("row")).toHaveLength(5);
    const farmRead = within(permsTable()).getByText("farm.read").closest("tr") as HTMLElement;
    expect(within(farmRead).getByText("Viewer")).toBeInTheDocument();
    expect(within(farmRead).getByText("PlatformAdmin")).toBeInTheDocument();
  });

  it("surfaces a load failure instead of an empty table", async () => {
    getRbacMatrix.mockImplementation(() => Promise.reject(new Error("boom")));
    renderPage();
    await waitFor(() =>
      expect(
        screen.getAllByText("Could not load the roles and permissions.").length,
      ).toBeGreaterThan(0),
    );
    getRbacMatrix.mockImplementation(() => Promise.resolve(matrix));
  });

  it("shows no editing affordance without platform.manage_rbac", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");
    // The marker stays a glyph. can_manage is false in the base fixture.
    expect(
      within(permsTable()).queryByRole("button", { name: /Revoke subscription.manage/ }),
    ).not.toBeInTheDocument();
  });
});

/**
 * Phase 2 — runtime editing.
 *
 * The matrix here grants `can_manage` and puts BillingAdmin one override away
 * from its shipped default, which is the state the modified-marker and Reset
 * control exist for.
 */
describe("PlatformRolesPage editing", () => {
  const editable: RbacMatrix = {
    ...matrix,
    can_manage: true,
    roles: matrix.roles.map((role) =>
      role.name === "BillingAdmin"
        ? {
            ...role,
            // Granted by an override, not by the YAML — so the row must render
            // as granted *and* modified, with a Reset.
            capabilities: ["subscription.manage", "farm.delete"],
            capability_count: 2,
            active_count: 2,
            overrides: [
              {
                capability: "farm.delete",
                granted: true,
                note: "incident 412",
                updated_at: "2026-08-11T10:00:00Z",
                updated_by: "11111111-1111-1111-1111-111111111111",
              },
            ],
          }
        : role,
    ),
  };

  beforeEach(async () => {
    getRbacMatrix.mockClear();
    setRbacOverride.mockClear();
    resetRbacOverride.mockClear();
    getRbacChanges.mockClear();
    getRbacMatrix.mockImplementation(() => Promise.resolve(editable));
    setRbacOverride.mockImplementation(() =>
      Promise.resolve({
        role: "BillingAdmin",
        capability: "farm.read",
        baseline: false,
        effective: true,
        overridden: true,
        action: "grant",
        unchanged: false,
      }),
    );
    resetRbacOverride.mockImplementation(() =>
      Promise.resolve({
        role: "BillingAdmin",
        capability: "farm.delete",
        baseline: false,
        effective: false,
        overridden: false,
        action: "reset",
        unchanged: false,
      }),
    );
    getRbacChanges.mockImplementation(() => Promise.resolve([]));
    await setupTestI18n("en");
  });

  it("opens on an editable role so the toggles are visible without hunting", async () => {
    // The prod report was "I see no edit / modify functionalities". The cause
    // was the landing role, so assert the *default* view offers a control.
    renderPage();
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");
    expect(
      within(permsTable()).getByRole("button", {
        name: "Revoke subscription.manage from this role",
      }),
    ).toBeInTheDocument();
  });

  it("says outright that the permissions can be edited", async () => {
    renderPage();
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");
    expect(
      screen.getByText(/You can change what BillingAdmin is allowed to do/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Select a tick or dash in the Granted column/)).toBeInTheDocument();
  });

  it("turns the granted marker into a toggle for an editable role", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");
    expect(
      within(permsTable()).getByRole("button", {
        name: "Revoke subscription.manage from this role",
      }),
    ).toBeInTheDocument();
  });

  it("leaves PlatformAdmin uneditable and says why", async () => {
    renderPage("/platform/roles?role=PlatformAdmin");
    await bothTables();
    await within(permsTable()).findByText("farm.read");
    expect(
      screen.getByText(/PlatformAdmin grants every permission and cannot be edited/),
    ).toBeInTheDocument();
    expect(
      within(permsTable()).queryByRole("button", { name: /Revoke farm.read/ }),
    ).not.toBeInTheDocument();
  });

  it("confirms before writing, showing the before and after", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    const user = userEvent.setup();
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");

    await user.click(
      within(permsTable()).getByRole("button", {
        name: "Revoke subscription.manage from this role",
      }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Revoke this permission?")).toBeInTheDocument();
    // Nothing is sent until the admin confirms — the toggle is not optimistic.
    expect(setRbacOverride).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Apply change" }));
    await waitFor(() =>
      expect(setRbacOverride).toHaveBeenCalledWith(
        expect.objectContaining({
          role: "BillingAdmin",
          capability: "subscription.manage",
          granted: false,
        }),
      ),
    );
  });

  it("passes the note through to the change log", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    const user = userEvent.setup();
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");

    await user.click(
      within(permsTable()).getByRole("button", {
        name: "Revoke subscription.manage from this role",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Why/), "over-broad");
    await user.click(within(dialog).getByRole("button", { name: "Apply change" }));

    await waitFor(() =>
      expect(setRbacOverride).toHaveBeenCalledWith(expect.objectContaining({ note: "over-broad" })),
    );
  });

  it("states the propagation delay rather than implying it is instant", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    const user = userEvent.setup();
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");

    await user.click(
      within(permsTable()).getByRole("button", {
        name: "Revoke subscription.manage from this role",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/within 30 seconds/)).toBeInTheDocument();
  });

  it("warns that granting an unenforced permission changes nothing yet", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    const user = userEvent.setup();
    await bothTables();
    // analytics.export is a stub and not granted, so show the not-granted rows.
    // FilterChip renders role="switch", not a plain button.
    await user.click(screen.getByRole("switch", { name: "Not granted" }));
    await within(permsTable()).findByText("analytics.export");

    await user.click(
      within(permsTable()).getByRole("button", { name: "Grant analytics.export to this role" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Nothing enforces this permission yet/)).toBeInTheDocument();
  });

  it("marks a permission that differs from the shipped default and offers a reset", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    const user = userEvent.setup();
    await bothTables();
    await within(permsTable()).findByText("farm.delete");

    const row = within(permsTable()).getByText("farm.delete").closest("tr") as HTMLElement;
    expect(within(row).getByText("Edited")).toBeInTheDocument();

    await user.click(within(row).getByRole("button", { name: "Reset" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Reset to the shipped default?")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Apply change" }));
    await waitFor(() =>
      expect(resetRbacOverride).toHaveBeenCalledWith(
        expect.objectContaining({ role: "BillingAdmin", capability: "farm.delete" }),
      ),
    );
    // Reset must go through DELETE, never a PUT of the baseline value.
    expect(setRbacOverride).not.toHaveBeenCalled();
  });

  it("does not mark an unmodified permission", async () => {
    renderPage("/platform/roles?role=BillingAdmin");
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");
    const row = within(permsTable()).getByText("subscription.manage").closest("tr") as HTMLElement;
    expect(within(row).queryByText("Edited")).not.toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Reset" })).not.toBeInTheDocument();
  });

  it("shows the change log on demand, newest first", async () => {
    getRbacChanges.mockImplementation(() =>
      Promise.resolve([
        {
          id: 2,
          role: "BillingAdmin",
          capability: "farm.delete",
          action: "grant",
          previous_effective: false,
          new_effective: true,
          changed_by: "u1",
          changed_by_email: "ops@agripulse.cloud",
          note: "incident 412",
          changed_at: "2026-08-11T10:00:00Z",
        },
      ]),
    );
    renderPage("/platform/roles?role=BillingAdmin");
    const user = userEvent.setup();
    await bothTables();

    await user.click(screen.getByRole("radio", { name: "Change log" }));
    await screen.findByText("ops@agripulse.cloud");
    expect(screen.getByText("incident 412")).toBeInTheDocument();
    expect(screen.getByText("Granted")).toBeInTheDocument();
  });

  it("keeps the dialog open and reports a failed write", async () => {
    setRbacOverride.mockImplementation(() => Promise.reject(new Error("boom")));
    renderPage("/platform/roles?role=BillingAdmin");
    const user = userEvent.setup();
    await bothTables();
    await within(permsTable()).findByText("subscription.manage");

    await user.click(
      within(permsTable()).getByRole("button", {
        name: "Revoke subscription.manage from this role",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Apply change" }));

    // The admin must not be left believing a change landed when it did not.
    expect(await within(dialog).findByText(/Nothing was saved/)).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
