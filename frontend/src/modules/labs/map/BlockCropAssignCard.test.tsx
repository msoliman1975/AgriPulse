import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { BlockCropAssignCard } from "./BlockCropAssignCard";

// The legacy lab map assigns crops through its own card, not the shared
// CropAssignmentPanel. It must ask the same question before saving: which
// decision trees the new crop starts and stops on this block.

const h = vi.hoisted(() => ({ assign: vi.fn(), preview: vi.fn() }));

vi.mock("@/api/cropAssignments", () => ({ assignBlockCrop: h.assign }));
vi.mock("@/api/farmDecisionTrees", () => ({ previewFarmTreeImpact: h.preview }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/modules/settings/components/BulkCropRemovalPanel", () => ({
  BulkCropRemovalPanel: () => null,
}));
vi.mock("@/modules/farms/components/CropPicker", () => ({
  CropPicker: ({
    onChange,
    onValidityChange,
  }: {
    onChange: (c: string, v: string | null, s: string | null) => void;
    onValidityChange: (ok: boolean) => void;
  }) => {
    useEffect(() => {
      onChange("crop-mango", "var-keitt", null);
      onValidityChange(true);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return null;
  },
}));

const impact = {
  farm_id: "f1",
  has_crops_before: true,
  has_crops_after: true,
  blocks: [
    {
      block_id: "b1",
      label: "B1",
      label_ar: null,
      starting: [
        {
          tree_id: "t1",
          code: "mango_flowering",
          name_en: "Mango flowering",
          name_ar: null,
          enabled: true,
        },
      ],
      stopping: [],
    },
  ],
  farm_starting: [],
  farm_stopping: [],
  exclusions_cleared: [],
  changes_anything: true,
};

async function openAndSubmit(): Promise<void> {
  const user = userEvent.setup();
  render(<BlockCropAssignCard blockId="b1" farmId="f1" hasCurrentCrop onAssigned={() => {}} />);
  await user.click(screen.getByText("Change crop"));
  await user.type(screen.getByPlaceholderText("2026A"), "2026A");
  await user.click(screen.getByRole("button", { name: "Save" }));
}

describe("BlockCropAssignCard", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
    h.assign.mockResolvedValue({});
    h.preview.mockResolvedValue(impact);
  });

  it("previews the tree impact of the chosen crop and saves after confirm", async () => {
    await openAndSubmit();
    await screen.findByText("Decision trees affected by this change");
    expect(h.preview).toHaveBeenCalledWith("f1", {
      blocks: [
        {
          block_id: "b1",
          crop_id: "crop-mango",
          crop_variety_id: "var-keitt",
          crop_variety_strain_id: null,
        },
      ],
    });
    expect(h.assign).not.toHaveBeenCalled();

    await userEvent.click(screen.getByText("Save change"));
    await waitFor(() => expect(h.assign).toHaveBeenCalledTimes(1));
  });

  it("does not assign when the dialog is cancelled", async () => {
    await openAndSubmit();
    await screen.findByText("Decision trees affected by this change");
    // The card's own form has a Cancel too; the dialog's is portalled last.
    const cancels = screen.getAllByText("Cancel", { selector: "button" });
    await userEvent.click(cancels[cancels.length - 1]);
    await waitFor(() =>
      expect(screen.queryByText("Decision trees affected by this change")).toBeNull(),
    );
    expect(h.assign).not.toHaveBeenCalled();
  });
});
