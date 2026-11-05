import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { FarmDecisionTreesPanel } from "./FarmDecisionTreesPanel";

// The properties worth holding are the ones that would silently mislead
// somebody:
//
//   * the switch shows what the SERVER holds — a failed save must put it
//     back, or the screen claims a tree is off while the sweep still runs it
//   * turning a tree off says what happens to the cards it already opened,
//     because "off" otherwise reads as "those disappear too"
//   * the Arabic build renders Arabic tree names, not English ones under an
//     Arabic heading

const h = vi.hoisted(() => ({
  list: vi.fn(),
  set: vi.fn(),
}));

vi.mock("@/api/farmDecisionTrees", () => ({
  listFarmDecisionTrees: h.list,
  setFarmDecisionTree: h.set,
}));

function tree(over: Record<string, unknown> = {}) {
  return {
    tree_id: "t1",
    code: "mango_canopy_health_v1",
    name_en: "Mango canopy health",
    name_ar: "صحة تاج المانجو",
    scope: "block",
    version: 2,
    source: "platform",
    crop_paths: ["mango"],
    blocks_matched: 2,
    enabled: true,
    ...over,
  };
}

describe("FarmDecisionTreesPanel", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
    h.list.mockResolvedValue({
      farm_id: "f1",
      has_crops: true,
      blocks_total: 3,
      trees: [
        tree(),
        tree({
          tree_id: "t2",
          code: "own_tree_v1",
          name_en: "Our own tree",
          name_ar: null,
          source: "tenant",
        }),
      ],
    });
    h.set.mockResolvedValue({ tree_id: "t1", code: "x", enabled: false, changed: true });
  });

  async function open() {
    render(<FarmDecisionTreesPanel farmId="f1" />);
    await waitFor(() => expect(screen.getByText("Mango canopy health")).toBeTruthy());
  }

  it("asks for a crop before listing any tree", async () => {
    h.list.mockResolvedValue({ farm_id: "f1", has_crops: false, blocks_total: 2, trees: [] });
    render(<FarmDecisionTreesPanel farmId="f1" />);
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toMatch(/Assign a crop to at least one block/),
    );
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("says how many of the farm's blocks each tree matches", async () => {
    await open();
    expect(screen.getAllByText("2 of 3 blocks")).toHaveLength(2);
  });

  it("lists the matching trees and counts how many run here", async () => {
    await open();
    expect(screen.getByText("Our own tree")).toBeTruthy();
    expect(screen.getByText("2 of 2 running on this farm.")).toBeTruthy();
    const boxes = screen.getAllByRole<HTMLInputElement>("checkbox");
    expect(boxes.every((b) => b.checked)).toBe(true);
  });

  it("turns a tree off and sends that to the server", async () => {
    const user = userEvent.setup();
    await open();

    await user.click(screen.getByLabelText("Run Mango canopy health on this farm"));

    expect(h.set).toHaveBeenCalledWith("f1", "t1", false);
    await waitFor(() => expect(screen.getByText("1 of 2 running on this farm.")).toBeTruthy());
  });

  it("puts the switch back when the save fails", async () => {
    const user = userEvent.setup();
    h.set.mockRejectedValue(new Error("boom"));
    await open();

    const box = screen.getByLabelText<HTMLInputElement>("Run Mango canopy health on this farm");
    await user.click(box);

    await waitFor(() => expect(box.checked).toBe(true));
    expect(screen.getByText(/Could not save that change/i)).toBeTruthy();
    expect(screen.getByText("2 of 2 running on this farm.")).toBeTruthy();
  });

  it("says the already-open recommendations and alerts stay", async () => {
    await open();
    expect(
      screen.getByText(/Recommendations and alerts it already opened stay in the Action Center/i),
    ).toBeTruthy();
  });

  it("shows an empty list as 'none match', not as a load failure", async () => {
    h.list.mockResolvedValue({ farm_id: "f1", has_crops: true, blocks_total: 1, trees: [] });
    render(<FarmDecisionTreesPanel farmId="f1" />);
    await waitFor(() =>
      expect(screen.getByText(/No published decision tree matches this farm/i)).toBeTruthy(),
    );
  });

  it("shows a load failure instead of an empty list", async () => {
    h.list.mockRejectedValue(new Error("nope"));
    render(<FarmDecisionTreesPanel farmId="f1" />);
    await waitFor(() =>
      expect(screen.getByText(/Could not load the decision trees/i)).toBeTruthy(),
    );
  });

  it("renders Arabic tree names in the Arabic interface", async () => {
    await setupTestI18n("ar");
    render(<FarmDecisionTreesPanel farmId="f1" />);
    await waitFor(() => expect(screen.getByText("صحة تاج المانجو")).toBeTruthy());
    // The tenant tree has no Arabic name, so it falls back to English rather
    // than rendering blank.
    expect(screen.getByText("Our own tree")).toBeTruthy();
    expect(screen.getByText("أشجار القرار")).toBeTruthy();
  });
});
