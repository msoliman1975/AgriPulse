import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { BulkCropRemovalPanel } from "./BulkCropRemovalPanel";

const previewBulkCropRemoval = vi.fn();
const removeBulkCropAssignments = vi.fn();

vi.mock("@/api/bulkCropAssignment", () => ({
  previewBulkCropRemoval: (...a: unknown[]) => previewBulkCropRemoval(...a),
  removeBulkCropAssignments: (...a: unknown[]) => removeBulkCropAssignments(...a),
}));

const PREVIEW = {
  farm_id: "farm-1",
  block_count: 1,
  assignment_count: 2,
  attribute_value_count: 3,
  attribute_value_log_count: 4,
  growth_stage_log_count: 5,
  recommendation_unlink_count: 6,
  reopened_count: 0,
  items: [
    {
      block_id: "b1",
      code: "B1",
      name: "North 01",
      removed_count: 0,
      detail: null,
      assignments: [
        {
          block_crop_id: "bc-1",
          crop_path: "mango.alphonso",
          season_label: "2026A",
          effective_from: "2026-01-01",
          effective_to: null,
          is_current: true,
        },
        {
          block_crop_id: "bc-2",
          crop_path: "wheat",
          season_label: "2025A",
          effective_from: "2025-01-01",
          effective_to: "2026-01-01",
          is_current: false,
        },
      ],
    },
  ],
};

function renderPanel(onRemoved = vi.fn()): { onRemoved: ReturnType<typeof vi.fn> } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BulkCropRemovalPanel farmId="farm-1" payload={{ block_ids: ["b1"] }} onRemoved={onRemoved} />
    </QueryClientProvider>,
  );
  return { onRemoved };
}

beforeEach(async () => {
  vi.clearAllMocks();
  await setupTestI18n();
  previewBulkCropRemoval.mockResolvedValue(PREVIEW);
  removeBulkCropAssignments.mockResolvedValue({ ...PREVIEW, items: [] });
});

describe("BulkCropRemovalPanel", () => {
  it("shows what would be destroyed before offering to delete", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: /check what would be removed/i }));

    await screen.findByText(/permanently delete 2 crop assignment/i);
    // The cascade is spelled out: these rows vanish silently otherwise.
    expect(screen.getByText(/3 crop field value/i)).toBeVisible();
    expect(screen.getByText(/5 growth-stage log/i)).toBeVisible();
    expect(screen.getByText(/6 recommendation/i)).toBeVisible();
    // Both seasons listed, not just the current one.
    expect(screen.getByText("mango.alphonso")).toBeVisible();
    expect(screen.getByText("wheat")).toBeVisible();
    // Checking must not delete.
    expect(removeBulkCropAssignments).not.toHaveBeenCalled();
  });

  it("keeps the delete disabled until the confirmation word is typed", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole("button", { name: /check what would be removed/i }));

    const del = await screen.findByRole("button", { name: /permanently delete 2/i });
    expect(del).toBeDisabled();

    await user.type(screen.getByLabelText(/type remove to confirm/i), "remov");
    expect(del).toBeDisabled();

    await user.type(screen.getByLabelText(/type remove to confirm/i), "e");
    expect(del).toBeEnabled();

    await user.click(del);
    await waitFor(() => expect(removeBulkCropAssignments).toHaveBeenCalledTimes(1));
    expect(removeBulkCropAssignments).toHaveBeenCalledWith("farm-1", { block_ids: ["b1"] });
  });

  it("offers nothing to delete when the blocks are already empty", async () => {
    const user = userEvent.setup();
    previewBulkCropRemoval.mockResolvedValue({
      ...PREVIEW,
      assignment_count: 0,
      items: [
        {
          block_id: "b1",
          code: "B1",
          name: null,
          removed_count: 0,
          detail: "No crop assignments on this block.",
          assignments: [],
        },
      ],
    });
    renderPanel();
    await user.click(screen.getByRole("button", { name: /check what would be removed/i }));

    await screen.findByText(/nothing to remove/i);
    expect(screen.queryByRole("button", { name: /permanently delete/i })).not.toBeInTheDocument();
  });

  it("surfaces a server refusal instead of implying success", async () => {
    const user = userEvent.setup();
    removeBulkCropAssignments.mockRejectedValue({
      isApiError: true,
      problem: { title: "Conflict", detail: "expected to remove 2 assignment(s) but removed 1" },
    });
    const { onRemoved } = renderPanel();

    await user.click(screen.getByRole("button", { name: /check what would be removed/i }));
    await user.type(await screen.findByLabelText(/type remove to confirm/i), "REMOVE");
    await user.click(screen.getByRole("button", { name: /permanently delete 2/i }));

    await screen.findByText(/could not delete the assignments/i);
    expect(onRemoved).not.toHaveBeenCalled();
  });
});
