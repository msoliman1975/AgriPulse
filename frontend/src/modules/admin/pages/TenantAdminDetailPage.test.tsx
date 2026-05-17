import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { TenantAdminDetailPage } from "./TenantAdminDetailPage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const tenantMock = vi.hoisted(() => vi.fn());
const sidecarMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/adminTenants", async () => {
  const actual = await vi.importActual<object>("@/api/adminTenants");
  return {
    ...actual,
    getAdminTenant: tenantMock,
    getAdminTenantSidecar: sidecarMock,
  };
});

const TENANT_ID = "11111111-1111-1111-1111-111111111111";

function baseTenant(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: TENANT_ID,
    slug: "acme",
    name: "Acme Farms",
    legal_name: null,
    tax_id: null,
    contact_email: "ops@acme.test",
    contact_phone: null,
    schema_name: "tenant_xxx",
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

function baseSidecar(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    tenant_id: TENANT_ID,
    settings: {
      cloud_cover_threshold_visualization_pct: 60,
      cloud_cover_threshold_analysis_pct: 20,
      imagery_refresh_cadence_hours: 24,
      alert_notification_channels: ["in_app", "email"],
      webhook_endpoint_url: null,
      dashboard_default_indices: ["ndvi", "ndwi"],
    },
    subscription: {
      id: "22222222-2222-2222-2222-222222222222",
      tier: "standard",
      plan_type: null,
      started_at: "2026-05-01T00:00:00Z",
      expires_at: null,
      is_current: true,
      trial_start: null,
      trial_end: null,
      feature_flags: {},
    },
    active_member_count: 7,
    recent_events: [
      {
        id: "33333333-3333-3333-3333-333333333333",
        occurred_at: "2026-05-02T00:00:00Z",
        event_type: "platform.tenant_suspended",
        actor_user_id: null,
        actor_kind: "user",
        details: {},
        correlation_id: null,
      },
    ],
    ...overrides,
  };
}

function renderDetail() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/platform/tenants/${TENANT_ID}`]}>
        <Routes>
          <Route path="/platform/tenants/:tenantId" element={<TenantAdminDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("<TenantAdminDetailPage>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    tenantMock.mockReset();
    sidecarMock.mockReset();
  });

  it("renders profile, settings, subscription, KPI, and audit events", async () => {
    tenantMock.mockResolvedValue(baseTenant());
    sidecarMock.mockResolvedValue(baseSidecar());
    renderDetail();

    expect(await screen.findByText("Acme Farms")).toBeInTheDocument();
    expect(screen.getByText("acme")).toBeInTheDocument();
    expect(await screen.findByText("7")).toBeInTheDocument();
    // "standard" renders both as the KPI value and the subscription tier row.
    expect(screen.getAllByText("standard").length).toBeGreaterThan(0);
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("platform.tenant_suspended")).toBeInTheDocument();
  });

  it("shows a status banner for suspended tenants with the reason", async () => {
    tenantMock.mockResolvedValue(
      baseTenant({
        status: "suspended",
        suspended_at: "2026-05-02T00:00:00Z",
        last_status_reason: "trial expired",
      }),
    );
    sidecarMock.mockResolvedValue(baseSidecar());
    renderDetail();

    expect(
      await screen.findByText("This tenant is suspended. Sign-ins are blocked."),
    ).toBeInTheDocument();
    expect(screen.getByText("trial expired")).toBeInTheDocument();
  });

  it("surfaces an error message when the tenant fetch fails", async () => {
    tenantMock.mockRejectedValue(new Error("boom"));
    sidecarMock.mockResolvedValue(baseSidecar());
    renderDetail();

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load tenant");
  });
});
