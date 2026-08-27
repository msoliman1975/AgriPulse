import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { ManagePanel } from "./ManagePanel";

// "Edit details" in the block dock is the only rename path for a block in
// either console, so it is also the only way to give an existing block an
// Arabic name. `blocks.name_ar` and every reader of it shipped before this
// input did.

const h = vi.hoisted(() => ({ getBlock: vi.fn(), updateBlock: vi.fn() }));

vi.mock("@/api/blocks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/blocks")>()),
  getBlock: h.getBlock,
  updateBlock: h.updateBlock,
}));

function block(over: Record<string, unknown> = {}) {
  return {
    id: "b1",
    farm_id: "f1",
    code: "B-12",
    name: "North strip",
    name_ar: null,
    irrigation_system: null,
    irrigation_source: null,
    soil_texture: null,
    salinity_class: null,
    soil_ph: null,
    notes: null,
    tags: [],
    ...over,
  };
}

function renderEdit() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ManagePanel
        mode="edit"
        blockId="b1"
        farmId="f1"
        gridProductId={null}
        responsibleMembershipId={null}
        onDone={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("ManagePanel — Arabic block name", () => {
  beforeEach(() => {
    h.getBlock.mockReset();
    h.updateBlock.mockReset();
    h.updateBlock.mockResolvedValue(block());
  });

  it("saves an Arabic name typed onto a block that had none", async () => {
    await setupTestI18n("en");
    h.getBlock.mockResolvedValue(block());
    renderEdit();
    const user = userEvent.setup();

    const field = await screen.findByLabelText("Arabic block name");
    await user.type(field, "الشريط الشمالي");
    await user.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => expect(h.updateBlock).toHaveBeenCalledTimes(1));
    expect(h.updateBlock).toHaveBeenCalledWith(
      "b1",
      expect.objectContaining({ name: "North strip", name_ar: "الشريط الشمالي" }),
    );
  });

  it("shows the stored Arabic name and sends null when it is cleared", async () => {
    await setupTestI18n("en");
    h.getBlock.mockResolvedValue(block({ name_ar: "الشريط الشمالي" }));
    renderEdit();
    const user = userEvent.setup();

    const field = await screen.findByLabelText("Arabic block name");
    expect(field).toHaveValue("الشريط الشمالي");

    await user.clear(field);
    await user.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => expect(h.updateBlock).toHaveBeenCalledTimes(1));
    expect(h.updateBlock.mock.calls[0][1].name_ar).toBeNull();
  });
});
