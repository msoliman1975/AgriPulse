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

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      {/* DataTable calls useNavigate for row links, so a Router is required. */}
      <MemoryRouter initialEntries={["/platform/roles"]}>
        <PlatformRolesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The permission table, addressed by its caption so KPI text can't match. */
async function table(): Promise<HTMLElement> {
  return waitFor(() => screen.getByRole("table"));
}

describe("PlatformRolesPage", () => {
  beforeEach(async () => {
    getRbacMatrix.mockClear();
    await setupTestI18n("en");
  });

  it("groups roles into their three tier bands", async () => {
    renderPage();
    await waitFor(() => screen.getByText("BillingAdmin"));
    expect(screen.getByText("Platform roles")).toBeInTheDocument();
    expect(screen.getByText("Tenant roles")).toBeInTheDocument();
    expect(screen.getByText("Farm roles")).toBeInTheDocument();
  });

  it("marks the wildcard role rather than printing a bare count", async () => {
    renderPage();
    await waitFor(() => screen.getByText("PlatformAdmin"));
    expect(screen.getByText("All permissions")).toBeInTheDocument();
  });

  it("reports how many people hold each role", async () => {
    renderPage();
    await waitFor(() => screen.getByText("BillingAdmin"));
    expect(screen.getByText("7 people hold this role")).toBeInTheDocument();
  });

  it("defaults to the granted permissions of the first role", async () => {
    renderPage();
    // DataTable keeps its header mounted while loading, so wait for real
    // content before counting rows or the skeleton gets measured instead.
    await within(await table()).findByText("farm.read");
    // header + PlatformAdmin's 4 granted capabilities
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(5);
  });

  it("narrows the table to the role that was clicked", async () => {
    renderPage();
    const user = userEvent.setup();
    await waitFor(() => screen.getByText("BillingAdmin"));
    await user.click(screen.getByText("Subscription and billing only."));

    await waitFor(() => {
      expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
    });
    expect(screen.getByText("subscription.manage")).toBeInTheDocument();
    expect(screen.queryByText("farm.delete")).not.toBeInTheDocument();
  });

  it("flags a permission that no route enforces yet", async () => {
    renderPage();
    await within(await table()).findByText("analytics.export");
    // PlatformAdmin holds the stub capability, so the badge must be visible
    // on first paint rather than hidden behind a filter.
    expect(within(screen.getByRole("table")).getByText("Pending")).toBeInTheDocument();
  });

  it("shows which roles grant a permission in the by-permission view", async () => {
    renderPage();
    const user = userEvent.setup();
    await waitFor(() => screen.getByText("BillingAdmin"));
    await user.click(screen.getByRole("radio", { name: "By permission" }));

    await within(await table()).findByText("analytics.export");
    // Every capability is listed, not just the selected role's.
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(5);
    const farmRead = within(screen.getByRole("table")).getByText("farm.read").closest("tr");
    expect(within(farmRead as HTMLElement).getByText("Viewer")).toBeInTheDocument();
    expect(within(farmRead as HTMLElement).getByText("PlatformAdmin")).toBeInTheDocument();
  });

  it("surfaces a load failure instead of an empty table", async () => {
    getRbacMatrix.mockImplementationOnce(() => Promise.reject(new Error("boom")));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Could not load the roles and permissions.")).toBeInTheDocument(),
    );
  });
});
