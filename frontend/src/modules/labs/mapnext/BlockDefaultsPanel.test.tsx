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
  savedGrid: {
    current: { cell_size_m: null as number | null, anomaly_z_threshold: null as number | null },
  },
  applyGridMock: vi.fn(),
  applyGridCellSizeMock: vi.fn(),
  previewApplyGridMock: vi.fn(),
}));
const applySubscriptionsMock = h.applySubscriptionsMock;
const applyGridMock = h.applyGridMock;
const applyGridCellSizeMock = h.applyGridCellSizeMock;
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
      Promise.resolve({
        irrigation_system: null,
        irrigation_source: null,
        flow_rate_m3_per_hour: null,
      }),
    ),
    getOrgTemplate: vi.fn(() => Promise.resolve({ default_tags: [] })),
    getGridTemplate: vi.fn(() => Promise.resolve(h.savedGrid.current)),
    putGridTemplate: vi.fn((_farmId: string, body: typeof h.savedGrid.current) => {
      h.savedGrid.current = body;
      return Promise.resolve(body);
    }),
    previewApplyGrid: h.previewApplyGridMock,
    applyGrid: h.applyGridMock,
    applyGridCellSize: h.applyGridCellSizeMock,
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
  listWeatherProviders: vi.fn(() => Promise.resolve([{ code: "open_meteo", name: "Open-Meteo" }])),
}));

async function renderPanel() {
  const view = render(<BlockDefaultsPanel farmId="f1" farmName="Bashayer" />);
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

// The grid card inherits the same three guards, and adds a fourth concern:
// its cell-size scope is destructive, so the confirmation must appear only
// when live geometry would actually be retired.

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
    target_cell_size_m: null,
    action: "threshold" as const,
    reason: "Set from the farm template",
    matches: false,
    scenes_affected: 0,
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
    target_cell_size_m: null,
    action: "skipped" as const,
    reason: "No active imagery subscription",
    matches: true,
    scenes_affected: 0,
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
      rezone_rows: 0,
      create_rows: 0,
      blocked_rows: 0,
      scenes_affected: 0,
      requires_confirmation: false,
    });
  });

  async function renderGrid() {
    const view = render(<BlockDefaultsPanel farmId="f1" farmName="Bashayer" />);
    await waitFor(() => expect(screen.getByText(/Grid & anomaly detection/i)).toBeTruthy());
    return view;
  }

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
      rezone_rows: 0,
      create_rows: 0,
      blocked_rows: 0,
      scenes_affected: 0,
      requires_confirmation: false,
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

// ---- Bulk rezone (cell-size scope) ----------------------------------------
//
// The destructive half. The property under test throughout is that the
// confirmation appears exactly when live geometry would be retired — no
// more (or operators learn to type past it) and no less (or a farm-wide
// rezone is one click away).

const REZONE_ROW = {
  block_id: "b1",
  block_code: "A-01",
  block_name: "North Mango 1",
  product_id: "p1",
  product_code: "s2_l2a",
  product_name: "Sentinel-2 L2A",
  native_pixel_m: 10,
  current_cell_size_m: 30,
  current_anomaly_z_threshold: 1.5,
  target_anomaly_z_threshold: null,
  target_cell_size_m: 20,
  action: "rezone" as const,
  reason: "Rezone 30m → 20m",
  matches: false,
  scenes_affected: 214,
};

const BLOCKED_ROW = {
  ...REZONE_ROW,
  block_id: "b3",
  block_code: "A-03",
  action: "blocked" as const,
  reason: "Cell size must be an integer multiple of the source's native pixel (10m).",
  matches: true,
  scenes_affected: 0,
};

