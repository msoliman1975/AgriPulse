import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { UnitDetail } from "../map/types";

import { BlockDock } from "./BlockDock";

// The Conditions tab calls the tree-explain endpoint, which is gated on
// `recommendation.read`. Roles without it must not see a tab that 403s.
const caps = vi.hoisted(() => ({ value: true }));
vi.mock("@/rbac/useCapability", () => ({
  useCapability: () => caps.value,
}));

vi.mock("@/api/recommendations", async () => {
  const actual =
    await vi.importActual<typeof import("@/api/recommendations")>("@/api/recommendations");
  return {
    ...actual,
    explainBlock: vi.fn(() =>
      Promise.resolve({
        block_id: "b1",
        evaluated_at: "2026-06-30T00:00:00Z",
        crop_path: null,
        trees: [],
      }),
    ),
  };
});

vi.mock("@/modules/farms/components/AreaDisplay", () => ({
  AreaDisplay: ({ areaM2 }: { areaM2: number }) => <span>{areaM2 / 10_000} ha</span>,
}));

const DETAIL: UnitDetail = {
  id: "b1",
  name: "Block A2",
  type: "block",
  parent_pivot_id: null,
  crop: "Mango",
  area_ha: 4,
  health: "watch",
  last_updated: "2026-06-30T00:00:00Z",
  alerts: [],
  indices: {
    ndvi: { current: 0.58, trend_7d_delta: 0.02, series_30d: [] },
    ndre: { current: 0.3, trend_7d_delta: 0, series_30d: [] },
    ndwi: { current: 0.05, trend_7d_delta: 0, series_30d: [] },
  },
  irrigation: { last: null, next: null, soil_moisture_pct: 35, soil_status: "optimal" },
  recommendations: [],
  activities: [],
  weather_3d: [],
  plan: null,
  crop_assignment: {
    crop_name: "Mango",
    variety_name: "Alphonso",
    strain_name: null,
    crop_path: "mango.alphonso",
    season_label: "Summer 2026",
    planting_date: "2017-11-04",
    growth_stage: "fruit_set",
    status: "active",
  },
  signals: [],
  integration: null,
};

function renderDock(detail: UnitDetail = DETAIL): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const node: ReactNode = (
    <BlockDock
      detail={detail}
      loading={false}
      error={false}
      activeIndex="ndvi"
      onActiveIndexChange={() => {}}
      onClose={() => {}}
      farmId="f1"
      gridProductId={null}
      onReshape={() => {}}
      onInactivate={() => {}}
    />
  );
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("BlockDock", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    caps.value = true;
  });

  it("renders the block identity and the tab strip", async () => {
    renderDock();
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    expect(screen.getByRole("tab", { name: /Overview/ })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Field & plan/ })).toBeTruthy();
  });

  it("shows the assigned crop in the title bar, not 'no crop assigned'", async () => {
    // Regression: the bar read `UnitDetail.crop`, a hardcoded null left over
    // from the map prototype, so every block claimed to have no crop — which
    // also made a successful crop assignment look like it had not saved.
    renderDock();
    await waitFor(() => expect(screen.getByText("Mango · Alphonso")).toBeTruthy());
    expect(screen.queryByText(/no crop assigned/i)).toBeNull();
  });

  it("falls back to 'no crop assigned' only when there really is none", async () => {
    renderDock({ ...DETAIL, crop: null, crop_assignment: null });
    await waitFor(() => expect(screen.getByText(/no crop assigned/i)).toBeTruthy());
  });

  it("puts the title fields in the agreed order", async () => {
    renderDock();
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    const labels = screen
      .getAllByText(/^(Block|Crop|Health|Alerts|Date)$/)
      .map((el) => el.textContent);
    expect(labels).toEqual(["Block", "Crop", "Health", "Alerts", "Date"]);
  });

  it("offers a resize handle", async () => {
    renderDock();
    await waitFor(() => expect(screen.getByLabelText(/resize/i)).toBeTruthy());
  });

  it("shows the Conditions tab when the user can read recommendations", async () => {
    renderDock();
    await waitFor(() => expect(screen.getByRole("tab", { name: /Conditions/ })).toBeTruthy());
  });

  it("hides the Conditions tab entirely when the user cannot", async () => {
    caps.value = false;
    renderDock();
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    // Hidden, not rendered-then-403: the endpoint would reject the call.
    expect(screen.queryByRole("tab", { name: /Conditions/ })).toBeNull();
    // The rest of the dock is unaffected.
    expect(screen.getByRole("tab", { name: /Overview/ })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Manage/ })).toBeTruthy();
  });
});
