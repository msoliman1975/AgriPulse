import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ObserverOverview, ObserverScene } from "@/api/observer";
import { setupTestI18n } from "@/i18n/testing";

import { PlatformObserverPage } from "./PlatformObserverPage";

/*
 * These cover the two places where a wrong rendering choice would mislead an
 * operator into chasing a defect that does not exist:
 *
 *   * a "not applicable" stage must not read as a zero-of-something failure;
 *   * an ungridded scene must say so rather than showing "0 / 0".
 *
 * Plus the handover property the whole surface depends on — the selection
 * lives in the URL, so a view can be sent to someone else.
 */

const tenants = [{ id: "t1", name: "Agrosina", slug: "agrosina", schema_name: "tenant_abc" }];

const farms = [
  {
    id: "f1",
    name: "Suez",
    code: "SUEZ",
    block_count: 36,
    blocks_with_imagery_sub: 36,
    blocks_with_grid: 12,
    has_weather_sub: true,
    first_scene_at: "2015-08-19T08:00:00Z",
    last_scene_at: "2026-08-04T10:41:00Z",
  },
];

const overview: ObserverOverview = {
  farm_id: "f1",
  block_count: 36,
  window_from: "2026-01-01T00:00:00Z",
  window_to: "2026-08-06T00:00:00Z",
  stages: [
    {
      key: "discovered",
      label: "Discovered",
      count: 1284,
      expected: null,
      shortfall: null,
      verdict: "info",
      detail: { failed: 38, in_flight: 0, skipped: 0 },
    },
    {
      key: "indices",
      label: "Indices computed",
      count: 1215,
      expected: 1246,
      shortfall: 31,
      verdict: "warn",
      detail: {},
    },
    {
      key: "cells",
      label: "Cell aggregates",
      count: 0,
      expected: 0,
      shortfall: 0,
      verdict: "not_applicable",
      detail: {},
    },
  ],
  calc_versions: [],
  trend_product_ambiguous: false,
  consumers_are_window_proxy: true,
};

const scenes: ObserverScene[] = [
  {
    job_id: "j1",
    block_id: "b1",
    block_name: "North Mango",
    block_code: "B-07",
    product_id: "p1",
    scene_id: "S2B_MSIL2A_20260614T083709",
    scene_datetime: "2026-06-14T08:37:00Z",
    status: "succeeded",
    cloud_cover_pct: 4.2,
    valid_pixel_pct: 91.6,
    error_code: null,
    error_message: null,
    stac_item_id: "S2B_X",
    started_at: null,
    completed_at: null,
    duration_s: 18.4,
    indices_written: 7,
    cells_written: 24,
    cells_expected: 24,
    gridded: true,
  },
  {
    job_id: "j2",
    block_id: "b2",
    block_name: "South Citrus",
    block_code: "B-12",
    product_id: "p1",
    scene_id: "S2B_MSIL2A_20260614T083709",
    scene_datetime: "2026-06-14T08:37:00Z",
    status: "succeeded",
    cloud_cover_pct: 4.2,
    valid_pixel_pct: 43.1,
    error_code: null,
    error_message: null,
    stac_item_id: "S2B_Y",
    started_at: null,
    completed_at: null,
    duration_s: 11.2,
    indices_written: 7,
    cells_written: 0,
    cells_expected: 0,
    gridded: false,
  },
];

vi.mock("@/api/observer", async () => {
  const actual = await vi.importActual<typeof import("@/api/observer")>("@/api/observer");
  return {
    ...actual,
    listObserverTenants: vi.fn(() => Promise.resolve(tenants)),
    listObserverFarms: vi.fn(() => Promise.resolve(farms)),
    listObserverProducts: vi.fn(() => Promise.resolve([])),
    getObserverOverview: vi.fn(() => Promise.resolve(overview)),
    getObserverHistogram: vi.fn(() => Promise.resolve([])),
    listObserverScenes: vi.fn(() => Promise.resolve(scenes)),
    getSceneIndices: vi.fn(() => Promise.resolve([])),
  };
});

function renderPage(initialUrl = "/platform/observer") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <QueryClientProvider client={qc}>
        <PlatformObserverPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("PlatformObserverPage", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("asks for a farm before showing any pipeline numbers", () => {
    renderPage();
    expect(screen.getByText(/Pick a tenant and a farm/i)).toBeInTheDocument();
  });

  it("restores the whole selection from the URL so a view can be handed over", async () => {
    renderPage("/platform/observer?tenant=t1&farm=f1&from=2026-01-01&to=2026-08-06&bucket=month");
    await waitFor(() => expect(screen.getByText(/Pipeline stages/i)).toBeInTheDocument());
    expect(screen.getByText("1,284")).toBeInTheDocument();
  });

  it("shows a not-applicable stage as such, never as a zero-of-something failure", async () => {
    renderPage("/platform/observer?tenant=t1&farm=f1&from=2026-01-01&to=2026-08-06");
    await waitFor(() => expect(screen.getByText(/Cell aggregates/i)).toBeInTheDocument());
    expect(screen.getByText(/not applicable/i)).toBeInTheDocument();
    // The shortfall marker belongs to the flagged stage only.
    expect(screen.queryByText("−0")).not.toBeInTheDocument();
  });

  it("explains a flagged stage in words rather than leaving a bare colour", async () => {
    renderPage("/platform/observer?tenant=t1&farm=f1&from=2026-01-01&to=2026-08-06");
    await waitFor(() => expect(screen.getByText(/wrote no aggregates/i)).toBeInTheDocument());
  });

  it("labels an ungridded scene instead of rendering 0 / 0", async () => {
    renderPage("/platform/observer?tenant=t1&farm=f1&from=2026-01-01&to=2026-08-06");
    await waitFor(() => expect(screen.getByText(/South Citrus/i)).toBeInTheDocument());
    expect(screen.getByText(/not gridded/i)).toBeInTheDocument();
    expect(screen.getByText("24 / 24")).toBeInTheDocument();
    expect(screen.queryByText("0 / 0")).not.toBeInTheDocument();
  });

  it("writes the tenant choice back into the URL", async () => {
    renderPage();
    const user = userEvent.setup();
    await waitFor(() => screen.getByRole("option", { name: /Agrosina/i }));
    await user.selectOptions(screen.getByLabelText(/tenant/i), "t1");
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /Suez/i })).toBeInTheDocument();
    });
  });
});
