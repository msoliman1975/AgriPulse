import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SeasonContextCrop } from "@/api/insights";
import { setupTestI18n } from "@/i18n/testing";

import { blocksForCrops, SeasonContextBar } from "./SeasonContextBar";

// The crop chips were read-only labels and are now the overview's filter.
// What matters is that "All" is reachable, that a block planted with two
// crops is counted once, and that "no matching blocks" never degrades into
// "show everything".

const CROPS: SeasonContextCrop[] = [
  { crop_id: "c-mango", name_en: "Mango", name_ar: "مانجو", block_count: 2, block_ids: ["b1", "b2"] },
  { crop_id: "c-palm", name_en: "Date palm", name_ar: null, block_count: 2, block_ids: ["b2", "b3"] },
];

const h = vi.hoisted(() => ({ context: vi.fn() }));

vi.mock("@/api/insights", async () => {
  const actual = await vi.importActual<typeof import("@/api/insights")>("@/api/insights");
  return { ...actual, getFarmSeasonContext: h.context };
});

function Harness() {
  const [selected, setSelected] = useState<string[]>([]);
  return (
    <>
      <SeasonContextBar farmId="f1" selected={selected} onChange={setSelected} />
      <output data-testid="selection">{selected.join(",")}</output>
    </>
  );
}

function renderBar(crops: SeasonContextCrop[] = CROPS) {
  h.context.mockResolvedValue({ farm_id: "f1", crops, active_block_count: 3 });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Harness />
    </QueryClientProvider>,
  );
}

describe("SeasonContextBar as a crop filter", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
  });

  it("starts on All, with every crop offered", async () => {
    renderBar();
    await waitFor(() => expect(screen.getByRole("button", { name: /Mango/ })).toBeTruthy());
    expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /Date palm/ }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  it("selects several crops at once and clears back to All", async () => {
    const user = userEvent.setup();
    renderBar();
    await waitFor(() => expect(screen.getByRole("button", { name: /Mango/ })).toBeTruthy());

    await user.click(screen.getByRole("button", { name: /Mango/ }));
    await user.click(screen.getByRole("button", { name: /Date palm/ }));
    expect(screen.getByTestId("selection").textContent).toBe("c-mango,c-palm");
    // With a filter on, the bar has to say what it does NOT cover — the
    // weather rows are centroid data and stay farm-wide.
    expect(screen.getByText(/farm weather is centroid data/i)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByTestId("selection").textContent).toBe("");
    expect(screen.queryByText(/farm weather is centroid data/i)).toBeNull();
  });

  it("deselects a crop by clicking it again", async () => {
    const user = userEvent.setup();
    renderBar();
    await waitFor(() => expect(screen.getByRole("button", { name: /Mango/ })).toBeTruthy());

    await user.click(screen.getByRole("button", { name: /Mango/ }));
    await user.click(screen.getByRole("button", { name: /Mango/ }));
    expect(screen.getByTestId("selection").textContent).toBe("");
    expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true");
  });
});

describe("blocksForCrops", () => {
  it("means every block when nothing is selected", () => {
    // null, not [] — "all blocks" and "no blocks" must not be the same value.
    expect(blocksForCrops(CROPS, [])).toBeNull();
    expect(blocksForCrops(undefined, ["c-mango"])).toBeNull();
  });

  it("unions the blocks of every selected crop, counting a shared block once", () => {
    // b2 is planted with both crops; block_count would double-count it.
    expect(blocksForCrops(CROPS, ["c-mango", "c-palm"])?.sort()).toEqual(["b1", "b2", "b3"]);
    expect(blocksForCrops(CROPS, ["c-mango"])?.sort()).toEqual(["b1", "b2"]);
  });

  it("returns an empty list, not null, for a crop with no blocks", () => {
    // An empty list filters everything out; null would show the whole farm
    // under a label saying it was filtered.
    const orphan: SeasonContextCrop[] = [
      { crop_id: "c-none", name_en: "Fallow", name_ar: null, block_count: 0, block_ids: [] },
    ];
    expect(blocksForCrops(orphan, ["c-none"])).toEqual([]);
  });
});
