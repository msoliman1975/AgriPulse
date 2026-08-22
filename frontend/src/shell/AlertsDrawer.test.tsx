import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { AlertsDrawer } from "./AlertsDrawer";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const listPlatformMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/platformAlerts", async () => {
  const actual = await vi.importActual<object>("@/api/platformAlerts");
  return { ...actual, listPlatformAlerts: listPlatformMock };
});

const listInboxMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/inbox", async () => {
  const actual = await vi.importActual<object>("@/api/inbox");
  return { ...actual, listInbox: listInboxMock };
});

function buildAlert(over: Record<string, unknown> = {}) {
  return {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    alert_key: "stuck_job:imagery:farm-1",
    category: "imagery",
    kind: "stuck_job",
    severity: "critical",
    status: "open",
    tenant_id: null,
    tenant_slug: "agrosina",
    tenant_name: "Agrosina",
    farm_id: null,
    farm_name: "Bashier Elkhier",
    title: "Imagery jobs stuck on Bashier Elkhier",
    detail: "6 jobs.",
    context: {},
    first_seen_at: "2026-08-21T00:00:00Z",
    last_seen_at: "2026-08-22T00:00:00Z",
    occurrences: 61,
    acknowledged_at: null,
    acknowledged_by: null,
    acknowledged_by_email: null,
    resolved_at: null,
    resolved_reason: null,
    ...over,
  };
}

function renderDrawer(platform: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/platform/tenants"]}>
        <Routes>
          <Route
            path="/platform/tenants"
            element={<AlertsDrawer open onClose={() => {}} platform={platform} />}
          />
          <Route path="/platform/alerts" element={<p>alerts-page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("<AlertsDrawer> in platform mode", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listPlatformMock.mockReset();
    listInboxMock.mockReset();
  });

  // A platform admin belongs to no tenant, so /v1/inbox answers 403 and the
  // bell was permanently empty for the one person these alerts are for.
  it("lists platform alerts and never calls the tenant inbox", async () => {
    listPlatformMock.mockResolvedValue({
      items: [buildAlert()],
      total: 1,
      limit: 10,
      offset: 0,
    });

    renderDrawer(true);

    expect(await screen.findByText("Imagery jobs stuck on Bashier Elkhier")).toBeInTheDocument();
    expect(screen.getByText("Agrosina / Bashier Elkhier")).toBeInTheDocument();
    expect(listInboxMock).not.toHaveBeenCalled();
  });

  it("is the second way into the alerts page", async () => {
    const user = userEvent.setup();
    listPlatformMock.mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 });

    renderDrawer(true);

    const seeAll = await screen.findByRole("button", { name: /alerts page/i });
    await user.click(seeAll);

    expect(screen.getByText("alerts-page")).toBeInTheDocument();
  });

  it("still shows the tenant inbox for everyone else", async () => {
    listInboxMock.mockResolvedValue([
      {
        id: "11111111-1111-1111-1111-111111111111",
        title: "NDVI dropped on Block 4",
        body: "Below the threshold.",
        severity: "warning",
        read_at: null,
        link_url: null,
        created_at: "2026-08-22T00:00:00Z",
      },
    ]);

    renderDrawer(false);

    expect(await screen.findByText("NDVI dropped on Block 4")).toBeInTheDocument();
    expect(listPlatformMock).not.toHaveBeenCalled();
  });
});
