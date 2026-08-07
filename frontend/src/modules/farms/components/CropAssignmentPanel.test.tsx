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

const resolveCropAttributes = vi.fn();
vi.mock("@/api/crops", () => ({
  resolveCropAttributes: (...a: unknown[]) => resolveCropAttributes(...a),
}));
// The cascading picker fetches the catalog; the panel is what's under test.
vi.mock("@/modules/farms/components/CropPicker", () => ({
  CropPicker: ({
    onChange,
    onValidityChange,
    onCropPathChange,
  }: {
    onChange: (c: string | null, v: string | null, s: string | null) => void;
    onValidityChange?: (ok: boolean) => void;
    onCropPathChange?: (p: string | null) => void;
  }) => (
    <button
      type="button"
      data-testid="crop-picker"
      onClick={() => {
        onChange("crop-1", null, null);
        onValidityChange?.(true);
        onCropPathChange?.("tomato");
      }}
    >
      pick tomato
    </button>
  ),
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
    resolveCropAttributes.mockReset();
    resolveCropAttributes.mockResolvedValue({
      crop_path: "tomato",
      shadowed_codes: [],
      definitions: [
        {
          code: "planting_material",
          name_en: "Planting material",
          name_ar: "x",
          value_type: "single_select",
          unit_en: null,
          unit_ar: null,
          is_required: true,
          show_when: null,
          required_when: null,
          options: [
            { code: "nursery_seedling", name_en: "Nursery seedling", name_ar: "x", sort_order: 1 },
          ],
        },
      ],
    });
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

describe("<CropAssignmentPanel> crop fields on the same screen", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listBlockCrops.mockResolvedValue([]);
  });

  it("shows the crop's fields as soon as a crop is picked, before any save", async () => {
    // The whole point: no assign → save → come back and fill in.
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByTestId("crop-picker"));
    expect(await screen.findByText("Crop fields")).toBeInTheDocument();
    expect(screen.getByLabelText(/Planting material/)).toBeInTheDocument();
    expect(resolveCropAttributes).toHaveBeenCalledWith("tomato");
    // Nothing was saved to get here.
    expect(assignBlockCrop).not.toHaveBeenCalled();
  });

  it("blocks the save while a required crop field is empty", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByTestId("crop-picker"));
    await screen.findByLabelText(/Planting material/);
    await user.type(screen.getByLabelText(/Season/), "2026");
    // The server would reject the whole transaction, so the form does too.
    expect(screen.getByRole("button", { name: /Assign crop/ })).toBeDisabled();
  });

  it("sends the crop fields with the assignment, in one request", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByTestId("crop-picker"));
    await screen.findByLabelText(/Planting material/);
    await user.type(screen.getByLabelText(/Season/), "2026");
    await user.selectOptions(screen.getByLabelText(/Planting material/), "nursery_seedling");

    await user.click(screen.getByRole("button", { name: /Assign crop/ }));

    await waitFor(() => expect(assignBlockCrop).toHaveBeenCalledTimes(1));
    expect(assignBlockCrop.mock.calls[0][1].attributes).toEqual({
      planting_material: "nursery_seedling",
    });
  });
});
