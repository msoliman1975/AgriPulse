import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { HeatUnitStartControl } from "./HeatUnitStartControl";

const updateBlockCrop = vi.fn();

vi.mock("@/api/cropAssignments", () => ({
  updateBlockCrop: (...a: unknown[]) => updateBlockCrop(...a),
}));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

function renderControl(gddStartDate: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <HeatUnitStartControl
        blockId="block-1"
        farmId="farm-1"
        assignment={{ id: "bc-1", gdd_start_date: gddStartDate } as never}
      />
    </QueryClientProvider>,
  );
}

describe("<HeatUnitStartControl>", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    updateBlockCrop.mockResolvedValue({});
    await setupTestI18n("en");
  });

  it("says the block follows the crop when no start is set", () => {
    renderControl(null);
    expect(screen.getByText("Follows the crop catalogue's start.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Follow the crop" })).not.toBeInTheDocument();
  });

  it("saves the block's own start date", async () => {
    renderControl(null);
    const input = screen.getByLabelText("Start date for this block");
    await userEvent.type(input, "2026-03-20");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(updateBlockCrop).toHaveBeenCalledWith("block-1", "bc-1", {
        gdd_start_date: "2026-03-20",
      }),
    );
  });

  it("clears an override so the block follows the crop again", async () => {
    renderControl("2026-03-20");
    expect(screen.getByText("Counting from 2026-03-20 on this block.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Follow the crop" }));
    await waitFor(() =>
      expect(updateBlockCrop).toHaveBeenCalledWith("block-1", "bc-1", { gdd_start_date: null }),
    );
  });
});
