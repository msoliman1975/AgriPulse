import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

// The family tabs chart their block-level index over a chosen range.
vi.mock("@/api/indices", async () => {
  const actual = await vi.importActual<typeof import("@/api/indices")>("@/api/indices");
  return { ...actual, getTimeseries: vi.fn(() => Promise.resolve({ points: [] })) };
});

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

  it("gives every index family its own tab", async () => {
    renderDock();
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    for (const name of [/Vigour & canopy/, /Nutrition/, /^Moisture$/]) {
      expect(screen.getByRole("tab", { name })).toBeTruthy();
    }
    // The undifferentiated "Index" tab the families replace is gone.
    expect(screen.queryByRole("tab", { name: /^Index$/ })).toBeNull();
    // "Moisture" and "Water & environment" are different subjects; the family
    // tab used to be called "Water & moisture", which read as the same one.
    expect(screen.queryByRole("tab", { name: /Water & moisture/ })).toBeNull();
  });

  it("defines every index in the family and says how to read its scale", async () => {
    renderDock();
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: /^Moisture$/ }));

    // Both members are defined, including the grid-only one that has no value
    // of its own — a definition is reference material, not a reading.
    expect(screen.getAllByText("Definition")).toHaveLength(2);
    expect(screen.getAllByText("How to read it")).toHaveLength(2);
    expect(screen.getByText(/McFeeters/)).toBeTruthy();
    expect(screen.getByText(/Leaf water absorbs shortwave infrared/)).toBeTruthy();
    // The scale text has to warn that this family's charted index is inverted.
    expect(screen.getByText(/the scale is inverted against the canopy indices/)).toBeTruthy();
    expect(screen.getByText(/moves with the crop and its growth stage/)).toBeTruthy();
  });

  it("turns the charted reading into a sentence rather than a bare decimal", async () => {
    const { getTimeseries } = await import("@/api/indices");
    // NDWI 0.05 is above McFeeters' zero threshold: standing water, which is
    // the opposite verdict to what the same number would mean on NDVI.
    vi.mocked(getTimeseries).mockResolvedValueOnce({
      block_id: "b1",
      index_code: "ndwi",
      granularity: "daily",
      points: [
        // The API serves NUMERIC as a string; the view runs it through Number().
        { time: "2026-06-01", mean: "0.04", min: null, max: null, valid_pixels: 400, valid_pixel_pct: "98" },
        { time: "2026-06-30", mean: "0.05", min: null, max: null, valid_pixels: 400, valid_pixel_pct: "98" },
      ],
    });

    renderDock();
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: /^Moisture$/ }));

    await waitFor(() =>
      expect(screen.getByText(/Above zero: open water on the block/)).toBeTruthy(),
    );
  });

  it("shows a family's members with their readings, grid-only ones disabled", async () => {
    renderDock();
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: /Nutrition/ }));

    // NDRE is block level, so it carries a value the flat pill row dropped.
    const ndre = screen.getByRole("button", { name: /NDRE/ });
    expect(ndre.textContent).toContain("0.30");
    expect(ndre.hasAttribute("disabled")).toBe(false);

    // GNDVI exists only on the sub-block grid: shown, but not selectable.
    const gndvi = screen.getByRole("button", { name: /GNDVI/ });
    expect(gndvi.hasAttribute("disabled")).toBe(true);

    // Nothing from another family leaks in.
    expect(screen.queryByRole("button", { name: /NDWI/ })).toBeNull();
  });

  it("keeps water in Water & environment and out of Field & plan", async () => {
    // The two tabs used to overlap: irrigation and soil moisture rendered in
    // Field & plan, and soil moisture again on Overview.
    renderDock({
      ...DETAIL,
      irrigation: {
        last: null,
        next: { date: "2026-07-02", volume_mm: 40 },
        soil_moisture_pct: 35,
        soil_status: "optimal",
      },
    });
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    expect(screen.queryByText(/Soil moisture/)).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: /Field & plan/ }));
    expect(screen.queryByText(/Soil moisture/)).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: /Water & environment/ }));
    expect(screen.getAllByText("Soil moisture")).toHaveLength(1);
  });

  it("flags an emergency irrigation instead of printing it as routine", async () => {
    renderDock({
      ...DETAIL,
      irrigation: {
        last: null,
        next: { date: "2026-07-02", volume_mm: 40, is_emergency: true },
        soil_moisture_pct: 12,
        soil_status: "critical",
      },
    });
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: /Water & environment/ }));
    expect(screen.getByTitle(/Emergency irrigation/)).toBeTruthy();
  });

  it("puts the plan back in the tab named after it", async () => {
    // Growth stage and season had no home once the drawer's Plan section went.
    renderDock({
      ...DETAIL,
      plan: { season_label: "Summer", season_year: 2026, name: null, status: "active" },
    });
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: /Field & plan/ }));
    expect(screen.getByText("Fruit set")).toBeTruthy();
    expect(screen.getByText("Summer (2026)")).toBeTruthy();
  });
});
