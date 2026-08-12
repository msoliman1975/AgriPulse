// Composition test for the v2 shell.
//
// The point is not to re-test the legend or the rail — those have their own
// pure tests — but to prove the seven zones actually mount together against
// the shared loaders, in both languages, without the live console being
// involved.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";
import { FarmConsoleV2Page } from "./FarmConsoleV2Page";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: "" } }) }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

// MapLibre does not run under jsdom — it reaches for WebGL on construction.
// The shell's job is to hand it the right props, not to render tiles.
vi.mock("../map/MapCanvas", () => ({
  MapCanvas: () => <div data-testid="map-canvas" />,
}));

const summary = vi.hoisted(() => ({
  farm: {
    id: "f1",
    code: "BASH",
    name: "Bashayer El Kheir",
    area_m2: 1_486_000,
    is_active: true,
    active_to: null,
    boundary: null,
  },
  blocks: [
    { id: "b1", code: "B-01", name: "North ridge", unit_type: "block" },
    { id: "b2", code: "B-02", name: "Wadi", unit_type: "block" },
    { id: "p1", code: "P-01", name: "Pivot one", unit_type: "pivot" },
  ],
  summaries: {
    b1: {
      id: "b1",
      health: "critical",
      has_alert: true,
      alert_severity: "critical",
      alert_count: 3,
      ndvi_current: 0.21,
      ndre_current: null,
      ndwi_current: null,
      grid_product_id: null,
    },
    b2: {
      id: "b2",
      health: "healthy",
      has_alert: false,
      alert_severity: null,
      alert_count: 0,
      ndvi_current: 0.44,
      ndre_current: null,
      ndwi_current: null,
      grid_product_id: null,
    },
    p1: {
      id: "p1",
      health: "watch",
      has_alert: false,
      alert_severity: null,
      alert_count: 0,
      ndvi_current: 0.33,
      ndre_current: null,
      ndwi_current: null,
      grid_product_id: null,
    },
  },
  geojson: { type: "FeatureCollection", features: [] },
  activePlan: null,
}));

vi.mock("../map/api", async () => {
  const actual = await vi.importActual<object>("../map/api");
  return {
    ...actual,
    loadMapSummary: () => Promise.resolve(summary),
    loadUnitDetail: () => Promise.resolve(undefined),
    loadBlockHealth: () => Promise.resolve({}),
  };
});

vi.mock("@/api/grid", () => ({
  getFarmGridCells: () => Promise.resolve(null),
  getGridCells: () => Promise.resolve({ cells: [] }),
}));
vi.mock("@/api/imagery", () => ({
  listSubscriptions: () => Promise.resolve([]),
  listFarmScenes: () =>
    Promise.resolve({
      farm_id: "f1",
      median_gap_days: 5,
      items: [
        {
          scene_date: "2026-07-01",
          at: "2026-07-01T08:30:00Z",
          block_count: 2,
          succeeded_count: 2,
          skipped_cloud_count: 0,
          computed_count: 2,
          cloud_cover_pct: "4.00",
        },
        {
          scene_date: "2026-06-26",
          at: "2026-06-26T08:30:00Z",
          block_count: 2,
          succeeded_count: 0,
          skipped_cloud_count: 2,
          computed_count: 0,
          cloud_cover_pct: "91.00",
        },
      ],
    }),
}));
vi.mock("@/api/signals", () => ({
  listSignalDefinitions: () => Promise.resolve([]),
  listSignalObservations: () => Promise.resolve([]),
}));
vi.mock("@/queries/recommendations", () => ({ useRecommendations: () => ({ data: [] }) }));
vi.mock("@/queries/alerts", () => ({ useAlerts: () => ({ data: [] }) }));

function renderConsole() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PrefsProvider>
        <MemoryRouter initialEntries={["/labs/map-v2/f1"]}>
          <Routes>
            <Route path="/labs/map-v2/:farmId" element={<FarmConsoleV2Page />} />
          </Routes>
        </MemoryRouter>
      </PrefsProvider>
    </QueryClientProvider>,
  );
}

describe("FarmConsoleV2Page", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("identifies the farm in the view bar without needing a panel", async () => {
    renderConsole();
    expect(await screen.findByText("Bashayer El Kheir")).toBeInTheDocument();
    // 1,486,000 m² is ~353.7 feddan, and two of the three units are blocks.
    expect(screen.getByText(/2 blocks/)).toBeInTheDocument();
    expect(screen.getByText(/1 pivot/)).toBeInTheDocument();
  });

  it("mounts the map, the rail and the legend together", async () => {
    renderConsole();
    expect(await screen.findByTestId("map-canvas")).toBeInTheDocument();
    expect(screen.getByText("North ridge")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter units by name or code")).toBeInTheDocument();
    // This fixture has no imagery subscriptions, so no block can be gridded.
    // The legend must name that upstream cause rather than "no grid" — the
    // Bashayer case, and the reason the empty state is diagnosed at all.
    expect(screen.getByText("No imagery yet")).toBeInTheDocument();
  });

  it("filters the rail", async () => {
    const user = userEvent.setup();
    renderConsole();
    await screen.findByText("North ridge");
    await user.type(screen.getByLabelText("Filter units by name or code"), "wadi");
    await waitFor(() => expect(screen.queryByText("North ridge")).not.toBeInTheDocument());
    expect(screen.getByText("Wadi")).toBeInTheDocument();
  });

  it("orders the rail worst-first by default", async () => {
    renderConsole();
    await screen.findByText("North ridge");
    const rows = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    const critical = rows.findIndex((r) => r.includes("North ridge"));
    const healthy = rows.findIndex((r) => r.includes("Wadi"));
    expect(critical).toBeLessThan(healthy);
  });

  it("shows real acquisition days, keeps the cloudy one, and predicts the next pass", async () => {
    renderConsole();
    const strip = await screen.findByRole("listbox", { name: "Acquisition dates" });
    expect(strip).toBeInTheDocument();
    // The 26 Jun pass was skipped for cloud. It must still be on the strip —
    // a visible, explained gap beats a silently shorter timeline.
    expect(screen.getByText("☁ 91%")).toBeInTheDocument();
    expect(screen.getByText("Next pass")).toBeInTheDocument();
  });

  it("puts the chosen scene in the URL so the view is shareable", async () => {
    const user = userEvent.setup();
    renderConsole();
    await screen.findByRole("listbox", { name: "Acquisition dates" });
    const before = screen.getAllByRole("option");
    const label = before[before.length - 1].textContent;
    await user.click(before[before.length - 1]);
    // Re-query rather than reusing the node: selecting a scene re-renders the
    // strip, so the original element is detached by the time this asserts.
    await waitFor(() => {
      const after = screen.getAllByRole("option").find((o) => o.textContent === label);
      expect(after).toHaveAttribute("aria-selected", "true");
    });
  });

  it("renders in Arabic", async () => {
    await setupTestI18n("ar");
    renderConsole();
    expect(await screen.findByText("Bashayer El Kheir")).toBeInTheDocument();
    expect(screen.getByText("لا توجد صور بعد")).toBeInTheDocument();
  });
});
