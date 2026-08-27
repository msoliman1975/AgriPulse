import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { FarmZonesPanel } from "./FarmZonesPanel";

// Replaces the grid & anomaly and bulk-rezone tests from
// BlockDefaultsPanel.test.tsx. Zones are farm-level now and there is no
// template-then-apply step, so the properties worth holding changed shape —
// but the dangerous ones did not, and they are all here:
//
//   * a rezone states its cost BEFORE anything is written
//   * it refuses until the farm name is typed exactly
//   * a no-op says what is actually true rather than blaming the blocks
//   * the backfill budget reaches the API
//   * blocks can be handed back to the inherited default (the one-way door)

const h = vi.hoisted(() => ({
  getTpl: vi.fn(),
  putTpl: vi.fn(),
  preview: vi.fn(),
  applyGrid: vi.fn(),
  applyCell: vi.fn(),
}));

vi.mock("@/api/farmConfig", () => ({
  getGridTemplate: h.getTpl,
  putGridTemplate: h.putTpl,
  previewApplyGrid: h.preview,
  applyGrid: h.applyGrid,
  applyGridCellSize: h.applyCell,
}));

const TPL = { cell_size_m: 30, anomaly_z_threshold: 1.5 };

function preview(over: Record<string, unknown> = {}) {
  return {
    rows: [],
    total_rows: 2,
    changed_rows: 1,
    unchanged_rows: 1,
    skipped_rows: 0,
    is_noop: false,
    rezone_rows: 1,
    create_rows: 0,
    blocked_rows: 0,
    scenes_affected: 12,
    requires_confirmation: true,
    ...over,
  };
}

