import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/errors";
import { setupTestI18n } from "@/i18n/testing";

import { TenantCreatePage } from "./TenantCreatePage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const createMock = vi.hoisted(() => vi.fn());
const metaMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/adminTenants", async () => {
  const actual = await vi.importActual<object>("@/api/adminTenants");
  return {
    ...actual,
    createAdminTenant: createMock,
    getAdminTenantMeta: metaMock,
  };
});

function buildSuccess(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    slug: "acme",
    name: "Acme",
    schema_name: "tenant_xxxx",
    contact_email: "ops@acme.test",
    default_locale: "en",
    default_unit_system: "feddan",
    status: "active",
    created_at: "2026-05-08T00:00:00Z",
    provisioning_failed: false,
    owner_user_id: null,
    ...overrides,
  };
}

function renderWizard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/platform/tenants/new"]}>
        <Routes>
          <Route path="/platform/tenants/new" element={<TenantCreatePage />} />
          <Route path="/platform/tenants/:tenantId" element={<p>landed-on-detail</p>} />
          <Route path="/platform/tenants" element={<p>landed-on-list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function fillProfile(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.type(screen.getByLabelText("Slug"), "acme-farms");
  await user.type(screen.getByLabelText("Display name"), "Acme Farms");
  await user.type(screen.getByLabelText("Contact email"), "ops@acme.test");
}

describe("<TenantCreatePage>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    createMock.mockReset();
    metaMock.mockReset();
    metaMock.mockResolvedValue({
      statuses: ["active", "suspended"],
      tiers: ["free", "standard", "premium"],
      locales: ["en", "ar"],
      unit_systems: ["feddan", "acre", "hectare"],
      purge_grace_days: 30,
    });
  });

  it("walks the happy path through profile â†’ owner â†’ review â†’ create", async () => {
    createMock.mockResolvedValue(buildSuccess({ status: "active" }));
    const user = userEvent.setup();
    renderWizard();

    await fillProfile(user);
    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByLabelText("Initial owner email");
    await user.type(screen.getByLabelText("Initial owner email"), "owner@acme.test");
    await user.type(screen.getByLabelText("Initial owner full name"), "Owner Name");
    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByText("Step 3 of 3 â€” Review & create");
    await user.click(screen.getByRole("button", { name: "Create tenant" }));

    expect(await screen.findByText("Tenant created")).toBeInTheDocument();
    expect(screen.getByText("Welcome email sent to owner@acme.test.")).toBeInTheDocument();
    // useMutation invokes mutationFn with (variables, ctx); assert on the
    // first arg only.
    expect(createMock.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        slug: "acme-farms",
        name: "Acme Farms",
        contact_email: "ops@acme.test",
        owner_email: "owner@acme.test",
        owner_full_name: "Owner Name",
      }),
    );
  });

  it("surfaces a 409 slug conflict and bounces back to the slug field", async () => {
    createMock.mockRejectedValue(
      new ApiError(
        {
          type: "https://agripulse.cloud/problems/tenant-slug-conflict",
          title: "Tenant slug already exists",
          status: 409,
        },
        undefined,
      ),
    );
    const user = userEvent.setup();
    renderWizard();

    await fillProfile(user);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByLabelText("Initial owner email");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Create tenant" }));

    await waitFor(() => {
      expect(screen.getByText("A tenant with this slug already exists.")).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Slug")).toHaveValue("acme-farms");
  });

  it("shows the no-owner success message when owner_email is omitted", async () => {
    createMock.mockResolvedValue(buildSuccess({ status: "active", owner_user_id: null }));
    const user = userEvent.setup();
    renderWizard();

    await fillProfile(user);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByLabelText("Initial owner email");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Create tenant" }));

    expect(await screen.findByText(/Provision the Keycloak owner manually/)).toBeInTheDocument();
  });

  it("shows the pending-provision banner when create reports provisioning_failed", async () => {
    createMock.mockResolvedValue(
      buildSuccess({ status: "pending_provision", provisioning_failed: true }),
    );
    const user = userEvent.setup();
    renderWizard();

    await fillProfile(user);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByLabelText("Initial owner email");
    await user.type(screen.getByLabelText("Initial owner email"), "owner@acme.test");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Create tenant" }));

    expect(await screen.findByText(/Keycloak provisioning failed/)).toBeInTheDocument();
  });

  it("blocks Next on profile when slug is malformed", async () => {
    const user = userEvent.setup();
    renderWizard();

    // Two chars â€” under the 3-char minimum. (The slug input lowercases on
    // change, so an "all caps" string like "BAD" would have passed.)
    await user.type(screen.getByLabelText("Slug"), "ab");
    await user.type(screen.getByLabelText("Display name"), "Acme");
    await user.type(screen.getByLabelText("Contact email"), "ops@acme.test");
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Slug must match [a-z0-9-]{3,32}.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Initial owner email")).not.toBeInTheDocument();
  });
});
