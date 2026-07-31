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
  savedGrid: { current: { cell_size_m: null as number | null, anomaly_z_threshold: null as number | null } },
  applyGridMock: vi.fn(),
  previewApplyGridMock: vi.fn(),
}));
const applySubscriptionsMock = h.applySubscriptionsMock;
const applyGridMock = h.applyGridMock;
const previewApplyGridMock = h.previewApplyGridMock;

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
    getLocks: vi.fn(() =>
      Promise.resolve({ subscriptions: false, irrigation: false, org: false, grid: false }),
    ),
    getIrrigationTemplate: vi.fn(() =>
      Promise.resolve({ irrigation_system: null, irrigation_source: null, flow_rate_m3_per_hour: null }),
    ),
    getOrgTemplate: vi.fn(() => Promise.resolve({ default_tags: [] })),
    getGridTemplate: vi.fn(() => Promise.resolve(h.savedGrid.current)),
    putGridTemplate: vi.fn((_farmId: string, body: typeof h.savedGrid.current) => {
      h.savedGrid.current = body;
      return Promise.resolve(body);
    }),
    previewApplyGrid: h.previewApplyGridMock,
    applyGrid: h.applyGridMock,
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

// The grid card inherits the same three guards. It applies a *threshold*, so
// the destructive-sounding cell-size field must not imply a bulk rezone.

const GRID_ROWS = [
  {
    block_id: "b1",
    block_code: "A-01",
    block_name: "North Mango 1",
    product_id: "p1",
    product_code: "s2_l2a",
    product_name: "Sentinel-2 L2A",
    native_pixel_m: 10,
    current_cell_size_m: 20,
    current_anomaly_z_threshold: 1.5,
    target_anomaly_z_threshold: 1.2,
    action: "threshold" as const,
    reason: "Set from the farm template",
    matches: false,
  },
  {
    block_id: "b2",
    block_code: "A-02",
    block_name: "Windbreak strip",
    product_id: null,
    product_code: null,
    product_name: null,
    native_pixel_m: null,
    current_cell_size_m: null,
    current_anomaly_z_threshold: null,
    target_anomaly_z_threshold: null,
    action: "skipped" as const,
    reason: "No active imagery subscription",
    matches: true,
  },
];

describe("BlockDefaultsPanel — grid & anomaly", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    h.saved.current = { imagery: [], weather: [] };
    h.savedGrid.current = { cell_size_m: null, anomaly_z_threshold: 1.5 };
    applyGridMock.mockReset();
    applyGridMock.mockResolvedValue({ blocks_touched: 1, total_blocks: 2 });
    previewApplyGridMock.mockReset();
    previewApplyGridMock.mockResolvedValue({
      rows: GRID_ROWS,
      total_rows: 2,
      changed_rows: 1,
      unchanged_rows: 0,
      skipped_rows: 1,
      is_noop: false,
    });
  });

  async function renderGrid() {
    const view = render(<BlockDefaultsPanel farmId="f1" />);
    await waitFor(() => expect(screen.getByText(/Grid & anomaly detection/i)).toBeTruthy());
    return view;
  }

  it("warns that cell size is not applied to blocks", async () => {
    await renderGrid();
    expect(screen.getByText(/Cell size is saved on the template but not applied/i)).toBeTruthy();
  });

  it("blocks Apply while the grid template has unsaved edits", async () => {
    const user = userEvent.setup();
    await renderGrid();

    const field = screen.getByLabelText(/Anomaly sensitivity/i);
    await user.clear(field);
    await user.type(field, "1.2");

    // Two Apply buttons exist (subscriptions + grid); the grid one is last.
    const applyButtons = screen.getAllByRole("button", { name: /Apply to blocks/i });
    expect(applyButtons[applyButtons.length - 1]).toBeDisabled();
    expect(previewApplyGridMock).not.toHaveBeenCalled();
  });

  it("previews and applies once the template is saved", async () => {
    const user = userEvent.setup();
    await renderGrid();

    const field = screen.getByLabelText(/Anomaly sensitivity/i);
    await user.clear(field);
    await user.type(field, "1.2");
    const saveButtons = screen.getAllByRole("button", { name: /Save template/i });
    await user.click(saveButtons[saveButtons.length - 1]);

    const applyButtons = screen.getAllByRole("button", { name: /Apply to blocks/i });
    await waitFor(() => expect(applyButtons[applyButtons.length - 1]).toBeEnabled());
    await user.click(applyButtons[applyButtons.length - 1]);

    // Preview lists both rows; the skipped one explains itself.
    await waitFor(() => expect(screen.getByText("A-01")).toBeTruthy());
    expect(screen.getByText(/No active imagery subscription/i)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /Apply to 1 block/i }));
    await waitFor(() => expect(applyGridMock).toHaveBeenCalled());
    // Only the changed row's block is submitted — the skipped one is not.
    expect(applyGridMock.mock.calls[0][1]).toEqual(["b1"]);
  });

  it("disables confirm and warns when nothing would change", async () => {
    const user = userEvent.setup();
    previewApplyGridMock.mockResolvedValue({
      rows: [{ ...GRID_ROWS[1] }],
      total_rows: 1,
      changed_rows: 0,
      unchanged_rows: 0,
      skipped_rows: 1,
      is_noop: true,
    });
    await renderGrid();

    const applyButtons = screen.getAllByRole("button", { name: /Apply to blocks/i });
    await user.click(applyButtons[applyButtons.length - 1]);

    await waitFor(() => expect(screen.getByText(/Nothing to apply/i)).toBeTruthy());
    expect(screen.getByRole("button", { name: /Apply to 0 block/i })).toBeDisabled();
    expect(applyGridMock).not.toHaveBeenCalled();
  });

  it("sends clear_override when the inherit checkbox is ticked", async () => {
    const user = userEvent.setup();
    await renderGrid();

    await user.click(screen.getByLabelText(/Clear each block's override/i));
    const applyButtons = screen.getAllByRole("button", { name: /Apply to blocks/i });
    await user.click(applyButtons[applyButtons.length - 1]);

    await waitFor(() => expect(previewApplyGridMock).toHaveBeenCalled());
    expect(previewApplyGridMock.mock.calls[0][2]).toBe(true);
  });
});
