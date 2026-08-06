import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PixelBudget, PixelExplain, SceneDetail } from "@/api/observer";
import { setupTestI18n } from "@/i18n/testing";

import { ObserverSceneDetailPage } from "./ObserverSceneDetailPage";

/*
 * The map needs WebGL, which jsdom has none of. It is lazily imported by the
 * page precisely so it can be stubbed here and the rest of the surface stays
 * testable.
 */
vi.mock("@/modules/admin/components/observer/ObserverSceneMap", () => ({
  ObserverSceneMap: () => <div data-testid="scene-map" />,
}));

const s2Detail: SceneDetail = {
  tile_server_base_url: "https://tiles.example",
  s3_bucket: "imagery",
  job_id: "j1",
  block_id: "b1",
  product_id: "p1",
  block_code: "B-07",
  block_name: "North Mango",
  farm_id: "f1",
  scene_id: "S2B_MSIL2A_20260614T083709",
  scene_datetime: "2026-06-14T08:37:00Z",
  status: "succeeded",
  stac_item_id: "S2B_X",
  cloud_cover_pct: 4.2,
  valid_pixel_pct: 91.6,
  error_code: null,
  error_message: null,
  requested_at: null,
  started_at: null,
  completed_at: null,
  provider_code: "sentinel_hub",
  provider_name: "Sentinel Hub",
  product_code: "s2_l2a",
  product_name: "Sentinel-2 L2A",
  resolution_m: 10,
  bands: ["blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"],
  supported_indices: ["ndvi", "ndmi"],
  aoi_hash: "a41f9c",
  boundary_geojson: { type: "Polygon", coordinates: [] },
  area_m2: 120000,
  raw_asset_key: "sentinel_hub/s2_l2a/S2B_MSIL2A_20260614T083709/a41f9c/raw_bands.tif",
  index_asset_keys: {},
  mask_ruleset: "s2_scl_v1",
  mask_classes: [0, 1, 3, 8, 9, 10, 11],
  grid: {
    grid_config_id: "g1",
    cell_size_m: 40,
    utm_srid: 32636,
    cell_count: 24,
    effective_from: "2026-04-02T00:00:00Z",
    effective_to: null,
  },
  // Two executions of the same scene under different calc versions — the
  // shape a silent recompute leaves behind.
  calc_runs: [
    {
      id: "r2",
      job_id: "j1",
      calc_version: "idx-2026.08",
      mask_ruleset: "s2_scl_v1",
      trigger: "live",
      outcome: "ok",
      error: null,
      aoi_pixel_count: 3508,
      masked_pixel_count: 239,
      cell_count: 24,
      grid_config_id: "g1",
      band_order: ["red", "nir"],
      per_index: { ndvi: { valid: 3214, nodata: 55 } },
      started_at: "2026-06-14T09:01:00Z",
      completed_at: "2026-06-14T09:02:00Z",
      duration_ms: 18400,
      created_at: "2026-06-14T09:02:00Z",
    },
    {
      id: "r1",
      job_id: "j1",
      calc_version: "idx-2026.03",
      mask_ruleset: "s2_scl_v1",
      trigger: "live",
      outcome: "ok",
      error: null,
      aoi_pixel_count: 3508,
      masked_pixel_count: 0,
      cell_count: 24,
      grid_config_id: "g1",
      band_order: ["red", "nir"],
      per_index: { ndvi: { valid: 3508, nodata: 0 } },
      started_at: "2026-03-02T09:01:00Z",
      completed_at: "2026-03-02T09:02:00Z",
      duration_ms: 17900,
      created_at: "2026-03-02T09:02:00Z",
    },
  ],
};

