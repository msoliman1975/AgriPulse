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
  getConfig: vi.fn(() =>
    Promise.resolve({
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
    }),
  ),
}));

vi.mock("@/api/weather", () => ({
  listWeatherProviders: vi.fn(() =>
    Promise.resolve([{ code: "open_meteo", name: "Open-Meteo", kind: "forecast" }]),
  ),
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
    farm_aoi_fetchable: true,
    farm_aoi_width_px: 420,
    farm_aoi_height_px: 380,
    farm_aoi_max_px: 2500,
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

  it("shows the fetch scope only once the product is on", async () => {
    render(<FarmSubscriptionsPanel farmId="f1" />);
    await waitFor(() => expect(screen.getByText("Sentinel-2 L2A")).toBeTruthy());
    // Nothing subscribed yet, so there is no fetch to describe.
    expect(screen.queryByText(/Fetched per block/i)).toBeNull();
  });

  it("reports the fetch scope without offering to change it", async () => {
    // It was a checkbox, and it read as a preference. It is the cutover
    // switch: `fetch_farm_aoi` also excludes the farm's blocks from the block
    // sweep, so ticking it on a farm too big to fetch left that farm with no
    // imagery at all. The only control that cannot do that is no control.
    h.imagery.mockResolvedValue([subscription()]);
    render(<FarmSubscriptionsPanel farmId="f1" />);

    await waitFor(() => expect(screen.getByText(/Fetched per block/i)).toBeTruthy());
    // The product's own on/off box is the only checkbox left in the row.
    expect(screen.queryByRole("checkbox", { name: /whole farm/i })).toBeNull();
    expect(h.updateImagery).not.toHaveBeenCalled();
  });

  it("says a farm is fetched as one area when it has cut over", async () => {
    h.imagery.mockResolvedValue([subscription({ fetch_farm_aoi: true })]);
    render(<FarmSubscriptionsPanel farmId="f1" />);
    await waitFor(() => expect(screen.getByText(/Fetched as one farm area/i)).toBeTruthy());
  });

  it("says WHY a farm is stuck on per-block fetching, with the measurement", async () => {
    // Without the numbers this reads as an arbitrary refusal. With them, an
    // operator can see how far over the limit the farm is.
    h.imagery.mockResolvedValue([
      subscription({
        farm_aoi_fetchable: false,
        farm_aoi_width_px: 3100,
        farm_aoi_height_px: 1800,
      }),
    ]);
    render(<FarmSubscriptionsPanel farmId="f1" />);

    await waitFor(() => expect(screen.getByText(/too large for one request/i)).toBeTruthy());
    expect(screen.getByText(/3100×1800 px/)).toBeTruthy();
    expect(screen.getByText(/limit 2500/)).toBeTruthy();
  });

  it("does not call a farm too large just because the api has not shipped yet", async () => {
    // Each chart is its own ArgoCD app, so the frontend can reach prod before
    // the api that answers `farm_aoi_fetchable`. Read as a bare falsy check,
    // an absent field reports EVERY farm as too large, sized "undefined".
    const { farm_aoi_fetchable, farm_aoi_width_px, farm_aoi_height_px, ...old } = subscription();
    void farm_aoi_fetchable;
    void farm_aoi_width_px;
    void farm_aoi_height_px;
    h.imagery.mockResolvedValue([old]);
    render(<FarmSubscriptionsPanel farmId="f1" />);

    await waitFor(() => expect(screen.getByText(/Fetched per block/i)).toBeTruthy());
    expect(screen.queryByText(/too large/i)).toBeNull();
    expect(screen.queryByText(/undefined/)).toBeNull();
  });

  it("lets the cloud cap be set, not just the cadence", async () => {
    // The old template exposed this and the first version of this panel did
    // not, so a farm could be subscribed with no way to tune the one setting
    // that decides which passes are usable.
    h.imagery.mockResolvedValue([subscription()]);
    const user = userEvent.setup();
    render(<FarmSubscriptionsPanel farmId="f1" />);
    const boxes = await screen.findAllByRole("spinbutton");
    expect(boxes).toHaveLength(2);

    const cloud = boxes[1];
    await user.clear(cloud);
    await user.type(cloud, "45");
    await user.tab();

    await waitFor(() => expect(h.updateImagery).toHaveBeenCalledTimes(1));
    expect(h.updateImagery).toHaveBeenCalledWith("f1", "sub-1", { cloud_cover_max_pct: 45 });
  });

  it("refuses a cloud cap outside 0-100 rather than sending it", async () => {
    h.imagery.mockResolvedValue([subscription()]);
    const user = userEvent.setup();
    render(<FarmSubscriptionsPanel farmId="f1" />);
    const boxes = await screen.findAllByRole("spinbutton");

    await user.clear(boxes[1]);
    await user.type(boxes[1], "150");
    await user.tab();

    expect(h.updateImagery).not.toHaveBeenCalled();
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
    // Two number inputs now: cadence first, cloud cap second.
    const box = (await screen.findAllByRole("spinbutton"))[0];

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
    const cloud = (await screen.findAllByRole("spinbutton"))[1];

    await user.clear(cloud);
    await user.type(cloud, "45");
    await user.tab();

    await waitFor(() => expect(screen.getByText(/Could not save that change/i)).toBeTruthy());
  });
});
