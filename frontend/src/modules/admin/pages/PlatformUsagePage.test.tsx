import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UsageOverview } from "@/api/usage";
import { setupTestI18n } from "@/i18n/testing";

import { PlatformUsagePage } from "./PlatformUsagePage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const overviewMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/usage", async () => {
  const actual = await vi.importActual<object>("@/api/usage");
  return { ...actual, getUsageOverview: overviewMock };
});

function buildOverview(overrides: Partial<UsageOverview> = {}): UsageOverview {
  return {
    filters: { start: "2026-08-10", end: "2026-09-08", tenant_id: null, include_staff: false },
    kpis: {
      dau: 4,
      wau: 12,
      mau: 30,
      stickiness: 0.3333,
      median_session_seconds: 720,
      sessions: 40,
      sessions_per_user: 3.2,
    },
    daily: [
      { day: "2026-09-07", events: 100, users: 8 },
      { day: "2026-09-08", events: 140, users: 12 },
    ],
    routes: [{ route: "/insights/:farmId", total_ms: 3_600_000, visits: 90, median_ms: 42_000 }],
    features: [{ feature: "insights", events: 120, users: 9, tenants: 3, last_used: "2026-09-08" }],
    cold_features: ["reports", "signals"],
    funnels: [
      {
        flow: "farm_onboarding",
        entries: 10,
        completions: 4,
        abandoned: 6,
        died_at: "subscriptions",
      },
    ],
    funnel_steps: [],
    error_routes: [{ route: "/board/:farmId", views: 200, errors: 24, error_rate: 0.12 }],
    recent_errors: [
      {
        time: "2026-09-08T09:12:30Z",
        route: "/board/:farmId",
        status_code: 500,
        error_code: "http_500",
        correlation_id: "9c1b6f2e-0000-4000-8000-000000000001",
        method: "GET",
      },
    ],
    retry_storms: [],
    slow_actions: [],
    tenants: [
      {
        tenant_id: "22222222-2222-2222-2222-222222222222",
        last_seen: "2026-09-08",
        wau: 6,
        features_used: 4,
        events: 900,
      },
    ],
    ...overrides,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/platform/usage"]}>
        <PlatformUsagePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PlatformUsagePage", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    overviewMock.mockReset();
    overviewMock.mockResolvedValue(buildOverview());
  });

  it("excludes platform staff by default", async () => {
    renderPage();
    await waitFor(() => {
      expect(overviewMock).toHaveBeenCalled();
    });
    // The default matters more than it looks: with staff included, our own
    // clicking outweighs the customers' on a pilot-scale product.
    expect(overviewMock.mock.calls[0][0]).toMatchObject({ includeStaff: false });
  });

  it("re-queries with staff when the toggle is turned on", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(overviewMock).toHaveBeenCalled();
    });
    await user.click(screen.getByLabelText(/include platform staff/i));
    await waitFor(() => {
      expect(overviewMock.mock.calls.some((c) => c[0].includeStaff === true)).toBe(true);
    });
  });

  it("shows the correlation id for a recent failure", async () => {
    renderPage();
    // This is the whole reason the failures table exists: it hands you the id
    // that finds the server log line for an error a real person saw.
    expect(await screen.findByText("9c1b6f2e-0000-4000-8000-000000000001")).toBeInTheDocument();
  });

  it("names the step a funnel died at", async () => {
    renderPage();
    expect(await screen.findByText(/subscriptions/)).toBeInTheDocument();
  });

  it("says they bounced at entry rather than 'unknown' when no step was reached", async () => {
    overviewMock.mockResolvedValue(
      buildOverview({
        funnels: [
          {
            flow: "backfill_run",
            entries: 5,
            completions: 0,
            abandoned: 5,
            died_at: null,
          },
        ],
      }),
    );
    renderPage();
    expect(await screen.findByText(/bounced at entry/i)).toBeInTheDocument();
  });

  it("lists cold capabilities as the delete-candidate list", async () => {
    renderPage();
    expect(await screen.findByText("reports")).toBeInTheDocument();
    expect(screen.getByText("signals")).toBeInTheDocument();
  });

  it("renders in Arabic without falling back to the key", async () => {
    await setupTestI18n("ar");
    renderPage();
    expect(await screen.findByText("استخدام المنتج")).toBeInTheDocument();
  });
});
