import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { PlatformAlertsPage } from "./PlatformAlertsPage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const listMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/platformAlerts", async () => {
  const actual = await vi.importActual<object>("@/api/platformAlerts");
  return { ...actual, listPlatformAlerts: listMock };
});

function buildAlert(overrides: Record<string, unknown> = {}) {
  return {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    alert_key: "peer_lag:optical:farm-1",
    category: "imagery",
    kind: "peer_lag",
    severity: "critical",
    status: "open",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "acme",
    tenant_name: "Acme Farms",
    farm_id: "33333333-3333-3333-3333-333333333333",
    farm_name: "Green Farm",
    title: "Optical imagery is 42h behind a peer farm",
    detail: "Peer farm ingested scene day 2026-08-20.",
    context: {},
    first_seen_at: "2026-08-20T00:00:00Z",
    last_seen_at: "2026-08-21T00:00:00Z",
    occurrences: 4,
    acknowledged_at: null,
    acknowledged_by: null,
    acknowledged_by_email: null,
    resolved_at: null,
    resolved_reason: null,
    ...overrides,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/platform/alerts"]}>
        <PlatformAlertsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("<PlatformAlertsPage>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listMock.mockReset();
  });

  // Regression: the page used to hand <DataTable> the whole `{items, total,
  // …}` envelope as its async state. TypeScript accepted it because of a
  // cast, then the table called .map() on an object, threw, and blanked the
  // whole app — there is no error boundary above this route.
  it("renders a row from the paged envelope", async () => {
    listMock.mockResolvedValue({
      items: [buildAlert()],
      total: 1,
      limit: 100,
      offset: 0,
    });

    renderPage();

    expect(
      await screen.findByText("Optical imagery is 42h behind a peer farm"),
    ).toBeInTheDocument();
    expect(screen.getByText("Acme Farms")).toBeInTheDocument();
    expect(screen.getByText("Green Farm")).toBeInTheDocument();
  });

  it("shows the empty state when nothing is wrong", async () => {
    listMock.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });

    renderPage();

    expect(await screen.findByText(/nothing/i)).toBeInTheDocument();
  });
});
