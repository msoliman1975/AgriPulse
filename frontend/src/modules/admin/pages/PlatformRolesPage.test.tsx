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
    },
  ],
};

const getRbacMatrix = vi.fn(() => Promise.resolve(matrix));

vi.mock("@/api/rbacMatrix", async () => {
  const actual = await vi.importActual<typeof import("@/api/rbacMatrix")>("@/api/rbacMatrix");
  return { ...actual, getRbacMatrix: () => getRbacMatrix() };
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

  it("defaults to the granted permissions of the first role", async () => {
    renderPage();
    await bothTables();
    await within(permsTable()).findByText("farm.read");
    // header + PlatformAdmin's 4 granted capabilities
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
    renderPage();
    await bothTables();
    await within(permsTable()).findByText("analytics.export");
    // PlatformAdmin holds the stub capability, so the badge must be visible on
    // first paint rather than hidden behind a filter.
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
    renderPage();
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
    expect(within(permsTable()).getByText(/resolver enforces the role mapping/)).toBeInTheDocument();
    expect(within(permsTable()).getByText(/reserved for a module that has not shipped/)).toBeInTheDocument();
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
});
