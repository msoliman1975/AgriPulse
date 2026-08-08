import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { BulkUpdatesPage } from "./BulkUpdatesPage";

const listBulkCropCandidates = vi.fn();
const previewBulkCropAssignment = vi.fn();
const applyBulkCropAssignment = vi.fn();

vi.mock("@/api/bulkCropAssignment", () => ({
  listBulkCropCandidates: (...a: unknown[]) => listBulkCropCandidates(...a),
  previewBulkCropAssignment: (...a: unknown[]) => previewBulkCropAssignment(...a),
  applyBulkCropAssignment: (...a: unknown[]) => applyBulkCropAssignment(...a),
}));
vi.mock("@/api/farms", () => ({
  listFarms: () =>
    Promise.resolve({ items: [{ id: "farm-1", name: "Bashayer Farm" }], next_cursor: null }),
}));
vi.mock("@/api/crops", () => ({
  resolveCropAttributes: () =>
    Promise.resolve({ crop_path: "wheat", definitions: [], shadowed_codes: [] }),
}));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

// The cascading picker fetches the whole crop catalog; the wizard is what's
// under test. Mirrors the real one's effect-driven callbacks.
vi.mock("@/modules/farms/components/CropPicker", () => ({
  CropPicker: ({
    onChange,
    onValidityChange,
    onCropPathChange,
  }: {
    onChange: (c: string | null, v: string | null, s: string | null) => void;
    onValidityChange?: (ok: boolean) => void;
    onCropPathChange?: (p: string | null) => void;
  }) => {
    const [picked, setPicked] = React.useState(false);
    React.useEffect(() => {
      onCropPathChange?.(picked ? "wheat" : null);
    }, [onCropPathChange, picked]);
    React.useEffect(() => {
      onValidityChange?.(picked);
    }, [onValidityChange, picked]);
    return (
      <button
        type="button"
        data-testid="crop-picker"
        onClick={() => {
          onChange("crop-1", null, null);
          setPicked(true);
        }}
      >
        pick wheat
      </button>
    );
  },
}));

const CANDIDATES = [
  {
    block_id: "b1",
    code: "B1",
    name: "North 01",
    area_value: "4.0",
    area_unit: "feddan",
    unit_type: "block",
    current: null,
  },
  {
    block_id: "b2",
    code: "B2",
    name: "North 02",
    area_value: "6.5",
    area_unit: "feddan",
    unit_type: "block",
    current: {
      block_crop_id: "bc-2",
      crop_path: "mango.alphonso",
      season_label: "2026A",
      planting_date: "2026-02-01",
      effective_from: "2026-02-01",
      status: "growing",
    },
  },
];

function renderPage(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BulkUpdatesPage />
    </QueryClientProvider>,
  );
}

/** Drive steps 1–3 and stop on the review step. */
async function walkToReview(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await screen.findByText("Bashayer Farm");
  await user.selectOptions(screen.getByLabelText(/farm/i), "farm-1");
  await user.click(screen.getByRole("button", { name: /continue/i }));

  await user.click(await screen.findByTestId("crop-picker"));
  await user.type(screen.getByLabelText(/season label/i), "2027A");
  await user.click(screen.getByRole("button", { name: /continue/i }));

  await screen.findByTestId("block-row-B1");
  await user.click(screen.getByRole("button", { name: /select all 2 matching/i }));
  await user.click(screen.getByRole("button", { name: /preview changes/i }));
}

beforeEach(async () => {
  vi.clearAllMocks();
  await setupTestI18n();
  listBulkCropCandidates.mockResolvedValue(CANDIDATES);
});

