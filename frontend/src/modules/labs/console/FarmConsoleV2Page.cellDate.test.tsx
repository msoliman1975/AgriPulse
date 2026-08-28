// The cell mesh is on an older day than the strip — does the console SAY so?
//
// Its own file rather than a case in FarmConsoleV2Page.test.tsx: that fixture
// has no imagery subscriptions, so no block is gridded and the mesh never
// loads. This one needs a gridded block carrying a stale reading.
//
// Asserted on the rendered sentence, not on the hook's return value. The rule
// itself is covered in cellDateGap.test.ts; what this proves is that the
// sentence reaches the screen, in both languages.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";
import { FarmConsoleV2Page } from "./FarmConsoleV2Page";

vi.mock("react-oidc-context", () => ({ useAuth: () => ({ user: { access_token: "" } }) }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
vi.mock("../map/MapCanvas", () => ({ MapCanvas: () => <div data-testid="map-canvas" /> }));

const summary = vi.hoisted(() => ({
  farm: {
    id: "f1",
    code: "MANGO",
    name: "Mango Republic",
    area_m2: 1_486_000,
    is_active: true,
    active_to: null,
    boundary: null,
  },
  blocks: [{ id: "b1", code: "B-01", name: "North ridge", unit_type: "block" }],
  summaries: {
    b1: {
      id: "b1",
      health: "healthy",
      has_alert: false,
      alert_severity: null,
      alert_count: 0,
      ndvi_current: 0.44,
      ndre_current: null,
      ndwi_current: null,
      // A gridded block: this is what makes the mesh load at all.
      grid_product_id: "p1",
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

// The production shape: the backfill has reached 2025-07-23, the strip offers
// days into 2026-08, and `at` resolves every one of them to the July 2025 row.
vi.mock("@/api/grid", () => ({
  getFarmGridCells: () =>
    Promise.resolve({
      farm_id: "f1",
      index_code: "ndvi",
      blocks: [
        {
          block_id: "b1",
          product_id: "p1",
          at: "2025-07-23T08:41:47.247000+00:00",
          cells: [
            {
              cell_id: "c1",
              row_idx: 0,
              col_idx: 0,
              area_m2: "10000",
              centroid_lon: 31.2,
              centroid_lat: 30.1,
              geometry: {
                type: "Polygon",
                coordinates: [
                  [
                    [31.2, 30.1],
                    [31.21, 30.1],
                    [31.21, 30.11],
                    [31.2, 30.1],
                  ],
                ],
              },
              mean: "0.41",
              valid_pixel_pct: "98.0",
              time: "2025-07-23T08:41:47.247000+00:00",
            },
          ],
        },
      ],
    }),
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
          scene_date: "2026-08-25",
          at: "2026-08-25T08:30:00Z",
          block_count: 1,
          succeeded_count: 1,
          skipped_cloud_count: 0,
          computed_count: 1,
          cloud_cover_pct: "4.00",
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

describe("FarmConsoleV2Page cell-date notice", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("names both days when the mesh is older than the strip", async () => {
    renderConsole();
    expect(
      await screen.findByText(/Sub-block cells are from 2025-07-23, not 2026-08-25/),
    ).toBeInTheDocument();
  });

  it("renders the notice in Arabic", async () => {
    await setupTestI18n("ar");
    renderConsole();
    expect(await screen.findByText(/2025-07-23/)).toBeInTheDocument();
    // The English sentence must not survive under an Arabic locale — a missing
    // translation falls back to English and still contains both dates.
    expect(screen.queryByText(/Sub-block cells are from/)).not.toBeInTheDocument();
  });
});
