import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { TenantListPage } from "./TenantListPage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const listMock = vi.hoisted(() => vi.fn());
const metaMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/adminTenants", async () => {
  const actual = await vi.importActual<object>("@/api/adminTenants");
  return {
    ...actual,
    listAdminTenants: listMock,
    getAdminTenantMeta: metaMock,
  };
});

function buildTenant(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    slug: "acme",
    name: "Acme Farms",
    legal_name: null,
    tax_id: null,
    contact_email: "ops@acme.test",
    contact_phone: null,
    schema_name: "tenant_xxxx",
    status: "active",
    default_locale: "en",
    default_unit_system: "feddan",
    default_timezone: "Africa/Cairo",
    default_currency: "EGP",
    country_code: "EG",
    suspended_at: null,
    deleted_at: null,
    last_status_reason: null,
    purge_eligible_at: null,
    keycloak_group_id: null,
    pending_owner_email: null,
    created_at: "2026-05-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
    ...overrides,
  };
}

function renderList() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/platform/tenants"]}>
        <Routes>
          <Route path="/platform/tenants" element={<TenantListPage />} />
          <Route
            path="/platform/tenants/:tenantId"
            element={<p>detail-page</p>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("<TenantListPage>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listMock.mockReset();
    metaMock.mockReset();
    metaMock.mockResolvedValue({
      statuses: ["active", "suspended", "pending_delete"],
      tiers: ["free", "standard"],
      locales: ["en", "ar"],
      unit_systems: ["feddan"],
      purge_grace_days: 30,
    });
  });

  it("renders the table for a single-row response", async () => {
    listMock.mockResolvedValue({
      items: [buildTenant({ slug: "acme", name: "Acme Farms", status: "active" })],
      total: 1,
      limit: 25,
      offset: 0,
    });
    renderList();

    expect(await screen.findByText("Acme Farms")).toBeInTheDocument();
    expect(screen.getByText("acme")).toBeInTheDocument();
    // Two "Active" instances render: the filter chip and the row badge.
    // Assert at least one of each (chip is a switch role).
    expect(screen.getByRole("switch", { name: "Active" })).toBeInTheDocument();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(1);
  });

  it("filters by status when a chip is clicked", async () => {
    listMock.mockImplementation((params: { status?: string } = {}) => {
      if (params.status === "suspended") {
        return Promise.resolve({
          items: [buildTenant({ status: "suspended", name: "Beta" })],
          total: 1,
          limit: 25,
          offset: 0,
        });
      }
      return Promise.resolve({
        items: [buildTenant({ name: "Alpha" })],
        total: 1,
        limit: 25,
        offset: 0,
      });
    });

    renderList();
    expect(await screen.findByText("Alpha")).toBeInTheDocument();

    const suspendChip = await screen.findByRole("switch", { name: "Suspended" });
    await userEvent.click(suspendChip);

    await waitFor(() => {
      expect(screen.getByText("Beta")).toBeInTheDocument();
    });
    expect(listMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "suspended" }),
    );
  });

  it("renders the empty state when the response has zero items", async () => {
    listMock.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    renderList();
    expect(
      await screen.findByText("No tenants match your filters."),
    ).toBeInTheDocument();
  });

  it("surfaces an error banner on failure", async () => {
    listMock.mockRejectedValue(new Error("boom"));
    renderList();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load tenants",
    );
  });
});
