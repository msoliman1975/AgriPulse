import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { CropAssignmentPanel } from "./CropAssignmentPanel";

const listBlockCrops = vi.fn();
const assignBlockCrop = vi.fn();

vi.mock("@/api/cropAssignments", () => ({
  listBlockCrops: (...a: unknown[]) => listBlockCrops(...a),
  assignBlockCrop: (...a: unknown[]) => assignBlockCrop(...a),
  getBlockCropAttributes: () =>
    Promise.resolve({ block_crop_id: "x", crop_path: "p", definitions: [], values: {} }),
  getBlockCropAttributeHistory: () => Promise.resolve([]),
  putBlockCropAttributes: () => Promise.resolve({}),
}));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
// The cascading picker fetches the catalog; the panel is what's under test.
vi.mock("@/modules/farms/components/CropPicker", () => ({
  CropPicker: () => <div data-testid="crop-picker" />,
}));

const TODAY = new Date();
const iso = (offsetDays: number): string =>
  new Date(TODAY.getTime() + offsetDays * 86_400_000).toISOString().slice(0, 10);

function row(over: Record<string, unknown>) {
  return {
    id: "r1",
    crop_path: "mango",
    effective_from: iso(-400),
    effective_to: null,
    ...over,
  };
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CropAssignmentPanel blockId="b1" farmId="f1" onAssigned={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("<CropAssignmentPanel>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listBlockCrops.mockReset();
    assignBlockCrop.mockReset();
    assignBlockCrop.mockResolvedValue({});
  });

  it("shows the assignment whose range contains today, with its dates", async () => {
    listBlockCrops.mockResolvedValue([
      row({ id: "old", crop_path: "potato", effective_from: iso(-800), effective_to: iso(-400) }),
      row({ id: "now", crop_path: "mango", effective_from: iso(-400), effective_to: null }),
    ]);
    renderPanel();
    // Scope to the current card: "ongoing" also appears in the assign form's
    // help text for an empty end date.
    const card = await screen.findByTestId("current-assignment");
    expect(within(card).getByText("mango")).toBeInTheDocument();
    expect(within(card).getByText(/ongoing/)).toBeInTheDocument();
    expect(card.textContent).toContain(iso(-400));
    // History is off by default — requirement B.
    expect(screen.queryByText("Valid from → until")).not.toBeInTheDocument();
  });

  it("reports no current crop once the last assignment has ended", async () => {
    // The old stored `is_current` flag would still have claimed this block
    // was under potato months after harvest.
    listBlockCrops.mockResolvedValue([
      row({ id: "ended", crop_path: "potato", effective_from: iso(-200), effective_to: iso(-10) }),
    ]);
    renderPanel();
    expect(await screen.findByText(/No crop is assigned/i)).toBeInTheDocument();
  });

  it("reveals every assignment, and the fallow gap between them, on demand", async () => {
    const user = userEvent.setup();
    listBlockCrops.mockResolvedValue([
      row({ id: "a", crop_path: "potato", effective_from: iso(-800), effective_to: iso(-600) }),
      row({ id: "b", crop_path: "mango", effective_from: iso(-400), effective_to: null }),
    ]);
    renderPanel();
    await screen.findByText("mango");
    await user.click(screen.getByLabelText(/Show history/));

    expect(await screen.findByText("Valid from → until")).toBeInTheDocument();
    expect(screen.getByText("potato")).toBeInTheDocument();
    // The 200-day fallow stretch is stated, not left to be inferred.
    expect(screen.getByText(/Fallow/)).toBeInTheDocument();
  });

  it("says which assignment a new one will close, before committing", async () => {
    listBlockCrops.mockResolvedValue([
      row({ id: "open", crop_path: "mango", effective_from: iso(-400), effective_to: null }),
    ]);
    renderPanel();
    expect(await screen.findByText(/This will end mango on/)).toBeInTheDocument();
  });

  it("blocks an overlapping range and names the conflict", async () => {
    const user = userEvent.setup();
    listBlockCrops.mockResolvedValue([
      row({ id: "t", crop_path: "tomato", effective_from: iso(-30), effective_to: iso(60) }),
    ]);
    renderPanel();
    await screen.findByTestId("crop-picker");

    // `from` defaults to today, which lands inside the tomato range.
    expect(await screen.findByText(/Overlaps tomato/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Assign crop/ })).toBeDisabled();

    // Moving the start past the tomato clears it.
    await user.clear(screen.getByLabelText(/Valid from/));
    await user.type(screen.getByLabelText(/Valid from/), iso(60));
    await waitFor(() => expect(screen.queryByText(/Overlaps tomato/)).not.toBeInTheDocument());
  });
});