describe("BlockDefaultsPanel — bulk rezone", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    h.saved.current = { imagery: [], weather: [] };
    h.savedGrid.current = { cell_size_m: 20, anomaly_z_threshold: null };
    applyGridCellSizeMock.mockReset();
    applyGridCellSizeMock.mockResolvedValue({
      blocks_touched: 1,
      total_blocks: 1,
      scenes_queued: 214,
      scenes_stranded: 0,
    });
    previewApplyGridMock.mockReset();
  });

  function previewWith(rows: unknown[], extra: Record<string, unknown> = {}) {
    previewApplyGridMock.mockResolvedValue({
      rows,
      total_rows: rows.length,
      changed_rows: 1,
      unchanged_rows: 0,
      skipped_rows: 0,
      is_noop: false,
      rezone_rows: 1,
      create_rows: 0,
      blocked_rows: 0,
      scenes_affected: 214,
      requires_confirmation: true,
      ...extra,
    });
  }

  async function openRezonePreview() {
    const user = userEvent.setup();
    render(<BlockDefaultsPanel farmId="f1" farmName="Bashayer" />);
    await waitFor(() => expect(screen.getByText(/Grid & anomaly detection/i)).toBeTruthy());
    await user.click(screen.getByRole("button", { name: /Apply cell size to blocks/i }));
    return user;
  }

  it("asks for the cell_size scope, not the threshold one", async () => {
    previewWith([REZONE_ROW]);
    await openRezonePreview();
    await waitFor(() => expect(previewApplyGridMock).toHaveBeenCalled());
    expect(previewApplyGridMock.mock.calls[0][3]).toBe("cell_size");
  });

  it("states the cost in scenes before anything is applied", async () => {
    previewWith([REZONE_ROW]);
    await openRezonePreview();
    await waitFor(() =>
      expect(screen.getByText(/214 scene\(s\) of history become unreadable/i)).toBeTruthy(),
    );
  });

  it("refuses to rezone until the farm name is typed exactly", async () => {
    previewWith([REZONE_ROW]);
    const user = await openRezonePreview();

    const confirmBtn = await screen.findByRole("button", { name: /Rezone 1 block/i });
    expect(confirmBtn).toBeDisabled();

    const nameField = screen.getByLabelText(/Confirm farm name/i);
    await user.type(nameField, "Bashayr");
    expect(screen.getByRole("button", { name: /Rezone 1 block/i })).toBeDisabled();

    await user.clear(nameField);
    await user.type(nameField, "Bashayer");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Rezone 1 block/i })).toBeEnabled(),
    );

    await user.click(screen.getByRole("button", { name: /Rezone 1 block/i }));
    await waitFor(() => expect(applyGridCellSizeMock).toHaveBeenCalled());
    expect(applyGridCellSizeMock.mock.calls[0][2]).toBe("Bashayer");
  });

  it("does not demand confirmation when nothing live is retired", async () => {
    // A farm being gridded for the first time destroys nothing.
    previewApplyGridMock.mockResolvedValue({
      rows: [
        { ...REZONE_ROW, action: "create" as const, current_cell_size_m: null, scenes_affected: 0 },
      ],
      total_rows: 1,
      changed_rows: 1,
      unchanged_rows: 0,
      skipped_rows: 0,
      is_noop: false,
      rezone_rows: 0,
      create_rows: 1,
      blocked_rows: 0,
      scenes_affected: 0,
      requires_confirmation: false,
    });
    const user = await openRezonePreview();

    await waitFor(() => expect(screen.getByText("A-01")).toBeTruthy());
    expect(screen.queryByLabelText(/Confirm farm name/i)).toBeNull();

    const confirmBtn = screen.getByRole("button", { name: /Apply to 1 block/i });
    expect(confirmBtn).toBeEnabled();
    await user.click(confirmBtn);
    await waitFor(() => expect(applyGridCellSizeMock).toHaveBeenCalled());
  });

  it("excludes blocked rows from the selection", async () => {
    previewWith([REZONE_ROW, BLOCKED_ROW], { total_rows: 2, blocked_rows: 1 });
    const user = await openRezonePreview();

    await waitFor(() => expect(screen.getByText("A-03")).toBeTruthy());
    // The refusal is visible and its checkbox cannot be selected.
    expect(screen.getByLabelText("A-03")).toBeDisabled();
    expect(screen.getByText(/1 row\(s\) refused/i)).toBeTruthy();

    const nameField = screen.getByLabelText(/Confirm farm name/i);
    await user.type(nameField, "Bashayer");
    await user.click(screen.getByRole("button", { name: /Rezone 1 block/i }));

    await waitFor(() => expect(applyGridCellSizeMock).toHaveBeenCalled());
    // Only the rezonable block is submitted.
    expect(applyGridCellSizeMock.mock.calls[0][1]).toEqual(["b1"]);
  });

  it("reports a partial backfill as a warning, not a clean success", async () => {
    previewWith([REZONE_ROW]);
    applyGridCellSizeMock.mockResolvedValue({
      blocks_touched: 1,
      total_blocks: 1,
      scenes_queued: 100,
      scenes_stranded: 114,
    });
    const user = await openRezonePreview();

    const nameField = await screen.findByLabelText(/Confirm farm name/i);
    await user.type(nameField, "Bashayer");
    await user.click(screen.getByRole("button", { name: /Rezone 1 block/i }));

    await waitFor(() =>
      expect(screen.getByText(/114 older scene\(s\) stay on the previous geometry/i)).toBeTruthy(),
    );
  });

  it("passes the backfill budget through when one is set", async () => {
    previewWith([REZONE_ROW]);
    const user = await openRezonePreview();

    const budgetField = await screen.findByLabelText(/Backfill budget/i);
    await user.type(budgetField, "500");
    const nameField = screen.getByLabelText(/Confirm farm name/i);
    await user.type(nameField, "Bashayer");
    await user.click(screen.getByRole("button", { name: /Rezone 1 block/i }));

    await waitFor(() => expect(applyGridCellSizeMock).toHaveBeenCalled());
    expect(applyGridCellSizeMock.mock.calls[0][3]).toBe(500);
  });
});
