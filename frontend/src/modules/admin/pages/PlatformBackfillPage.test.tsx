import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { PlatformBackfillPage } from "./PlatformBackfillPage";

const tenants = [{ id: "t1", name: "Agrosina", slug: "agrosina", schema_name: "tenant_abc" }];
const farms = [
  { id: "f1", name: "suez", code: "SUEZ", block_count: 37, active_run_id: null },
  // Already occupied — one run per farm, so this must not be selectable.
  { id: "f2", name: "busy-farm", code: "BUSY", block_count: 4, active_run_id: "r-existing" },
];

vi.mock("@/api/backfill", async () => {
  const actual = await vi.importActual<typeof import("@/api/backfill")>("@/api/backfill");
  return {
    ...actual,
    listBackfillTenants: vi.fn(() => Promise.resolve(tenants)),
    listBackfillFarms: vi.fn(() => Promise.resolve(farms)),
    listBackfillRuns: vi.fn(() => Promise.resolve([])),
    estimateBackfill: vi.fn(() =>
      Promise.resolve({
        days: 366,
        blocks: 37,
        subscriptions: 35,
        estimated_scenes: 2562,
        estimated_units: 2562,
        units_estimated: true,
        weather_hours: 8784,
        weather_subscriptions: 4,
        weather_providers: ["open_meteo"],
      }),
    ),
    createBackfillRun: vi.fn(),
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PlatformBackfillPage />
    </QueryClientProvider>,
  );
}

describe("PlatformBackfillPage", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("offers the three capabilities as tabs", () => {
    renderPage();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
  });

  it("disables a farm that already has a run in progress", async () => {
    renderPage();
    const user = userEvent.setup();
    await waitFor(() => screen.getByRole("option", { name: /Agrosina/i }));
    await user.selectOptions(screen.getByLabelText(/tenant/i), "t1");

    await waitFor(() => {
      expect(screen.getByRole("option", { name: /busy-farm/i })).toBeDisabled();
    });
    expect(screen.getByRole("option", { name: /suez/i })).not.toBeDisabled();
  });

  it("shows the estimate as an approximation, never as a quota reading", async () => {
    renderPage();
    const user = userEvent.setup();
    await waitFor(() => screen.getByRole("option", { name: /Agrosina/i }));
    await user.selectOptions(screen.getByLabelText(/tenant/i), "t1");
    await waitFor(() => screen.getByRole("option", { name: /suez/i }));
    await user.selectOptions(screen.getByLabelText(/farm/i), "f1");
    await user.click(screen.getByRole("button", { name: /dry run/i }));

    await waitFor(() => {
      expect(screen.getByText(/estimate, not a quota reading/i)).toBeInTheDocument();
    });
  });

  it("does not offer a dry run on the indices tab — it costs nothing", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /compute indices/i }));
    expect(screen.queryByRole("button", { name: /dry run/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /compute indices/i })).toBeInTheDocument();
  });
});
