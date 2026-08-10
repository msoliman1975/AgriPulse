import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { GrowthStageControl } from "./GrowthStageControl";

const getResolvedTaxonomy = vi.fn();
const listGrowthStages = vi.fn();
const recordGrowthStage = vi.fn();
const updateBlockCrop = vi.fn();

vi.mock("@/api/crops", () => ({
  getResolvedTaxonomy: (...a: unknown[]) => getResolvedTaxonomy(...a),
}));
vi.mock("@/api/cropAssignments", () => ({
  listGrowthStages: (...a: unknown[]) => listGrowthStages(...a),
  recordGrowthStage: (...a: unknown[]) => recordGrowthStage(...a),
  updateBlockCrop: (...a: unknown[]) => updateBlockCrop(...a),
}));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

const MANGO_STAGES = {
  crop_path: "mango",
  phenology_stages: {
    stages: [
      { code: "flowering", name_en: "Flowering", name_ar: "إزهار", order: 2 },
      { code: "pre_flowering", name_en: "Pre-flowering", name_ar: "ما قبل الإزهار", order: 1 },
    ],
  },
  size_classes: null,
};

function assignment(over: Record<string, unknown> = {}) {
  return {
    id: "bc-1",
    crop_path: "mango",
    growth_stage: "pre_flowering",
    growth_stage_updated_at: "2026-03-01T00:00:00Z",
    growth_stage_locked: false,
    ...over,
  } as never;
}

function renderControl(over: Record<string, unknown> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <GrowthStageControl blockId="block-1" farmId="farm-1" assignment={assignment(over)} />
    </QueryClientProvider>,
  );
}

describe("<GrowthStageControl>", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    getResolvedTaxonomy.mockResolvedValue(MANGO_STAGES);
    listGrowthStages.mockResolvedValue([]);
    recordGrowthStage.mockResolvedValue({});
    updateBlockCrop.mockResolvedValue({});
    await setupTestI18n("en");
  });

  it("shows the current stage by its display name, not its code", async () => {
    renderControl();
    // Also present as a dropdown option, so scope to the summary line.
    expect(await screen.findByText("Pre-flowering", { selector: "b" })).toBeInTheDocument();
  });

  it("offers the crop's stages in calendar order", async () => {
    renderControl();
    const select = await screen.findByLabelText("Set stage to");
    // The API returns them unordered; the calendar order is what an agronomist
    // reads down.
    expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "—",
      "Pre-flowering",
      "Flowering",
    ]);
  });

  it("records a transition against the current assignment", async () => {
    const user = userEvent.setup();
    renderControl();

    await user.selectOptions(await screen.findByLabelText("Set stage to"), "flowering");
    await user.click(screen.getByRole("button", { name: "Record stage" }));

    // A transition is an event on the block's timeline, tied to the assignment
    // it belongs to — not a blind field write.
    await waitFor(() =>
      expect(recordGrowthStage).toHaveBeenCalledWith("block-1", {
        stage: "flowering",
        block_crop_id: "bc-1",
      }),
    );
  });

  it("toggles the lock that stops the nightly sweep", async () => {
    const user = userEvent.setup();
    renderControl();

    await user.click(await screen.findByRole("checkbox"));

    await waitFor(() =>
      expect(updateBlockCrop).toHaveBeenCalledWith("block-1", "bc-1", {
        growth_stage_locked: true,
      }),
    );
  });

  it("says so when the crop has no stage calendar", async () => {
    // 20 of 23 crops are in this state, so it is the common case rather than
    // an edge one — and the only place anyone would find out.
    getResolvedTaxonomy.mockResolvedValue({
      crop_path: "wheat",
      phenology_stages: null,
      size_classes: null,
    });
    renderControl({ crop_path: "wheat", growth_stage: null });

    expect(await screen.findByText(/no stage calendar/i)).toBeInTheDocument();
    // Nothing to pick from, so no setter is offered.
    expect(screen.queryByLabelText("Set stage to")).not.toBeInTheDocument();
  });

  it("reports an unset stage rather than rendering an empty line", async () => {
    renderControl({ growth_stage: null, growth_stage_updated_at: null });
    expect(await screen.findByText(/Not set/)).toBeInTheDocument();
  });

  it("surfaces the server's message when a transition is refused", async () => {
    const user = userEvent.setup();
    recordGrowthStage.mockRejectedValue(new Error("stage 'flowering' is not in the crop calendar"));
    renderControl();

    await user.selectOptions(await screen.findByLabelText("Set stage to"), "flowering");
    await user.click(screen.getByRole("button", { name: "Record stage" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/not in the crop calendar/);
  });

  it("lists past transitions with where each came from", async () => {
    listGrowthStages.mockResolvedValue([
      {
        id: "log-1",
        block_id: "block-1",
        block_crop_id: "bc-1",
        stage: "pre_flowering",
        source: "auto",
        confirmed_by: null,
        transition_date: "2026-03-01T00:00:00Z",
        notes: null,
        created_at: "2026-03-01T00:00:00Z",
      },
    ]);
    renderControl();

    // The header shows the same date, so wait on something only the timeline
    // renders — otherwise the assertion passes before the history loads.
    expect(await screen.findByText(/automatic/)).toBeInTheDocument();
    expect(screen.getByText("Stage history")).toBeInTheDocument();
  });
});