describe("FarmZonesPanel", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
    h.getTpl.mockResolvedValue({ ...TPL });
    h.putTpl.mockResolvedValue({ ...TPL });
    h.preview.mockResolvedValue(preview());
    h.applyGrid.mockResolvedValue({ blocks_touched: 2, total_blocks: 2 });
    h.applyCell.mockResolvedValue({
      blocks_touched: 1,
      total_blocks: 2,
      scenes_queued: 12,
      scenes_stranded: 0,
      farm_scenes_queued: 0,
      scenes_unreplayable: 0,
    });
  });

  async function open() {
    render(<FarmZonesPanel farmId="f1" farmName="Bashier Elkhier" />);
    await waitFor(() => expect(screen.getByText(/Zones \(sub-block grid\)/i)).toBeTruthy());
  }

  it("applies sensitivity in one action, with no separate save step", async () => {
    const user = userEvent.setup();
    await open();
    const box = screen.getByRole("spinbutton", { name: /Anomaly sensitivity/i });

    await user.clear(box);
    await user.type(box, "2");
    await user.tab();

    // Saved AND applied — the old flow needed two buttons and silently did
    // nothing if you pressed only the second.
    await waitFor(() => expect(h.putTpl).toHaveBeenCalledTimes(1));
    expect(h.putTpl).toHaveBeenCalledWith("f1", { ...TPL, anomaly_z_threshold: 2 });
    await waitFor(() => expect(h.applyGrid).toHaveBeenCalledWith("f1", null, false));
  });

  it("states the cost in scenes before anything is written", async () => {
    const user = userEvent.setup();
    await open();

    await user.click(screen.getByRole("button", { name: /Preview changes/i }));

    await waitFor(() => expect(screen.getByText(/12 existing scene/i)).toBeTruthy());
    // Previewing must not have rezoned anything.
    expect(h.applyCell).not.toHaveBeenCalled();
  });

  it("refuses to rezone until the farm name is typed exactly", async () => {
    const user = userEvent.setup();
    await open();
    await user.click(screen.getByRole("button", { name: /Preview changes/i }));
    await waitFor(() => expect(screen.getByText(/Type Bashier Elkhier/i)).toBeTruthy());

    const confirm = screen.getByRole("button", { name: /Apply to blocks/i });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    await user.type(screen.getByRole("textbox"), "Bashier Elkhie");
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    await user.type(screen.getByRole("textbox"), "r");
    await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));
  });

  it("does not demand the farm name when nothing live is retired", async () => {
    h.preview.mockResolvedValue(
      preview({ requires_confirmation: false, rezone_rows: 0, create_rows: 1 }),
    );
    const user = userEvent.setup();
    await open();

    await user.click(screen.getByRole("button", { name: /Preview changes/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Apply to blocks/i })).toBeTruthy(),
    );
    expect(screen.queryByText(/Type Bashier Elkhier/i)).toBeNull();
  });

  it("says what is actually true when nothing would change", async () => {
    h.preview.mockResolvedValue(preview({ is_noop: true, changed_rows: 0 }));
    const user = userEvent.setup();
    await open();

    await user.click(screen.getByRole("button", { name: /Preview changes/i }));

    // The old copy blamed the blocks — "Blocks with no grid yet need a cell
    // size set on the block first" — when the usual cause was an unsaved
    // farm template. There is no unsaved state now, so it can say the truth.
    await waitFor(() => expect(screen.getByText(/every block already matches/i)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Apply to blocks/i })).toBeNull();
  });

  it("passes the backfill budget through when one is set", async () => {
    const user = userEvent.setup();
    await open();
    await user.click(screen.getByRole("button", { name: /Preview changes/i }));
    await waitFor(() => expect(screen.getByText(/Type Bashier Elkhier/i)).toBeTruthy());

    await user.type(screen.getByRole("spinbutton", { name: /Backfill budget/i }), "5");
    await user.type(screen.getByRole("textbox"), "Bashier Elkhier");
    await user.click(screen.getByRole("button", { name: /Apply to blocks/i }));

    await waitFor(() => expect(h.applyCell).toHaveBeenCalledWith("f1", null, "Bashier Elkhier", 5));
  });

  // --- what the apply actually queued ------------------------------------
  //
  // A production apply on 2026-08-27 rezoned 36 blocks and queued zero
  // scenes, because the backfill could not see that farm's scenes. The
  // panel reported the blocks and said nothing about the recompute, so the
  // run read exactly like a healthy one. These pin the difference.

  async function rezone(): Promise<void> {
    const user = userEvent.setup();
    await open();
    await user.click(screen.getByRole("button", { name: /Preview changes/i }));
    await waitFor(() => expect(screen.getByText(/Type Bashier Elkhier/i)).toBeTruthy());
    await user.type(screen.getByRole("textbox"), "Bashier Elkhier");
    await user.click(screen.getByRole("button", { name: /Apply to blocks/i }));
  }

  it("says how many scenes it queued", async () => {
    await rezone();
    await waitFor(() => expect(screen.getByText(/Queued 12 scene/i)).toBeTruthy());
  });

  it("names the farm-wide share of what it queued", async () => {
    h.applyCell.mockResolvedValue({
      blocks_touched: 1,
      total_blocks: 2,
      scenes_queued: 12,
      scenes_stranded: 0,
      farm_scenes_queued: 12,
      scenes_unreplayable: 0,
    });
    await rezone();
    await waitFor(() => expect(screen.getByText(/12 of them cover the whole farm/i)).toBeTruthy());
  });

  it("warns when it queued nothing at all", async () => {
    h.applyCell.mockResolvedValue({
      blocks_touched: 36,
      total_blocks: 36,
      scenes_queued: 0,
      scenes_stranded: 0,
      farm_scenes_queued: 0,
      scenes_unreplayable: 0,
    });
    await rezone();
    await waitFor(() => expect(screen.getByText(/No scene was queued/i)).toBeTruthy());
  });

  it("separates scenes that can never be recomputed from a short budget", async () => {
    h.applyCell.mockResolvedValue({
      blocks_touched: 1,
      total_blocks: 2,
      scenes_queued: 2,
      scenes_stranded: 0,
      farm_scenes_queued: 0,
      scenes_unreplayable: 40,
    });
    await rezone();
    await waitFor(() => expect(screen.getByText(/40 stored scene/i)).toBeTruthy());
    // Still a success, so no warning line: nothing is broken, those dates
    // simply have no bands left to read.
    expect(screen.queryByText(/No scene was queued/i)).toBeNull();
  });

  it("hands blocks back to the inherited default", async () => {
    const user = userEvent.setup();
    await open();

    await user.click(
      screen.getByRole("button", { name: /Reset blocks to the inherited default/i }),
    );

    // clear_override — without it, pushing a farm sensitivity onto blocks is
    // a one-way door.
    await waitFor(() => expect(h.applyGrid).toHaveBeenCalledWith("f1", null, true));
  });

  it("saves the cell size before previewing it", async () => {
    const user = userEvent.setup();
    await open();
    const cell = screen.getByRole("spinbutton", { name: /Cell size/i });

    await user.clear(cell);
    await user.type(cell, "40");
    await user.click(screen.getByRole("button", { name: /Preview changes/i }));

    // The old flow previewed the STORED template, so an unsaved edit produced
    // a confident preview of the wrong number.
    await waitFor(() => expect(h.putTpl).toHaveBeenCalledWith("f1", { ...TPL, cell_size_m: 40 }));
    const putOrder = h.putTpl.mock.invocationCallOrder[0];
    const previewOrder = h.preview.mock.invocationCallOrder[0];
    expect(putOrder).toBeLessThan(previewOrder);
  });
});
