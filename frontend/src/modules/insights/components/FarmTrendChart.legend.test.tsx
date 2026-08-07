import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { presetRange } from "../lib/timeRange";

import { FarmTrendChart } from "./FarmTrendChart";

// A farm with a dozen blocks draws a dozen lines on a 10-colour cycle. The
// legend is how a reader cuts that down to the blocks they are asking about,
// so these pin the rules that make it trustworthy: colour follows the block
// and never its position among the visible ones, and the plot can never be
// emptied completely.

const BLOCKS = ["North", "South", "East", "West"];

const h = vi.hoisted(() => ({ timeseries: vi.fn(), annotations: vi.fn() }));

vi.mock("@/api/insights", async () => {
  const actual = await vi.importActual<typeof import("@/api/insights")>("@/api/insights");
  return { ...actual, getFarmIndexTimeseries: h.timeseries, getFarmAnnotations: h.annotations };
});

function renderChart(blockIds: string[] | null = null) {
  h.annotations.mockResolvedValue({ farm_id: "f1", annotations: [] });
  h.timeseries.mockResolvedValue({
    farm_id: "f1",
    index_code: "ndvi",
    granularity: "daily",
    points: BLOCKS.flatMap((name, i) =>
      ["2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"].map((time) => ({
        time,
        block_id: `b${i}`,
        block_name: name,
        value: String(0.4 + i / 10),
      })),
    ),
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FarmTrendChart farmId="f1" range={presetRange("90d")} blockIds={blockIds} />
    </QueryClientProvider>,
  );
}

function legend() {
  return screen.getByRole("group", { name: /blocks shown/i });
}

function showAll() {
  return screen.getByRole("button", { name: "Show all blocks" });
}

function hideAll() {
  return screen.getByRole("button", { name: "Hide all blocks" });
}

function swatchColor(name: string): string | undefined {
  const btn = within(legend()).getByRole("button", { name: new RegExp(name) });
  return btn.querySelector("span[aria-hidden='true']")?.getAttribute("style") ?? undefined;
}

describe("FarmTrendChart legend selection", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
  });

  it("lists every block, all shown to begin with", async () => {
    renderChart();
    await waitFor(() => expect(within(legend()).getAllByRole("button")).toHaveLength(4));
    for (const name of BLOCKS) {
      expect(within(legend()).getByRole("button", { name: new RegExp(name) })).toBeTruthy();
    }
    expect(
      within(legend())
        .getAllByRole("button")
        .every((b) => b.getAttribute("aria-pressed") === "true"),
    ).toBe(true);
  });

  it("mutes a block without repainting the others", async () => {
    const user = userEvent.setup();
    renderChart();
    await waitFor(() => expect(within(legend()).getAllByRole("button")).toHaveLength(4));

    const westBefore = swatchColor("West");
    await user.click(within(legend()).getByRole("button", { name: /North/ }));

    // The muted entry stays in the legend, marked off rather than removed —
    // and West keeps the colour it had, because colour is pinned to the
    // block's index in the full series list, not among the visible ones.
    const north = within(legend()).getByRole("button", { name: /North/ });
    expect(north.getAttribute("aria-pressed")).toBe("false");
    expect(swatchColor("West")).toBe(westBefore);
  });

  it("restores everything from one control", async () => {
    const user = userEvent.setup();
    renderChart();
    await waitFor(() => expect(within(legend()).getAllByRole("button")).toHaveLength(4));

    await user.click(within(legend()).getByRole("button", { name: /North/ }));
    await user.click(within(legend()).getByRole("button", { name: /South/ }));
    await user.click(showAll());

    expect(
      within(legend())
        .getAllByRole("button")
        .every((b) => b.getAttribute("aria-pressed") === "true"),
    ).toBe(true);
    // Always mounted, disabled instead of unmounted — an appearing/vanishing
    // control shifts the legend entries under the reader's cursor mid-click.
    expect(showAll()).toBeDisabled();
    expect(hideAll()).toBeEnabled();
  });

  it("mutes every block from one control, and says so", async () => {
    const user = userEvent.setup();
    renderChart();
    await waitFor(() => expect(within(legend()).getAllByRole("button")).toHaveLength(4));

    await user.click(hideAll());

    expect(
      within(legend())
        .getAllByRole("button")
        .every((b) => b.getAttribute("aria-pressed") === "false"),
    ).toBe(true);
    // The plot must say the reader hid them, not repeat the "no observations
    // yet" empty state — the farm's data is there, it is just muted.
    expect(screen.getByText("All blocks are hidden.")).toBeTruthy();
    expect(screen.queryByText(/No observations yet/)).toBeNull();
    expect(hideAll()).toBeDisabled();
  });

  it("lets the reader mute the last visible block", async () => {
    const user = userEvent.setup();
    renderChart();
    await waitFor(() => expect(within(legend()).getAllByRole("button")).toHaveLength(4));

    for (const name of BLOCKS) {
      await user.click(within(legend()).getByRole("button", { name: new RegExp(name) }));
    }
    // Clicking the fourth block must not silently no-op just because it is
    // the last one left; the all-hidden message is what keeps that readable.
    const pressed = within(legend())
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(0);
    expect(screen.getByText("All blocks are hidden.")).toBeTruthy();
  });

  it("shows every index as a chip instead of hiding them in a dropdown", async () => {
    const user = userEvent.setup();
    renderChart();
    await waitFor(() => expect(within(legend()).getAllByRole("button")).toHaveLength(4));

    const picker = screen.getByRole("radiogroup", { name: /index/i });
    // A dropdown makes the reader already know NDRE exists to go find it.
    for (const code of ["NDVI", "NDWI", "EVI", "SAVI", "NDRE", "GNDVI"]) {
      expect(within(picker).getByRole("radio", { name: code })).toBeTruthy();
    }
    expect(within(picker).getByRole("radio", { name: "NDVI" })).toBeChecked();

    await user.click(within(picker).getByRole("radio", { name: "NDRE" }));
    expect(within(picker).getByRole("radio", { name: "NDRE" })).toBeChecked();
    expect(within(picker).getByRole("radio", { name: "NDVI" })).not.toBeChecked();
  });

  it("drops filtered-out blocks from the legend entirely", async () => {
    // Crop filtering removes a block from the question being asked, so it
    // should not linger as a muted legend entry the reader can re-enable.
    renderChart(["b0", "b1"]);
    await waitFor(() => expect(within(legend()).getAllByRole("button")).toHaveLength(2));
    expect(within(legend()).queryByRole("button", { name: /East/ })).toBeNull();
  });
});
