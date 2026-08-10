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
const getCropAttrs = vi.fn();
vi.mock("@/api/cropAssignments", () => ({
  getBlockCropAttributes: (...args: unknown[]) => getCropAttrs(...args),
}));

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
    id: "00000000-0000-0000-0000-0000000000bc",
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
  responsible_membership_id: null,
};

function renderDock(detail: UnitDetail = DETAIL): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const node: ReactNode = (
    <BlockDock
      detail={detail}
      integration={null}
      loading={false}
      error={false}
      activeIndex="ndvi"
      onActiveIndexChange={() => {}}
      onClose={() => {}}
      farmId="f1"
      gridProductId={null}
      onReshape={() => {}}
      onInactivate={() => {}}
      onResponsibleChanged={() => {}}
    />
  );
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("BlockDock", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    caps.value = true;
    getCropAttrs.mockReset();
    getCropAttrs.mockResolvedValue({
      block_crop_id: "00000000-0000-0000-0000-0000000000bc",
      crop_path: "mango.alphonso",
      definitions: [
        {
          code: "establishment_method",
          name_en: "Establishment method",
          name_ar: "طريقة التأسيس",
          value_type: "single_select",
          unit_en: null,
          unit_ar: null,
          options: [{ code: "grafted_tree", name_en: "Grafted tree", name_ar: "x", sort_order: 1 }],
        },
        {
          code: "age_at_transplant_months",
          name_en: "Age at transplant",
          name_ar: "x",
          value_type: "integer",
          unit_en: "months",
          unit_ar: "x",
          options: null,
        },
        {
          code: "nursery_source",
          name_en: "Nursery / supplier",
          name_ar: "x",
          value_type: "text",
          unit_en: null,
          unit_ar: null,
          options: null,
        },
      ],
      // nursery_source deliberately absent — an unset field must not render.
      values: { establishment_method: "grafted_tree", age_at_transplant_months: 30 },
    });
  });

  it("shows the set crop fields in the Field tab, with option labels and units", async () => {
    // The feature looked unshipped because these lived three clicks away under
    // Manage -> Crop; the Field tab is where a user actually looks.
    renderDock();
    fireEvent.click(await screen.findByRole("tab", { name: /Field & plan/ }));

    expect(await screen.findByText("Establishment method")).toBeTruthy();
    // Option code mapped to its label, not the raw "grafted_tree".
    expect(screen.getByText("Grafted tree")).toBeTruthy();
    expect(screen.getByText("Age at transplant")).toBeTruthy();
    expect(screen.getByText("months")).toBeTruthy();
  });

  it("omits crop fields that hold no value", async () => {
    renderDock();
    fireEvent.click(await screen.findByRole("tab", { name: /Field & plan/ }));
    await screen.findByText("Establishment method");
    expect(screen.queryByText("Nursery / supplier")).toBeNull();
  });

  it("adds no crop-field rows for a crop with no definitions", async () => {
    // Wheat/olive blocks must look exactly as they did before this feature.
    getCropAttrs.mockResolvedValue({
      block_crop_id: "bc",
      crop_path: "olive",
      definitions: [],
      values: {},
    });
    renderDock();
    fireEvent.click(await screen.findByRole("tab", { name: /Field & plan/ }));
    await screen.findByText("Crop & plan");
    expect(screen.queryByText("Establishment method")).toBeNull();
    expect(screen.queryByText("Age at transplant")).toBeNull();
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
        {
          time: "2026-06-01",
          mean: "0.04",
          min: null,
          max: null,
          valid_pixels: 400,
          valid_pixel_pct: "98",
        },
        {
          time: "2026-06-30",
          mean: "0.05",
          min: null,
          max: null,
          valid_pixels: 400,
          valid_pixel_pct: "98",
        },
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

  it("translates the activity type rather than humanising the enum", async () => {
    renderDock({
      ...DETAIL,
      activities: [
        { date: "2026-07-02", label: "Soil prep", activity_type: "soil_prep", phase: "next7d" },
      ],
    });
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: /Field & plan/ }));
    expect(screen.getByText("Soil prep")).toBeTruthy();
  });
});

// Everything the dock renders has to follow the UI language, not just the
// chrome. These are the fields that were frozen in English: the ones the dock
// derives itself (weekday heads, activity types, growth stage) and the dates,
// which formatted against the BROWSER locale instead of the app's.
describe("BlockDock — Arabic", () => {
  beforeEach(async () => {
    await setupTestI18n("ar");
    caps.value = true;
    getCropAttrs.mockReset();
    getCropAttrs.mockResolvedValue({
      block_crop_id: "00000000-0000-0000-0000-0000000000bc",
      crop_path: "mango.alphonso",
      definitions: [],
      values: {},
    });
  });

  it("labels the growth stage and the activity type in Arabic", async () => {
    renderDock({
      ...DETAIL,
      activities: [
        { date: "2026-07-02", label: "Soil prep", activity_type: "soil_prep", phase: "next7d" },
      ],
    });
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: /الحقل/ }));
    // `fruit_set` / `soil_prep`, not the English humanisation of either.
    expect(await screen.findByText("عقد الثمار")).toBeTruthy();
    expect(screen.getByText("تحضير التربة")).toBeTruthy();
    expect(screen.queryByText("Fruit set")).toBeNull();
    expect(screen.queryByText("Soil prep")).toBeNull();
  });

  it("heads the forecast columns in Arabic instead of an en-US weekday", async () => {
    renderDock({
      ...DETAIL,
      weather_3d: [
        { day: "Today", date: "2026-06-30", temp_c_max: 38 },
        { day: "Wed", date: "2026-07-01", temp_c_max: 39 },
        { day: "Thu", date: "2026-07-02", temp_c_max: 37 },
      ],
    });
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: /المياه/ }));
    expect(screen.getByText("اليوم")).toBeTruthy();
    expect(screen.queryByText("Wed")).toBeNull();
    expect(screen.queryByText("Thu")).toBeNull();
  });

  it("formats the observation date against the UI language, not the browser", async () => {
    renderDock();
    // longDate() passed `undefined` as the locale, so an Arabic UI on an
    // en-US browser kept printing "Jun 30, 2026" beside Arabic chip labels.
    await waitFor(() => expect(screen.getByText("Block A2")).toBeTruthy());
    expect(screen.queryByText(/Jun 30, 2026/)).toBeNull();
  });
});
