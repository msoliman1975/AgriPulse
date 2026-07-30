import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { BlockDefaultsPanel } from "./BlockDefaultsPanel";

// Regression cover for the "Apply to blocks does nothing but says it worked"
// bug: Apply reconciles blocks against the template STORED ON THE SERVER, so
// an empty or unsaved template makes it a no-op. It used to report that no-op
// as a green success ("Applied to 0 block(s)").

const PRODUCT_ID = "019eab8c-6550-7827-b10d-007109e77470";

// vi.mock factories are hoisted above the module body, so anything they close
// over has to be created inside vi.hoisted.
const h = vi.hoisted(() => ({
  saved: { current: { imagery: [] as unknown[], weather: [] as unknown[] } },
  applySubscriptionsMock: vi.fn(),
}));
const applySubscriptionsMock = h.applySubscriptionsMock;

vi.mock("@/api/farmConfig", async () => {
  const actual = await vi.importActual<typeof import("@/api/farmConfig")>("@/api/farmConfig");
  return {
    ...actual,
    getSubscriptionsTemplate: vi.fn(() => Promise.resolve(h.saved.current)),
    replaceSubscriptionsTemplate: vi.fn((_farmId: string, body: typeof h.saved.current) => {
      h.saved.current = body;
      return Promise.resolve(body);
    }),
    // Mirrors the real backend on the reported farm: 36 blocks, all of which
    // "match" an empty template, so nothing would change.
    previewApplySubscriptions: vi.fn(() =>
      Promise.resolve({
        imagery: Array.from({ length: 36 }, (_, i) => ({
          block_id: `b${i}`,
          will_add: [],
          will_update: [],
          will_deactivate: [],
          matches: true,
        })),
        weather: Array.from({ length: 36 }, (_, i) => ({
          block_id: `b${i}`,
          will_add: [],
          will_update: [],
          will_deactivate: [],
          matches: true,
        })),
        total_blocks: 36,
        matched_blocks: 36,
      }),
    ),
    applySubscriptions: h.applySubscriptionsMock,
    getLocks: vi.fn(() => Promise.resolve({ subscriptions: false, irrigation: false, org: false })),
    getIrrigationTemplate: vi.fn(() =>
      Promise.resolve({ irrigation_system: null, irrigation_source: null, flow_rate_m3_per_hour: null }),
    ),
    getOrgTemplate: vi.fn(() => Promise.resolve({ default_tags: [] })),
  };
});

vi.mock("@/api/config", () => ({
  getConfig: vi.fn(() =>
    Promise.resolve({
      tile_server_base_url: "https://tiles.example",
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
    Promise.resolve([{ code: "open_meteo", name: "Open-Meteo" }]),
  ),
}));

async function renderPanel() {
  const view = render(<BlockDefaultsPanel farmId="f1" />);
  // Wait for the initial template load to settle.
  await waitFor(() => expect(screen.getByText(/Save subscriptions template/i)).toBeTruthy());
  return view;
}

describe("BlockDefaultsPanel — apply subscriptions", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    h.saved.current = { imagery: [], weather: [] };
    applySubscriptionsMock.mockReset();
    applySubscriptionsMock.mockResolvedValue({
      blocks_touched: 0,
      imagery_added: 0,
      imagery_updated: 0,
      imagery_deactivated: 0,
      weather_added: 0,
      weather_updated: 0,
      weather_deactivated: 0,
    });
  });

  it("explains that an empty saved template would change nothing", async () => {
    await renderPanel();
    expect(screen.getByText(/saved template is empty/i)).toBeTruthy();
  });

  it("blocks Apply while the template has unsaved edits", async () => {
    const user = userEvent.setup();
    await renderPanel();

    // Add an imagery row but deliberately do NOT save it.
    await user.click(screen.getByRole("button", { name: /Add product/i }));

    const applyBtn = screen.getByRole("button", { name: /Apply subscriptions to blocks/i });
    expect(applyBtn).toBeDisabled();
    expect(screen.getByText(/unsaved template changes/i)).toBeTruthy();
  });

  it("re-enables Apply once the template is saved", async () => {
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole("button", { name: /Add product/i }));
    await user.click(screen.getByRole("button", { name: /Save subscriptions template/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Apply subscriptions to blocks/i })).toBeEnabled(),
    );
    expect(screen.queryByText(/unsaved template changes/i)).toBeNull();
  });

  it("does not offer a confirm button when every block already matches", async () => {
    const user = userEvent.setup();
    await renderPanel();

    await user.click(screen.getByRole("button", { name: /Apply subscriptions to blocks/i }));

    await waitFor(() => expect(screen.getByText(/36 of 36 blocks already match/i)).toBeTruthy());
    expect(screen.getByRole("button", { name: /Confirm apply/i })).toBeDisabled();
    // The whole point: the user can no longer trigger a no-op that claims success.
    expect(applySubscriptionsMock).not.toHaveBeenCalled();
  });
});