const clearPixel: PixelExplain = {
  job_id: "j1",
  scene_id: s2Detail.scene_id,
  scene_datetime: s2Detail.scene_datetime,
  block_id: "b1",
  raw_asset_key: s2Detail.raw_asset_key as string,
  row: 41,
  col: 78,
  lon: 31.21,
  lat: 30.01,
  inside_aoi: true,
  band_values: { red: 0.0871, nir: 0.314 },
  scl_value: 4,
  scl_label: "vegetation",
  masked: false,
  mask_reason: null,
  indices: {
    ndvi: {
      value: 0.5657,
      raw_value: 0.5657,
      formula_text: "(NIR - Red) / (NIR + Red)",
      substituted: "(0.3140 - 0.0871) / (0.3140 + 0.0871)",
      excluded_reason: null,
    },
  },
  unavailable_indices: {},
  masking_available: true,
};

const budget: PixelBudget = {
  job_id: "j1",
  aoi_pixel_count: 3508,
  masked_pixel_count: 239,
  per_index: { ndvi: { aoi: 3508, masked: 239, nodata: 55, valid: 3214 } },
  recomputed_live: true,
};

const getSceneDetail = vi.fn(() => Promise.resolve(s2Detail));
const explainPixel = vi.fn(() => Promise.resolve(clearPixel));
const getPixelBudget = vi.fn(() => Promise.resolve(budget));

vi.mock("@/api/observer", async () => {
  const actual = await vi.importActual<typeof import("@/api/observer")>("@/api/observer");
  return {
    ...actual,
    getSceneDetail: (...args: unknown[]) => getSceneDetail(...(args as [])),
    explainPixel: (...args: unknown[]) => explainPixel(...(args as [])),
    getPixelBudget: (...args: unknown[]) => getPixelBudget(...(args as [])),
    getSceneIndices: vi.fn(() =>
      Promise.resolve([
        {
          index_code: "ndvi",
          mean: 0.5123,
          min: null,
          max: null,
          p10: null,
          p50: null,
          p90: null,
          std_dev: null,
          valid_pixel_count: 3214,
          total_pixel_count: 3508,
          valid_pixel_pct: 91.62,
          cloud_cover_pct: 4.2,
          baseline_deviation: 0.42,
          stac_item_id: "S2B_X",
          inserted_at: "2026-06-14T09:02:00Z",
        },
      ]),
    ),
  };
});

function renderPage(url = "/platform/observer/scenes/j1?tenant=t1&index=ndvi") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[url]}>
      <QueryClientProvider client={qc}>
        <Routes>
          <Route path="/platform/observer/scenes/:jobId" element={<ObserverSceneDetailPage />} />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("ObserverSceneDetailPage", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
  });

  it("names the grid that governed the scene, with its valid-from date", async () => {
    renderPage();
    // The block name appears in both the breadcrumb and the title.
    await waitFor(() => expect(screen.getAllByText(/North Mango/).length).toBeGreaterThan(0));
    expect(screen.getByText(/40 m/)).toBeInTheDocument();
    // Valid time, not "the current grid" — showing today's geometry would
    // attribute cells this scene never had.
    expect(screen.getByText(/valid from 2026-04-02/)).toBeInTheDocument();
  });

  it("shows the mask ruleset and its classes rather than leaving them implicit", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/s2_scl_v1/)).toBeInTheDocument());
    expect(screen.getByText(/0, 1, 3, 8, 9, 10, 11/)).toBeInTheDocument();
  });

  it("does not read a raster until the operator asks for the pixel budget", async () => {
    renderPage();
    // The block name appears in both the breadcrumb and the title.
    await waitFor(() => expect(screen.getAllByText(/North Mango/).length).toBeGreaterThan(0));
    expect(getPixelBudget).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Compute pixel budget/i }));
    await waitFor(() => expect(getPixelBudget).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("3,214")).toBeInTheDocument();
  });

  it("prompts for a click before any pixel has been chosen", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText(/Click a pixel/i).length).toBeGreaterThan(0));
    expect(explainPixel).not.toHaveBeenCalled();
  });

  it("offers only the indices the product actually supports", async () => {
    renderPage();
    // The block name appears in both the breadcrumb and the title.
    await waitFor(() => expect(screen.getAllByText(/North Mango/).length).toBeGreaterThan(0));
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["NDVI", "NDMI"]);
  });
});