describe("BulkUpdatesPage", () => {
  it("will not let the user past a step whose required values are missing", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Bashayer Farm");

    // Step 1 with no farm chosen.
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText(/farm/i), "farm-1");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // Step 2 with no crop and no season.
    expect(await screen.findByTestId("crop-picker")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();
  });

  it("posts the picked blocks to preview without writing anything", async () => {
    const user = userEvent.setup();
    previewBulkCropAssignment.mockResolvedValue({
      farm_id: "farm-1",
      conflict_mode: "skip",
      crop_path: "wheat",
      assign_count: 1,
      replace_count: 0,
      skip_count: 1,
      items: [
        {
          block_id: "b1",
          code: "B1",
          name: "North 01",
          outcome: "assign",
          before: null,
          after: {
            crop_path: "wheat",
            season_label: "2027A",
            planting_date: null,
            effective_from: "2026-08-08",
          },
          overridden: false,
          detail: null,
        },
        {
          block_id: "b2",
          code: "B2",
          name: "North 02",
          outcome: "skip",
          before: CANDIDATES[1].current,
          after: null,
          overridden: false,
          detail: "Already carries mango.alphonso (2026A).",
        },
      ],
    });

    renderPage();
    await walkToReview(user);
    await user.click(await screen.findByRole("button", { name: /run preview/i }));

    await waitFor(() => expect(previewBulkCropAssignment).toHaveBeenCalledTimes(1));
    const [farmId, payload] = previewBulkCropAssignment.mock.calls[0];
    expect(farmId).toBe("farm-1");
    expect(payload.season_label).toBe("2027A");
    expect(payload.conflict_mode).toBe("skip");
    expect(payload.targets.map((t: { block_id: string }) => t.block_id).sort()).toEqual([
      "b1",
      "b2",
    ]);

    // The dry run must not have written.
    expect(applyBulkCropAssignment).not.toHaveBeenCalled();
    // Future-tense verbs while nothing has been written.
    expect(within(screen.getByTestId("outcome-row-B1")).getByText(/new assignment/i)).toBeVisible();
    expect(
      within(screen.getByTestId("outcome-row-B2")).getByText(/already has a crop/i),
    ).toBeVisible();
  });

  it("applies the exact payload the preview was built from", async () => {
    const user = userEvent.setup();
    previewBulkCropAssignment.mockResolvedValue({
      farm_id: "farm-1",
      conflict_mode: "skip",
      crop_path: "wheat",
      assign_count: 2,
      replace_count: 0,
      skip_count: 0,
      items: [],
    });
    applyBulkCropAssignment.mockResolvedValue({
      farm_id: "farm-1",
      conflict_mode: "skip",
      crop_path: "wheat",
      applied_count: 1,
      skipped_count: 0,
      failed_count: 1,
      items: [
        {
          block_id: "b1",
          code: "B1",
          name: null,
          outcome: "assigned",
          before: null,
          after: {
            crop_path: "wheat",
            season_label: "2027A",
            planting_date: null,
            effective_from: "2026-08-08",
          },
          overridden: false,
          block_crop_id: "bc-new",
          detail: null,
        },
        {
          block_id: "b2",
          code: "B2",
          name: null,
          outcome: "failed",
          before: null,
          after: null,
          overridden: false,
          block_crop_id: null,
          detail: "Overlaps a scheduled assignment.",
        },
      ],
    });

    renderPage();
    await walkToReview(user);
    await user.click(await screen.findByRole("button", { name: /run preview/i }));
    await user.click(await screen.findByRole("button", { name: /apply to 2 blocks/i }));

    await waitFor(() => expect(applyBulkCropAssignment).toHaveBeenCalledTimes(1));
    expect(applyBulkCropAssignment.mock.calls[0][1]).toEqual(
      previewBulkCropAssignment.mock.calls[0][1],
    );

    // A partial failure is reported per block, not swallowed by the summary.
    expect(await screen.findByText(/1 blocks updated, 1 failed/i)).toBeVisible();
    expect(
      within(screen.getByTestId("outcome-row-B2")).getByText(/overlaps a scheduled assignment/i),
    ).toBeVisible();
  });

  it("drops a stale preview when the block selection changes", async () => {
    const user = userEvent.setup();
    previewBulkCropAssignment.mockResolvedValue({
      farm_id: "farm-1",
      conflict_mode: "skip",
      crop_path: "wheat",
      assign_count: 2,
      replace_count: 0,
      skip_count: 0,
      items: [],
    });

    renderPage();
    await walkToReview(user);
    await user.click(await screen.findByRole("button", { name: /run preview/i }));
    await screen.findByRole("button", { name: /apply to 2 blocks/i });

    // Going back to change the selection must retract the promise the
    // preview made — an Apply button computed from the old picks is the one
    // thing this screen cannot be allowed to show.
    await user.click(screen.getByRole("button", { name: /change selection/i }));
    await user.click(await screen.findByRole("button", { name: /preview changes/i }));

    expect(screen.queryByRole("button", { name: /apply to 2 blocks/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run preview/i })).toBeVisible();
  });
});
