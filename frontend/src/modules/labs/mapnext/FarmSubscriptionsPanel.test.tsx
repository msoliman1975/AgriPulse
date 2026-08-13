import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { FarmSubscriptionsPanel } from "./FarmSubscriptionsPanel";

// Replaces the "apply subscriptions" tests that lived in
// BlockDefaultsPanel.test.tsx. The bug those guarded — Apply reconciling
// against a template stored on the server, so an unsaved or empty template
// made it a silent no-op that still reported success — cannot happen here,
// because there is no template and no apply step. A change IS the
// subscription. These tests hold that property.

const PRODUCT_ID = "019eab8c-6550-7827-b10d-007109e77470";

const h = vi.hoisted(() => ({
  imagery: vi.fn(),
  weather: vi.fn(),
  subscribeImagery: vi.fn(),
  updateImagery: vi.fn(),
  subscribeWeather: vi.fn(),
  updateWeather: vi.fn(),
}));

vi.mock("@/api/farmSubscriptions", () => ({
  listFarmImagerySubscriptions: h.imagery,
  listFarmWeatherSubscriptions: h.weather,
  subscribeFarmImagery: h.subscribeImagery,
  subscribeFarmWeather: h.subscribeWeather,
  updateFarmImagerySubscription: h.updateImagery,
  updateFarmWeatherSubscription: h.updateWeather,
}));

vi.mock("@/api/config", () => ({
  getConfig: vi.fn(async () => ({
    tile_server_base_url: "https://tiles.test",
    s3_bucket: "b",
    cloud_cover_visualization_max_pct: 60,
    cloud_cover_aggregation_max_pct: 30,
    products: [
      {
        product_id: PRODUCT_ID,
        product_code: "s2_l2a",
        product_name: "Sentinel-2 L2A",
        bands: [],
        supported_indices: [],
      },
    ],
  })),
}));

vi.mock("@/api/weather", () => ({
  listWeatherProviders: vi.fn(async () => [
    { code: "open_meteo", name: "Open-Meteo", kind: "forecast" },
  ]),
}));

function subscription(over: Record<string, unknown> = {}) {
  return {
    id: "sub-1",
    farm_id: "f1",
    product_id: PRODUCT_ID,
    cadence_hours: 24,
    cloud_cover_max_pct: 30,
    is_active: true,
    fetch_farm_aoi: false,
    last_successful_ingest_at: null,
    last_attempted_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("FarmSubscriptionsPanel", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
    h.imagery.mockResolvedValue([]);
    h.weather.mockResolvedValue([]);
    h.subscribeImagery.mockResolvedValue(subscription());
    h.updateImagery.mockResolvedValue(subscription());
    h.subscribeWeather.mockResolvedValue({});
    h.updateWeather.mockResolvedValue({});
  });

  it("subscribes the farm directly, with no second apply step", async () => {
    const user = userEvent.setup();
    render(<FarmSubscriptionsPanel farmId="f1" />);
    await waitFor(() => expect(screen.getByText("Sentinel-2 L2A")).toBeTruthy());

    await user.click(screen.getByRole("checkbox", { name: /Sentinel-2 L2A/i }));

    // One call, and it is the subscription itself — not a template that
    // something else later reconciles onto blocks.
    await waitFor(() => expect(h.subscribeImagery).toHaveBeenCalledTimes(1));
    expect(h.subscribeImagery).toHaveBeenCalledWith("f1", { product_id: PRODUCT_ID });
  });

  it("shows the whole-farm option only once the product is on", async () => {
    render(<FarmSubscriptionsPanel farmId="f1" />);
    await waitFor(() => expect(screen.getByText("Sentinel-2 L2A")).toBeTruthy());
    // Nothing subscribed yet, so there is nothing to fetch the whole farm for.
    expect(screen.queryByRole("checkbox", { name: /Whole farm/i })).toBeNull();
  });

  it("toggles the whole-farm fetch on an existing subscription", async () => {
    h.imagery.mockResolvedValue([subscription()]);
    const user = userEvent.setup();
    render(<FarmSubscriptionsPanel farmId="f1" />);
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: /Whole farm/i })).toBeTruthy(),
    );

    await user.click(screen.getByRole("checkbox", { name: /Whole farm/i }));

    await waitFor(() => expect(h.updateImagery).toHaveBeenCalledTimes(1));
    expect(h.updateImagery).toHaveBeenCalledWith("f1", "sub-1", { fetch_farm_aoi: true });
  });

  it("names the cost of the whole-farm fetch", async () => {
    render(<FarmSubscriptionsPanel farmId="f1" />);
    // An operator turning this on is spending provider quota; the screen has
    // to say so rather than leaving it to be discovered on the bill.
    await waitFor(() => expect(screen.getByText(/one larger request per pass/i)).toBeTruthy());
  });

  it("treats a blank cadence as the default rather than rejecting it", async () => {
    h.imagery.mockResolvedValue([subscription()]);
    const user = userEvent.setup();
    render(<FarmSubscriptionsPanel farmId="f1" />);
    const box = await screen.findByRole("spinbutton");

    await user.clear(box);
    await user.tab();

    await waitFor(() => expect(h.updateImagery).toHaveBeenCalledTimes(1));
    expect(h.updateImagery).toHaveBeenCalledWith("f1", "sub-1", { cadence_hours: null });
  });

  it("surfaces a failed change instead of silently keeping the old value", async () => {
    h.imagery.mockResolvedValue([subscription()]);
    h.updateImagery.mockRejectedValue(new Error("nope"));
    const user = userEvent.setup();
    render(<FarmSubscriptionsPanel farmId="f1" />);
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: /Whole farm/i })).toBeTruthy(),
    );

    await user.click(screen.getByRole("checkbox", { name: /Whole farm/i }));

    await waitFor(() => expect(screen.getByText(/Could not save that change/i)).toBeTruthy());
  });
});
