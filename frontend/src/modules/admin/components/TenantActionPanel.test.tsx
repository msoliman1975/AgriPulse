import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminTenant, TenantStatus } from "@/api/adminTenants";
import { setupTestI18n } from "@/i18n/testing";

import { TenantActionPanel } from "./TenantActionPanel";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const suspendMock = vi.hoisted(() => vi.fn());
const reactivateMock = vi.hoisted(() => vi.fn());
const requestDeleteMock = vi.hoisted(() => vi.fn());
const cancelDeleteMock = vi.hoisted(() => vi.fn());
const purgeMock = vi.hoisted(() => vi.fn());
const retryMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/adminTenants", async () => {
  const actual = await vi.importActual<object>("@/api/adminTenants");
  return {
    ...actual,
    suspendAdminTenant: suspendMock,
    reactivateAdminTenant: reactivateMock,
    requestDeleteAdminTenant: requestDeleteMock,
    cancelDeleteAdminTenant: cancelDeleteMock,
    purgeAdminTenant: purgeMock,
    retryProvisioningAdminTenant: retryMock,
  };
});

const TENANT_ID = "11111111-1111-1111-1111-111111111111";

function tenant(status: TenantStatus, overrides: Partial<AdminTenant> = {}): AdminTenant {
  return {
    id: TENANT_ID,
    slug: "acme",
    name: "Acme",
    legal_name: null,
    tax_id: null,
    contact_email: "ops@acme.test",
    contact_phone: null,
    schema_name: "tenant_xxx",
    status,
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

function renderPanel(t: AdminTenant, days = 30) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter
        initialEntries={[`/platform/tenants/${t.id}`]}
      >
        <Routes>
          <Route
            path="/platform/tenants/:tenantId"
            element={<TenantActionPanel tenant={t} purgeGraceDays={days} />}
          />
          <Route path="/platform/tenants" element={<p>landed-on-list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("<TenantActionPanel>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    suspendMock.mockReset();
    reactivateMock.mockReset();
    requestDeleteMock.mockReset();
    cancelDeleteMock.mockReset();
    purgeMock.mockReset();
    retryMock.mockReset();
  });

  it("active tenant shows Suspend + Mark-for-deletion only", () => {
    renderPanel(tenant("active"));
    expect(screen.getByText("Suspend")).toBeInTheDocument();
    expect(screen.getByText("Mark for deletion")).toBeInTheDocument();
    expect(screen.queryByText("Reactivate")).not.toBeInTheDocument();
    expect(screen.queryByText("Cancel deletion")).not.toBeInTheDocument();
    expect(screen.queryByText("Purge now")).not.toBeInTheDocument();
    expect(screen.queryByText("Retry provisioning")).not.toBeInTheDocument();
  });

  it("opens suspend modal and submits with optional reason", async () => {
    suspendMock.mockResolvedValue(tenant("suspended"));
    const user = userEvent.setup();
    renderPanel(tenant("active"));

    await user.click(screen.getByRole("button", { name: "Suspend" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(screen.getByLabelText("Reason (optional)"), "trial expired");
    // Two "Suspend" buttons exist (panel + modal confirm); scope to the dialog.
    const { getByRole } = within(dialog);
    await user.click(getByRole("button", { name: "Suspend" }));

    await waitFor(() => {
      expect(suspendMock).toHaveBeenCalledTimes(1);
    });
    expect(suspendMock.mock.calls[0]).toEqual([TENANT_ID, "trial expired"]);
  });

  it("reactivates without a modal", async () => {
    reactivateMock.mockResolvedValue(tenant("active"));
    const user = userEvent.setup();
    renderPanel(tenant("suspended"));

    await user.click(screen.getByText("Reactivate"));
    await waitFor(() => {
      expect(reactivateMock).toHaveBeenCalledWith(TENANT_ID);
    });
  });

  it("pending_delete tenant shows Cancel + Purge", () => {
    renderPanel(tenant("pending_delete", { deleted_at: "2026-05-01T00:00:00Z" }));
    expect(screen.getByText("Cancel deletion")).toBeInTheDocument();
    expect(screen.getByText("Purge now")).toBeInTheDocument();
    expect(screen.queryByText("Suspend")).not.toBeInTheDocument();
  });

  it("purge requires correct slug confirmation", async () => {
    const user = userEvent.setup();
    purgeMock.mockResolvedValue(undefined);
    // Set purge_eligible_at in the past so the force toggle does NOT show.
    renderPanel(
      tenant("pending_delete", {
        deleted_at: "2026-04-01T00:00:00Z",
        purge_eligible_at: "2026-05-01T00:00:00Z",
      }),
    );

    await user.click(screen.getByText("Purge now"));
    await screen.findByRole("dialog");

    const confirmBtn = screen.getByRole("button", { name: "Purge tenant" });
    expect(confirmBtn).toBeDisabled();

    // Wrong confirmation keeps it disabled.
    const input = screen.getByRole("textbox");
    await user.type(input, "not-the-slug");
    expect(confirmBtn).toBeDisabled();

    await user.clear(input);
    await user.type(input, "acme");
    expect(confirmBtn).not.toBeDisabled();
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(purgeMock).toHaveBeenCalledTimes(1);
    });
    expect(purgeMock.mock.calls[0]).toEqual([
      TENANT_ID,
      { slug_confirmation: "acme", force: false },
    ]);
  });

  it("inside grace window requires the force toggle", async () => {
    const user = userEvent.setup();
    purgeMock.mockResolvedValue(undefined);
    const future = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString();
    renderPanel(
      tenant("pending_delete", {
        deleted_at: new Date().toISOString(),
        purge_eligible_at: future,
      }),
    );

    await user.click(screen.getByText("Purge now"));
    await screen.findByRole("dialog");
    await user.type(screen.getByRole("textbox"), "acme");

    const confirmBtn = screen.getByRole("button", { name: "Purge tenant" });
    expect(confirmBtn).toBeDisabled(); // force toggle still off

    await user.click(screen.getByRole("checkbox"));
    expect(confirmBtn).not.toBeDisabled();
  });

  it("pending_provision tenant shows Retry button", async () => {
    retryMock.mockResolvedValue(tenant("active"));
    const user = userEvent.setup();
    renderPanel(tenant("pending_provision"));

    await user.click(screen.getByText("Retry provisioning"));
    await waitFor(() => {
      expect(retryMock).toHaveBeenCalledWith(TENANT_ID);
    });
  });
});
