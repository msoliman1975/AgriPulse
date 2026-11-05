import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { useTreeImpactConfirm } from "./useTreeImpactConfirm";

// What matters here:
//   * a change that moves no tree saves without a dialog — a dialog that lists
//     nothing teaches people to click through the ones that list something;
//   * a change that moves trees says which, per block, and that a tree still
//     running on other blocks is not leaving the farm;
//   * cancelling does not save; confirming does;
//   * a failed preview never blocks a save the user is allowed to make.

const h = vi.hoisted(() => ({ preview: vi.fn() }));

vi.mock("@/api/farmDecisionTrees", () => ({
  previewFarmTreeImpact: h.preview,
}));

function tree(code: string, over: Record<string, unknown> = {}) {
  return { tree_id: code, code, name_en: code, name_ar: null, enabled: true, ...over };
}

function impact(over: Record<string, unknown> = {}) {
  return {
    farm_id: "f1",
    has_crops_before: true,
    has_crops_after: true,
    blocks: [],
    farm_starting: [],
    farm_stopping: [],
    exclusions_cleared: [],
    changes_anything: false,
    ...over,
  };
}

function Harness(): ReactNode {
  const confirmer = useTreeImpactConfirm();
  const [outcome, setOutcome] = useState<string>("idle");
  return (
    <div>
      <button
        type="button"
        onClick={() =>
          void confirmer
            .confirm("f1", { blocks: [{ block_id: "b1", crop_removed: true }] })
            .then((ok) => setOutcome(ok ? "saved" : "cancelled"))
        }
      >
        go
      </button>
      <span data-testid="outcome">{outcome}</span>
      {confirmer.dialog}
    </div>
  );
}

describe("useTreeImpactConfirm", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
  });

  it("saves without asking when nothing moves", async () => {
    h.preview.mockResolvedValue(impact());
    render(<Harness />);
    await userEvent.click(screen.getByText("go"));
    await waitFor(() => expect(screen.getByTestId("outcome").textContent).toBe("saved"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(h.preview).toHaveBeenCalledWith("f1", {
      blocks: [{ block_id: "b1", crop_removed: true }],
    });
  });

  it("saves when the preview itself fails", async () => {
    h.preview.mockRejectedValue(new Error("boom"));
    render(<Harness />);
    await userEvent.click(screen.getByText("go"));
    await waitFor(() => expect(screen.getByTestId("outcome").textContent).toBe("saved"));
  });

  it("lists what starts and stops on the block, then saves on confirm", async () => {
    h.preview.mockResolvedValue(
      impact({
        changes_anything: true,
        blocks: [
          {
            block_id: "b1",
            label: "B3",
            label_ar: null,
            starting: [tree("citrus_greening")],
            stopping: [tree("mango_anthracnose", { other_blocks: 2 }), tree("mango_flowering")],
          },
        ],
        farm_stopping: [tree("mango_flowering")],
        exclusions_cleared: [tree("mango_flowering", { enabled: false })],
      }),
    );
    render(<Harness />);
    await userEvent.click(screen.getByText("go"));

    await screen.findByText("Decision trees affected by this change");
    expect(screen.getByText("Block B3")).toBeTruthy();
    expect(screen.getByText("Stop on this block (2)")).toBeTruthy();
    expect(screen.getByText("Starts on this block (1)")).toBeTruthy();
    expect(screen.getByText("still runs on 2 other blocks")).toBeTruthy();
    expect(screen.getByText(/You had turned off mango_flowering/)).toBeTruthy();
    expect(screen.getByTestId("outcome").textContent).toBe("idle");

    await userEvent.click(screen.getByText("Save change"));
    await waitFor(() => expect(screen.getByTestId("outcome").textContent).toBe("saved"));
    expect(screen.queryByText("Decision trees affected by this change")).toBeNull();
  });

  it("does not save when cancelled", async () => {
    h.preview.mockResolvedValue(
      impact({
        changes_anything: true,
        farm_starting: [tree("jordan_only", { blocks: 3 })],
      }),
    );
    render(<Harness />);
    await userEvent.click(screen.getByText("go"));
    await screen.findByText("Starts on this farm (1)");
    expect(screen.getByText("on 3 blocks")).toBeTruthy();

    await act(async () => {
      await userEvent.click(screen.getByText("Cancel"));
    });
    await waitFor(() => expect(screen.getByTestId("outcome").textContent).toBe("cancelled"));
  });
});
